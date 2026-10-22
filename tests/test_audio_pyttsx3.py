"""Live regression test for the real pyttsx3 backend.

This is the test that actually catches the original bug, because the fault was
inside pyttsx3's engine reuse rather than in our queue. It is skipped unless
you opt in, since it drives the real speech engine and takes a few seconds:

    set BMO_AUDIO_TESTS=1
    py -3.12 -m unittest discover -s tests -t .

Volume is forced to 0 so nothing is audible. Synthesis still runs through the
whole SAPI pipeline, so the timing signal below is still meaningful: a real
utterance takes over a second, while the bug made every utterance after the
first return in about 0.25s having said nothing.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bmo.audio import Pyttsx3Backend, SpeechEngine  # noqa: E402

#: A purged (silent) utterance returns in ~0.25s; a real one takes 1s or more.
MIN_SPOKEN_SECONDS = 0.6

PHRASES = [
    "Hello! I'm BMO.",
    "Yay! Let's play!",
    "Zzz... I'm sleepy.",
    "Hello! I'm BMO.",
    "Yay! Let's play!",
]


class TimingBackend:
    """Wraps the real backend and records how long each utterance took."""

    name = "pyttsx3-timed"

    def __init__(self) -> None:
        self.inner = Pyttsx3Backend(volume=0.0)
        self.timings: list[tuple[str, float]] = []

    def say(self, text: str) -> None:
        start = time.monotonic()
        try:
            self.inner.say(text)
        finally:
            self.timings.append((text, time.monotonic() - start))


@unittest.skipUnless(
    os.environ.get("BMO_AUDIO_TESTS") == "1",
    "set BMO_AUDIO_TESTS=1 to run the live speech tests",
)
class Pyttsx3BackendTests(unittest.TestCase):
    def test_every_consecutive_utterance_actually_speaks(self) -> None:
        backend = TimingBackend()
        engine = SpeechEngine(backend)
        try:
            for phrase in PHRASES:
                self.assertTrue(engine.speak(phrase))
            self.assertTrue(
                engine.wait_until_idle(timeout=90), "live speech timed out"
            )
        finally:
            engine.shutdown(timeout=30)

        self.assertEqual(len(backend.timings), len(PHRASES))
        self.assertEqual(engine.error_count, 0)

        silent = [
            (text, round(seconds, 3))
            for text, seconds in backend.timings
            if seconds < MIN_SPOKEN_SECONDS
        ]
        self.assertEqual(
            silent,
            [],
            "these utterances returned too fast to have produced audio, which "
            "is the signature of the pyttsx3 engine-reuse bug",
        )

    def test_backend_leaves_no_cached_engine_behind(self) -> None:
        """A stale cached engine is the root cause, so assert it is gone."""
        import pyttsx3

        Pyttsx3Backend(volume=0.0).say("Checking the cache.")

        self.assertEqual(
            dict(pyttsx3._activeEngines),
            {},
            "pyttsx3 still has a cached engine; the next utterance would reuse "
            "it and be silent",
        )


if __name__ == "__main__":
    unittest.main()
