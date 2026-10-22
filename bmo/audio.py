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

import contextlib
import logging
import os
import queue
import tempfile
import threading
import time
from typing import Protocol
from xml.sax.saxutils import escape

from bmo import config

log = logging.getLogger(__name__)

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


def find_voice_id(voices, wanted: str) -> str | None:
    """Match a voice by name substring, or by exact id. Case-insensitive.

    Kept as a plain function over (name, id) objects so it can be tested
    without a speech engine.
    """
    needle = wanted.strip().lower()
    if not needle:
        return None
    for voice in voices:
        if needle == voice.id.lower():
            return voice.id
    for voice in voices:
        if needle in voice.name.lower():
            return voice.id
    return None


#: SAPI accepts pitch from -10 (deep) to +10 (high).
MIN_PITCH, MAX_PITCH = -10, 10


def build_sapi_payload(text: str, pitch: int) -> str:
    """Wrap ``text`` in SAPI pitch markup, escaping it so punctuation is safe.

    SAPI parses XML in whatever it is told to speak, so any ``&`` or ``<`` in
    BMO's lines has to be escaped or the utterance is silently mangled.
    Returns the text unchanged when no pitch shift is wanted.
    """
    if not pitch:
        return text
    pitch = max(MIN_PITCH, min(MAX_PITCH, int(pitch)))
    return f'<pitch absmiddle="{pitch}">{escape(text)}</pitch>'


def list_voices() -> list[tuple[str, str]]:
    """Return [(name, id)] for every voice installed on this machine."""
    import pyttsx3

    engine = pyttsx3.init()
    try:
        return [(v.name, v.id) for v in engine.getProperty("voices")]
    finally:
        del engine
        _evict_cached_engine()


class Pyttsx3Backend:
    """Speaks via pyttsx3, building a fresh engine for every utterance.

    Creating an engine costs roughly 0.3s. That is a fair price for speech that
    actually comes out, and it happens on the worker thread, not the UI thread.
    """

    name = "pyttsx3"

    def __init__(
        self,
        rate: int = config.SPEECH_RATE,
        volume: float | None = config.SPEECH_VOLUME,
        voice: str | None = config.SPEECH_VOICE,
        pitch: int = config.SPEECH_PITCH,
    ) -> None:
        self.rate = rate
        self.volume = volume
        self.voice = voice
        self.pitch = pitch
        # Resolved once, then reused; looking it up costs an enumeration.
        self._voice_id: str | None = None
        self._voice_checked = False

    def say(self, text: str) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        try:
            voice_id = self._resolve_voice(engine)
            if voice_id:
                # Must be set before rate: pyttsx3 recalculates the rate
                # scaling from whichever voice is active.
                engine.setProperty("voice", voice_id)
            engine.setProperty("rate", self.rate)
            if self.volume is not None:
                engine.setProperty("volume", self.volume)
            engine.say(build_sapi_payload(text, self.pitch))
            engine.runAndWait()
        finally:
            # Stop first, in case runAndWait raised while audio was in flight.
            try:
                engine.stop()
            except Exception:
                log.debug("engine.stop() failed during cleanup", exc_info=True)
            del engine
            _evict_cached_engine()

    def _resolve_voice(self, engine) -> str | None:
        """Turn the configured voice name into a real voice id, once."""
        if self._voice_checked or not self.voice:
            return self._voice_id
        self._voice_checked = True

        voices = engine.getProperty("voices")
        self._voice_id = find_voice_id(voices, self.voice)
        if self._voice_id is None:
            log.warning(
                "voice %r not found, using the system default. Installed: %s",
                self.voice,
                ", ".join(v.name for v in voices),
            )
        else:
            log.info("using voice %r", self.voice)
        return self._voice_id


class EdgeTtsBackend:
    """Speaks with Microsoft's online neural voices via ``edge-tts``.

    Much closer to the cartoon BMO than the offline SAPI voices, because
    ``en-US-AnaNeural`` is an actual child voice rather than a pitched-up
    adult. The cost is a network round trip: this needs internet, and raises
    if it cannot reach the service, so :class:`FallbackBackend` can step in.

    Audio is synthesised to a temporary MP3 and played through pygame's mixer,
    which BMO already depends on.
    """

    name = "edge-tts"

    def __init__(
        self,
        voice: str = config.EDGE_VOICE,
        rate: str = config.EDGE_RATE,
        pitch: str = config.EDGE_PITCH,
        volume: str = config.EDGE_VOLUME,
        connect_timeout: int = config.EDGE_CONNECT_TIMEOUT,
        receive_timeout: int = config.EDGE_RECEIVE_TIMEOUT,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self.connect_timeout = connect_timeout
        self.receive_timeout = receive_timeout

    def say(self, text: str) -> None:
        path = self._synthesise(text)
        try:
            _play_audio_file(path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)

    def _synthesise(self, text: str) -> str:
        """Render ``text`` to a temporary MP3 and return its path."""
        import asyncio

        import edge_tts

        handle, path = tempfile.mkstemp(suffix=".mp3", prefix="bmo-speech-")
        os.close(handle)
        try:
            communicate = edge_tts.Communicate(
                text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch,
                volume=self.volume,
                connect_timeout=self.connect_timeout,
                receive_timeout=self.receive_timeout,
            )
            asyncio.run(communicate.save(path))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(path)
            raise

        if os.path.getsize(path) == 0:
            with contextlib.suppress(OSError):
                os.unlink(path)
            raise RuntimeError(f"edge-tts returned no audio for {text!r}")
        return path


def _play_audio_file(path: str) -> None:
    """Play an audio file and block until it finishes."""
    import pygame

    if not pygame.mixer.get_init():
        pygame.mixer.init()

    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
    try:
        while pygame.mixer.music.get_busy():
            time.sleep(0.02)
    finally:
        # Release the file handle so the temp file can be deleted on Windows.
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()


class FallbackBackend:
    """Uses ``primary``, and quietly falls back to ``fallback`` when it fails.

    This is what stops BMO going mute when the internet drops. After a
    failure the primary is rested for ``cooldown`` seconds rather than being
    disabled for the whole session, so a brief network blip recovers by itself.
    """

    def __init__(
        self,
        primary: SpeechBackend,
        fallback: SpeechBackend,
        cooldown: float = config.EDGE_RETRY_COOLDOWN,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.cooldown = cooldown
        self.fallback_count = 0
        self._resting_until = 0.0

    @property
    def name(self) -> str:
        if self._resting:
            return f"{self.fallback.name} (resting {self.primary.name})"
        return f"{self.primary.name} -> {self.fallback.name}"

    @property
    def _resting(self) -> bool:
        return time.monotonic() < self._resting_until

    def say(self, text: str) -> None:
        if not self._resting:
            try:
                self.primary.say(text)
                return
            except Exception as error:
                self.fallback_count += 1
                self._resting_until = time.monotonic() + self.cooldown
                log.warning(
                    "%s failed (%s), using %s for the next %.0fs",
                    self.primary.name,
                    error,
                    self.fallback.name,
                    self.cooldown,
                )
        self.fallback.say(text)


def make_backend(name: str = config.SPEECH_BACKEND) -> SpeechBackend:
    """Build the configured backend. See ``SPEECH_BACKEND`` in config.py."""
    if name == "pyttsx3":
        return Pyttsx3Backend()
    if name == "edge":
        return FallbackBackend(EdgeTtsBackend(), Pyttsx3Backend())
    raise ValueError(
        f"unknown SPEECH_BACKEND {name!r}; expected 'edge' or 'pyttsx3'"
    )


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
        self.backend: SpeechBackend = backend if backend is not None else make_backend()
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

    def shutdown(
        self,
        timeout: float = config.SPEECH_SHUTDOWN_TIMEOUT,
        *,
        drain: bool = False,
    ) -> bool:
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
