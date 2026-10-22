"""Tests for the speech queue and worker thread.

These use a fake backend, so they are fast and silent. The real pyttsx3
regression test lives in ``test_speech_pyttsx3.py``.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from speech import SpeechEngine  # noqa: E402


class FakeBackend:
    """Records what it was asked to say, without touching any audio device."""

    name = "fake"

    def __init__(self, delay: float = 0.0, fail_on: set[str] | None = None) -> None:
        self.delay = delay
        self.fail_on = fail_on or set()
        self.said: list[str] = []
        self._lock = threading.Lock()

    def say(self, text: str) -> None:
        if self.delay:
            time.sleep(self.delay)
        if text in self.fail_on:
            raise RuntimeError(f"backend blew up on {text!r}")
        with self._lock:
            self.said.append(text)


class SpeechEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engines: list[SpeechEngine] = []

    def tearDown(self) -> None:
        for engine in self.engines:
            engine.shutdown(timeout=5)

    def make(self, backend: FakeBackend) -> SpeechEngine:
        engine = SpeechEngine(backend)
        self.engines.append(engine)
        return engine

    # -------------------------------------------------- the core regression

    def test_speaks_a_single_phrase(self) -> None:
        backend = FakeBackend()
        engine = self.make(backend)

        self.assertTrue(engine.speak("Hello! I'm BMO."))
        self.assertTrue(engine.wait_until_idle(timeout=5))

        self.assertEqual(backend.said, ["Hello! I'm BMO."])
        self.assertEqual(engine.spoken_count, 1)

    def test_many_consecutive_requests_all_spoken_in_order(self) -> None:
        """The bug was: only the first utterance ever came out."""
        backend = FakeBackend()
        engine = self.make(backend)

        phrases = [f"phrase {i}" for i in range(10)]
        for phrase in phrases:
            self.assertTrue(engine.speak(phrase))

        self.assertTrue(engine.wait_until_idle(timeout=10))
        self.assertEqual(backend.said, phrases)
        self.assertEqual(engine.spoken_count, 10)
        self.assertEqual(engine.error_count, 0)

    def test_repeating_the_same_phrase_works_every_time(self) -> None:
        backend = FakeBackend()
        engine = self.make(backend)

        for _ in range(5):
            engine.speak("Yay! Let's play!")

        self.assertTrue(engine.wait_until_idle(timeout=10))
        self.assertEqual(backend.said, ["Yay! Let's play!"] * 5)

    # --------------------------------------------------------- the UI thread

    def test_speak_returns_immediately_while_audio_is_playing(self) -> None:
        """speak() must never block the Pygame loop."""
        backend = FakeBackend(delay=0.3)
        engine = self.make(backend)

        start = time.monotonic()
        for i in range(5):
            engine.speak(f"slow {i}")
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 0.1, "speak() blocked the caller")
        self.assertTrue(engine.wait_until_idle(timeout=10))
        self.assertEqual(len(backend.said), 5)

    # ------------------------------------------------------------- failures

    def test_backend_failure_is_counted_and_worker_survives(self) -> None:
        backend = FakeBackend(fail_on={"bad"})
        engine = self.make(backend)

        engine.speak("good one")
        engine.speak("bad")
        engine.speak("good two")

        self.assertTrue(engine.wait_until_idle(timeout=5))
        self.assertEqual(backend.said, ["good one", "good two"])
        self.assertEqual(engine.error_count, 1)
        self.assertEqual(engine.spoken_count, 2)
        self.assertTrue(engine.is_alive(), "worker died on a backend error")

    def test_empty_text_is_rejected_not_silently_queued(self) -> None:
        backend = FakeBackend()
        engine = self.make(backend)

        self.assertFalse(engine.speak(""))
        self.assertFalse(engine.speak("   "))

        self.assertTrue(engine.wait_until_idle(timeout=5))
        self.assertEqual(backend.said, [])
        self.assertEqual(engine.dropped_count, 2)

    # ------------------------------------------------------------- shutdown

    def test_shutdown_stops_the_worker_thread(self) -> None:
        backend = FakeBackend()
        engine = SpeechEngine(backend)

        engine.speak("bye")
        self.assertTrue(engine.wait_until_idle(timeout=5))

        self.assertTrue(engine.shutdown(timeout=5))
        self.assertFalse(engine.is_alive())

    def test_shutdown_is_idempotent(self) -> None:
        engine = SpeechEngine(FakeBackend())
        self.assertTrue(engine.shutdown(timeout=5))
        self.assertTrue(engine.shutdown(timeout=5))

    def test_speak_after_shutdown_is_refused_loudly(self) -> None:
        backend = FakeBackend()
        engine = SpeechEngine(backend)
        engine.shutdown(timeout=5)

        with self.assertLogs("speech", level="WARNING") as captured:
            self.assertFalse(engine.speak("too late"))

        self.assertIn("shutting down", captured.output[0])
        self.assertEqual(backend.said, [])

    def test_shutdown_discards_queued_speech_by_default(self) -> None:
        backend = FakeBackend(delay=0.2)
        engine = SpeechEngine(backend)

        for i in range(8):
            engine.speak(f"queued {i}")
        engine.shutdown(timeout=5)

        self.assertFalse(engine.is_alive())
        self.assertLess(len(backend.said), 8, "shutdown waited for the whole queue")

    def test_shutdown_with_drain_speaks_everything_first(self) -> None:
        backend = FakeBackend()
        engine = SpeechEngine(backend)

        for i in range(4):
            engine.speak(f"drain {i}")

        self.assertTrue(engine.shutdown(timeout=10, drain=True))
        self.assertEqual(len(backend.said), 4)


if __name__ == "__main__":
    unittest.main()
