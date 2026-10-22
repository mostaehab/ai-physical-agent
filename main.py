"""BMO - a small physical AI companion. Desktop prototype.

Run with:  py -3.12 main.py

Keys:  H = happy   S = sleepy   N = normal   ESC = quit

This file does three things and nothing else: start up, run the event loop,
and wire the components together. The face lives in ``bmo/display.py``, the
voice in ``bmo/audio.py``, and every tunable setting in ``bmo/config.py``.
"""

from __future__ import annotations

import logging
import time

import pygame

from bmo import config
from bmo.audio import SpeechEngine
from bmo.display import Display, Face, mood_for_key, update_blink

log = logging.getLogger("bmo.main")


def setup_logging(level: int = logging.INFO) -> None:
    """Send readable logs to the console so failures are never silent."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # comtypes (pulled in by pyttsx3 on Windows) chatters at INFO on startup.
    logging.getLogger("comtypes").setLevel(logging.WARNING)


def handle_key(face: Face, key: int, speech: SpeechEngine) -> bool:
    """Apply a mood key press: change the face *and* say the matching line.

    Returns True if the key was one of BMO's mood keys.
    """
    mood = mood_for_key(key)
    if mood is None:
        return False
    message = face.set_mood(mood)
    speech.speak(message)
    return True


def run(display: Display, speech: SpeechEngine, face: Face) -> None:
    """The main loop. Returns when BMO is asked to quit."""
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                else:
                    handle_key(face, event.key, speech)

        update_blink(face, time.time())
        display.render(face)


def main() -> None:
    setup_logging()

    display = Display()
    speech = SpeechEngine()
    face = Face()

    try:
        display.open()
        speech.speak(face.message)
        run(display, speech, face)
    finally:
        # Always runs, even if the loop raised, so we never leave a live
        # worker thread or an open audio device behind.
        log.info("shutting down")
        speech.shutdown()
        display.close()


if __name__ == "__main__":
    main()
