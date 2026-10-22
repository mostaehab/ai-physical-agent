"""Tests for mood state, blinking, drawing, and the window wrapper.

Pygame runs against SDL's dummy drivers here, so no window appears and no
audio device is touched.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before pygame initialises its backends.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

import main  # noqa: E402
from bmo import config  # noqa: E402
from bmo.display import (  # noqa: E402
    KEY_MOODS,
    Display,
    Face,
    draw_face,
    mood_for_key,
    update_blink,
)


class RecordingSpeech:
    """Stands in for SpeechEngine; records what BMO was asked to say."""

    def __init__(self) -> None:
        self.said: list[str] = []

    def speak(self, text: str) -> bool:
        self.said.append(text)
        return True


class MoodTests(unittest.TestCase):
    def test_set_mood_updates_mood_and_message(self) -> None:
        face = Face()
        returned = face.set_mood(config.HAPPY)

        self.assertEqual(face.mood, config.HAPPY)
        self.assertEqual(face.message, "Yay! Let's play!")
        self.assertEqual(returned, face.message)

    def test_every_configured_mood_can_be_set(self) -> None:
        for mood, line in config.MOOD_LINES.items():
            with self.subTest(mood=mood):
                face = Face()
                self.assertEqual(face.set_mood(mood), line)
                self.assertEqual(face.mood, mood)

    def test_unknown_mood_is_rejected(self) -> None:
        face = Face()
        with self.assertRaises(ValueError):
            face.set_mood("grumpy")
        self.assertEqual(face.mood, config.DEFAULT_MOOD)

    def test_eyes_closed_when_sleepy_or_blinking(self) -> None:
        self.assertTrue(Face(mood=config.SLEEPY).eyes_closed)
        self.assertTrue(Face(blinking=True).eyes_closed)
        self.assertFalse(Face().eyes_closed)


class MoodKeyTests(unittest.TestCase):
    """Key press must move the face *and* the voice, together."""

    def setUp(self) -> None:
        self.face = Face()
        self.speech = RecordingSpeech()

    def press(self, key: int) -> bool:
        return main.handle_key(self.face, key, self.speech)

    def test_h_makes_bmo_happy_and_say_the_happy_line(self) -> None:
        self.assertTrue(self.press(pygame.K_h))
        self.assertEqual(self.face.mood, config.HAPPY)
        self.assertEqual(self.speech.said, ["Yay! Let's play!"])

    def test_s_makes_bmo_sleepy_and_say_the_sleepy_line(self) -> None:
        self.assertTrue(self.press(pygame.K_s))
        self.assertEqual(self.face.mood, config.SLEEPY)
        self.assertEqual(self.speech.said, ["Zzz... I'm sleepy."])

    def test_n_returns_bmo_to_normal_and_say_the_greeting(self) -> None:
        self.press(pygame.K_h)
        self.assertTrue(self.press(pygame.K_n))
        self.assertEqual(self.face.mood, config.NORMAL)
        self.assertEqual(self.speech.said[-1], config.GREETING)

    def test_every_mood_key_changes_face_and_speaks_the_matching_line(self) -> None:
        for key, mood in sorted(KEY_MOODS.items()):
            with self.subTest(mood=mood):
                face = Face()
                speech = RecordingSpeech()
                self.assertTrue(main.handle_key(face, key, speech))
                self.assertEqual(face.mood, mood)
                self.assertEqual(face.message, config.MOOD_LINES[mood])
                self.assertEqual(speech.said, [config.MOOD_LINES[mood]])

    def test_unrelated_key_changes_nothing_and_says_nothing(self) -> None:
        self.assertFalse(self.press(pygame.K_q))
        self.assertEqual(self.face.mood, config.DEFAULT_MOOD)
        self.assertEqual(self.face.message, config.GREETING)
        self.assertEqual(self.speech.said, [])

    def test_pressing_the_same_key_twice_speaks_twice(self) -> None:
        self.press(pygame.K_h)
        self.press(pygame.K_h)
        self.assertEqual(self.speech.said, ["Yay! Let's play!"] * 2)

    def test_mood_for_key_returns_none_for_other_keys(self) -> None:
        self.assertIsNone(mood_for_key(pygame.K_q))
        self.assertEqual(mood_for_key(pygame.K_h), config.HAPPY)


class BlinkTests(unittest.TestCase):
    def test_blink_starts_after_the_interval(self) -> None:
        face = Face(last_blink=0.0)

        update_blink(face, now=1.0)
        self.assertFalse(face.blinking)

        update_blink(face, now=config.BLINK_INTERVAL + 0.01)
        self.assertTrue(face.blinking)

    def test_blink_ends_after_the_duration(self) -> None:
        face = Face(last_blink=0.0)
        start = config.BLINK_INTERVAL + 0.01

        update_blink(face, now=start)
        self.assertTrue(face.blinking)

        update_blink(face, now=start + config.BLINK_DURATION + 0.01)
        self.assertFalse(face.blinking)

    def test_sleepy_bmo_does_not_blink(self) -> None:
        face = Face(mood=config.SLEEPY, last_blink=0.0)
        update_blink(face, now=config.BLINK_INTERVAL + 10)
        self.assertFalse(face.blinking)


class DrawingTests(unittest.TestCase):
    """Catches crashes in the drawing code for every mood and blink state."""

    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        cls.screen = pygame.Surface((config.WIDTH, config.HEIGHT))
        cls.font = pygame.font.SysFont(config.FONT_NAME, config.MESSAGE_FONT_SIZE, bold=True)
        cls.hint_font = pygame.font.SysFont(config.FONT_NAME, config.HINT_FONT_SIZE)

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_draws_every_mood_in_both_blink_states(self) -> None:
        for mood in config.MOOD_LINES:
            for blinking in (False, True):
                with self.subTest(mood=mood, blinking=blinking):
                    face = Face(blinking=blinking)
                    face.set_mood(mood)
                    draw_face(self.screen, face, self.font, self.hint_font)

    def test_background_is_teal(self) -> None:
        draw_face(self.screen, Face(), self.font, self.hint_font)
        self.assertEqual(self.screen.get_at((5, 5))[:3], config.TEAL)

    def test_face_panel_is_dark(self) -> None:
        draw_face(self.screen, Face(), self.font, self.hint_font)
        self.assertEqual(self.screen.get_at((300, 150))[:3], config.DARK)


class DisplayWindowTests(unittest.TestCase):
    def test_open_render_close(self) -> None:
        display = Display()
        display.open()
        try:
            self.assertIsNotNone(display.screen)
            self.assertEqual(display.screen.get_size(), (config.WIDTH, config.HEIGHT))
            display.render(Face())
        finally:
            display.close()
        self.assertIsNone(display.screen)

    def test_render_before_open_is_a_clear_error(self) -> None:
        with self.assertRaises(RuntimeError):
            Display().render(Face())


if __name__ == "__main__":
    unittest.main()
