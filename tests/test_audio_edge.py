"""Live test for the edge-tts neural backend.

Skipped unless you opt in, because it needs an internet connection and takes
a few seconds:

    set BMO_AUDIO_TESTS=1
    py -3.12 -m unittest discover -s tests -t .

Playback goes through pygame's mixer with the dummy audio driver, so nothing
is audible and no real sound card is needed.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from bmo import config  # noqa: E402
from bmo.audio import EdgeTtsBackend, SpeechEngine  # noqa: E402

#: Roughly how many bytes of MP3 a short sentence should produce. Anything
#: near zero means the service answered but gave us nothing usable.
MIN_MP3_BYTES = 2000


@unittest.skipUnless(
    os.environ.get("BMO_AUDIO_TESTS") == "1",
    "set BMO_AUDIO_TESTS=1 to run the live speech tests",
)
class EdgeTtsBackendTests(unittest.TestCase):
    def test_synthesises_real_mp3_audio(self) -> None:
        backend = EdgeTtsBackend()
        path = backend._synthesise("Hello! I'm BMO.")
        try:
            size = os.path.getsize(path)
            self.assertGreater(size, MIN_MP3_BYTES, "edge-tts returned near-empty audio")
            with open(path, "rb") as handle:
                header = handle.read(3)
            self.assertTrue(
                header[:2] in (b"\xff\xfb", b"\xff\xf3") or header == b"ID3",
                f"not an MP3 stream, header was {header!r}",
            )
        finally:
            os.unlink(path)

    def test_the_configured_voice_is_a_real_voice(self) -> None:
        import asyncio

        import edge_tts

        names = {v["ShortName"] for v in asyncio.run(edge_tts.list_voices())}
        self.assertIn(config.EDGE_VOICE, names)

    def test_temp_files_are_cleaned_up_after_speaking(self) -> None:
        import glob
        import tempfile

        pattern = os.path.join(tempfile.gettempdir(), "bmo-speech-*")
        before = set(glob.glob(pattern))

        EdgeTtsBackend().say("Cleaning up after myself.")

        self.assertEqual(set(glob.glob(pattern)) - before, set())

    def test_several_consecutive_lines_all_speak(self) -> None:
        spoken: list[str] = []

        class Recording:
            name = "recording-edge"

            def __init__(self) -> None:
                self.inner = EdgeTtsBackend()

            def say(self, text: str) -> None:
                self.inner.say(text)
                spoken.append(text)

        engine = SpeechEngine(Recording())
        lines = list(config.MOOD_LINES.values())
        try:
            for line in lines:
                engine.speak(line)
            self.assertTrue(engine.wait_until_idle(timeout=120), "edge-tts timed out")
        finally:
            engine.shutdown(timeout=30)

        self.assertEqual(spoken, lines)
        self.assertEqual(engine.error_count, 0)

    def test_a_bad_voice_name_raises_so_the_fallback_can_take_over(self) -> None:
        backend = EdgeTtsBackend(voice="xx-XX-NotARealVoice")
        with self.assertRaises(Exception):
            backend._synthesise("This should not work.")


if __name__ == "__main__":
    unittest.main()
