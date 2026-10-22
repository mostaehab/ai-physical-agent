"""Tests for the speech queue and worker thread.

These use a fake backend, so they are fast and silent. The real pyttsx3
regression test lives in ``test_audio_pyttsx3.py``.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bmo import config  # noqa: E402
from bmo.audio import (  # noqa: E402
    MAX_PITCH,
    MIN_PITCH,
    Pyttsx3Backend,
    SpeechEngine,
    EdgeTtsBackend,
    FallbackBackend,
    build_sapi_payload,
    find_voice_id,
    make_backend,
)


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


class FakeVoice:
    def __init__(self, name: str, id: str) -> None:
        self.name = name
        self.id = id


VOICES = [
    FakeVoice("Microsoft David Desktop - English (United States)", r"HKEY\...\DAVID_11.0"),
    FakeVoice("Microsoft Zira Desktop - English (United States)", r"HKEY\...\ZIRA_11.0"),
]


class VoiceMatchingTests(unittest.TestCase):
    def test_matches_on_a_name_substring(self) -> None:
        self.assertEqual(find_voice_id(VOICES, "Zira"), VOICES[1].id)
        self.assertEqual(find_voice_id(VOICES, "David"), VOICES[0].id)

    def test_matching_ignores_case_and_padding(self) -> None:
        self.assertEqual(find_voice_id(VOICES, "  zIrA "), VOICES[1].id)

    def test_matches_on_an_exact_id(self) -> None:
        self.assertEqual(find_voice_id(VOICES, VOICES[0].id), VOICES[0].id)

    def test_an_exact_id_wins_over_a_name_substring(self) -> None:
        voices = [FakeVoice("contains zira in the name", "zira"), VOICES[1]]
        self.assertEqual(find_voice_id(voices, "zira"), "zira")

    def test_unknown_voice_returns_none_rather_than_raising(self) -> None:
        self.assertIsNone(find_voice_id(VOICES, "Glados"))

    def test_empty_request_returns_none(self) -> None:
        self.assertIsNone(find_voice_id(VOICES, ""))
        self.assertIsNone(find_voice_id(VOICES, "   "))

    def test_backend_defaults_to_the_configured_voice(self) -> None:
        self.assertEqual(Pyttsx3Backend().voice, config.SPEECH_VOICE)
        self.assertEqual(Pyttsx3Backend(voice="Zira").voice, "Zira")


class PitchMarkupTests(unittest.TestCase):
    def test_zero_pitch_leaves_the_text_untouched(self) -> None:
        self.assertEqual(build_sapi_payload("Hello! I'm BMO.", 0), "Hello! I'm BMO.")

    def test_pitch_wraps_the_text_in_sapi_markup(self) -> None:
        self.assertEqual(
            build_sapi_payload("Hi", 8), '<pitch absmiddle="8">Hi</pitch>'
        )

    def test_negative_pitch_is_allowed(self) -> None:
        self.assertEqual(
            build_sapi_payload("Hi", -6), '<pitch absmiddle="-6">Hi</pitch>'
        )

    def test_pitch_is_clamped_to_the_sapi_range(self) -> None:
        self.assertIn(f'absmiddle="{MAX_PITCH}"', build_sapi_payload("Hi", 99))
        self.assertIn(f'absmiddle="{MIN_PITCH}"', build_sapi_payload("Hi", -99))

    def test_xml_characters_are_escaped(self) -> None:
        """Unescaped & or < would silently mangle the utterance."""
        payload = build_sapi_payload("Tom & Jerry <3", 8)
        self.assertIn("Tom &amp; Jerry &lt;3", payload)
        self.assertNotIn("Jerry <3", payload)

    def test_apostrophes_and_quotes_survive(self) -> None:
        payload = build_sapi_payload("Zzz... I'm sleepy.", 8)
        self.assertIn("I'm sleepy.", payload)

    def test_backend_defaults_to_the_configured_pitch(self) -> None:
        self.assertEqual(Pyttsx3Backend().pitch, config.SPEECH_PITCH)
        self.assertEqual(Pyttsx3Backend(pitch=0).pitch, 0)


class BrokenBackend:
    """Always fails, like edge-tts with no internet."""

    name = "broken"

    def __init__(self) -> None:
        self.calls = 0

    def say(self, text: str) -> None:
        self.calls += 1
        raise OSError("simulated: no internet")


class FallbackBackendTests(unittest.TestCase):
    """BMO must never go mute just because the network dropped."""

    def test_healthy_primary_is_used_and_fallback_is_untouched(self) -> None:
        primary, spare = FakeBackend(), FakeBackend()
        fb = FallbackBackend(primary, spare)

        fb.say("hello")

        self.assertEqual(primary.said, ["hello"])
        self.assertEqual(spare.said, [])
        self.assertEqual(fb.fallback_count, 0)

    def test_failing_primary_falls_back_without_losing_the_line(self) -> None:
        primary, spare = BrokenBackend(), FakeBackend()
        fb = FallbackBackend(primary, spare)

        fb.say("hello")

        self.assertEqual(spare.said, ["hello"])
        self.assertEqual(fb.fallback_count, 1)

    def test_primary_is_rested_so_every_line_does_not_retry_the_network(self) -> None:
        primary, spare = BrokenBackend(), FakeBackend()
        fb = FallbackBackend(primary, spare, cooldown=30.0)

        for i in range(5):
            fb.say(f"line {i}")

        self.assertEqual(primary.calls, 1, "retried a known-dead network")
        self.assertEqual(spare.said, [f"line {i}" for i in range(5)])
        self.assertEqual(fb.fallback_count, 1)

    def test_primary_is_retried_once_the_cooldown_expires(self) -> None:
        primary, spare = BrokenBackend(), FakeBackend()
        fb = FallbackBackend(primary, spare, cooldown=30.0)

        fb.say("first")
        fb._resting_until = time.monotonic() - 0.01  # pretend the wait elapsed
        fb.say("second")

        self.assertEqual(primary.calls, 2)
        self.assertEqual(fb.fallback_count, 2)

    def test_a_failure_is_logged_rather_than_hidden(self) -> None:
        fb = FallbackBackend(BrokenBackend(), FakeBackend())
        with self.assertLogs("bmo.audio", level="WARNING") as captured:
            fb.say("hello")
        self.assertIn("no internet", captured.output[0])

    def test_name_shows_which_backend_is_in_charge(self) -> None:
        fb = FallbackBackend(BrokenBackend(), FakeBackend())
        self.assertIn("broken", fb.name)
        fb.say("hello")
        self.assertIn("resting", fb.name)


class BackendFactoryTests(unittest.TestCase):
    def test_pyttsx3_gives_the_offline_backend_alone(self) -> None:
        self.assertIsInstance(make_backend("pyttsx3"), Pyttsx3Backend)

    def test_edge_gives_a_neural_backend_with_an_offline_safety_net(self) -> None:
        backend = make_backend("edge")
        self.assertIsInstance(backend, FallbackBackend)
        self.assertIsInstance(backend.primary, EdgeTtsBackend)
        self.assertIsInstance(backend.fallback, Pyttsx3Backend)

    def test_unknown_backend_name_fails_clearly(self) -> None:
        with self.assertRaises(ValueError) as caught:
            make_backend("espeak")
        self.assertIn("espeak", str(caught.exception))

    def test_edge_backend_defaults_come_from_config(self) -> None:
        backend = EdgeTtsBackend()
        self.assertEqual(backend.voice, config.EDGE_VOICE)
        self.assertEqual(backend.rate, config.EDGE_RATE)
        self.assertEqual(backend.pitch, config.EDGE_PITCH)


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

        with self.assertLogs("bmo.audio", level="WARNING") as captured:
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
