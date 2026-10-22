"""Reliable text-to-speech for BMO.

Why this module exists
----------------------
``pyttsx3`` keeps its engines in a module-level ``weakref.WeakValueDictionary``,
so ``pyttsx3.init()`` hands back the *same* engine object while any reference to
it is still alive.

Reusing an engine is what broke BMO's voice. After the first ``runAndWait()``
the driver's internal ``_busy`` flag is left ``False``, so on the next utterance
``say()`` is no longer deferred: SAPI starts speaking immediately, *before* the
event loop runs. ``runAndWait()`` then starts that loop, which pumps the queued
``endLoop`` command, which calls the driver's ``stop()`` -- purging the utterance
that had only just started. The call returns in ~0.2s having said nothing.

The cure is to build a genuinely fresh engine for every utterance and to drop
every reference to the old one *before* the next ``init()`` call. That is the
same pattern as the standalone ``voice_test.py``, which always worked because
its engine was a function local that died on return.

Speech runs on a single worker thread so the Pygame loop never blocks, and so
two engines can never talk over each other.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Protocol

log = logging.getLogger(__name__)

#: Words per minute. 160 is a little slower than default and easier to follow.
DEFAULT_RATE = 160

#: Sentinel pushed onto the queue to tell the worker thread to finish.
_STOP = object()


class SpeechBackend(Protocol):
    """Something that can say one phrase out loud, synchronously.

    Implementations block until the phrase has finished playing. A future
    Windows-native backend (PowerShell / .NET ``System.Speech``) or a Raspberry
    Pi backend can be dropped in here without touching :class:`SpeechEngine`.
    """

    name: str

    def say(self, text: str) -> None:
        """Speak ``text`` and return once it has finished playing."""


def _evict_cached_engine() -> None:
    """Clear pyttsx3's engine cache so the next ``init()`` builds a new engine.

    Dropping our own reference is normally enough on CPython, but clearing the
    entry makes the guarantee explicit and survives a reference we do not
    control -- for example a traceback still holding on to a frame.
    """
    try:
        import pyttsx3

        pyttsx3._activeEngines.clear()
    except Exception:  # pragma: no cover - cleanup must never break speech
        log.debug("could not clear the pyttsx3 engine cache", exc_info=True)


class Pyttsx3Backend:
    """Speaks via pyttsx3, building a fresh engine for every utterance.

    Creating an engine costs roughly 0.3s. That is a fair price for speech that
    actually comes out, and it happens on the worker thread, not the UI thread.
    """

    name = "pyttsx3"

    def __init__(self, rate: int = DEFAULT_RATE, volume: float | None = None) -> None:
        self.rate = rate
        self.volume = volume

    def say(self, text: str) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        try:
            engine.setProperty("rate", self.rate)
            if self.volume is not None:
                engine.setProperty("volume", self.volume)
            engine.say(text)
            engine.runAndWait()
        finally:
            # Stop first, in case runAndWait raised while audio was in flight.
            try:
                engine.stop()
            except Exception:
                log.debug("engine.stop() failed during cleanup", exc_info=True)
            del engine
            _evict_cached_engine()


class SpeechEngine:
    """A queue plus one worker thread that speaks whatever is put on it.

    Requests are spoken in order, one at a time. Nothing is dropped silently:
    a request that cannot be accepted is logged as a warning, and a backend
    failure is logged with its traceback without killing the worker.
    """

    def __init__(
        self,
        backend: SpeechBackend | None = None,
        *,
        thread_name: str = "bmo-speech",
    ) -> None:
        self.backend: SpeechBackend = backend if backend is not None else Pyttsx3Backend()
        self.spoken_count = 0
        self.error_count = 0
        self.dropped_count = 0

        self._queue: queue.Queue = queue.Queue()
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name=thread_name, daemon=True)
        self._thread.start()
        log.info("speech worker started (backend=%s)", self.backend.name)

    # ------------------------------------------------------------------ API

    def speak(self, text: str) -> bool:
        """Queue ``text`` to be spoken. Returns False if it was not accepted."""
        if self._stopping.is_set():
            self.dropped_count += 1
            log.warning("speech request dropped, engine is shutting down: %r", text)
            return False
        if not text or not text.strip():
            self.dropped_count += 1
            log.warning("speech request dropped, text was empty")
            return False
        self._queue.put(text)
        return True

    @property
    def pending(self) -> int:
        """How many requests are queued but not yet finished."""
        return self._queue.unfinished_tasks

    def is_alive(self) -> bool:
        """True while the worker thread is running."""
        return self._thread.is_alive()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Block until everything queued has been spoken. Mainly for tests."""
        if timeout is None:
            self._queue.join()
            return True
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.01)
        return True

    def shutdown(self, timeout: float = 5.0, *, drain: bool = False) -> bool:
        """Stop the worker thread and release audio resources.

        By default any not-yet-started requests are discarded so closing BMO
        feels immediate. The utterance already playing cannot be interrupted,
        so we wait up to ``timeout`` seconds for it. Returns True if the thread
        finished cleanly.
        """
        if self._stopping.is_set() and not self._thread.is_alive():
            return True

        self._stopping.set()

        if not drain:
            discarded = 0
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
                self._queue.task_done()
                discarded += 1
            if discarded:
                self.dropped_count += discarded
                log.info("discarded %d queued utterance(s) on shutdown", discarded)

        self._queue.put(_STOP)
        self._thread.join(timeout)

        if self._thread.is_alive():
            log.warning(
                "speech worker did not stop within %.1fs; it is a daemon thread "
                "so the process can still exit",
                timeout,
            )
            return False

        log.info(
            "speech worker stopped (spoken=%d errors=%d dropped=%d)",
            self.spoken_count,
            self.error_count,
            self.dropped_count,
        )
        return True

    # --------------------------------------------------------------- worker

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                try:
                    self.backend.say(item)
                    self.spoken_count += 1
                except Exception:
                    self.error_count += 1
                    # Visible in the development console, with a traceback,
                    # and the worker keeps going.
                    log.exception("speech failed for %r", item)
            finally:
                self._queue.task_done()
