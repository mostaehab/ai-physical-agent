"""BMO - a small physical AI companion. Desktop prototype.

Run with:  py -3.12 main.py

Keys:  H = happy   S = sleepy   N = normal   ESC = quit

The face is drawn with Pygame on the main thread. Speech happens on a worker
thread owned by :class:`speech.SpeechEngine`, so talking never freezes the
animation. See ``speech.py`` for why speech is built the way it is.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pygame

from speech import SpeechEngine

log = logging.getLogger("bmo")

# ----------------------------------------------------------------- appearance

WIDTH, HEIGHT = 600, 600

TEAL = (90, 200, 190)
DARK = (25, 40, 45)
CYAN = (80, 240, 255)
WHITE = (255, 255, 255)

GREETING = "Hello! I'm BMO."

#: How often BMO blinks, and how long a blink lasts, in seconds.
BLINK_INTERVAL = 3.0
BLINK_DURATION = 0.15

#: Key -> (mood, what BMO says). One place to add new moods.
KEY_MOODS: dict[int, tuple[str, str]] = {
    pygame.K_h: ("happy", "Yay! Let's play!"),
    pygame.K_s: ("sleepy", "Zzz... I'm sleepy."),
    pygame.K_n: ("normal", GREETING),
}

HINT_TEXT = "H = Happy   S = Sleepy   N = Normal   ESC = Quit"


# ---------------------------------------------------------------------- state


@dataclass
class Face:
    """Everything the drawing code needs to know about BMO right now."""

    mood: str = "normal"
    message: str = GREETING
    blinking: bool = False
    last_blink: float = field(default_factory=time.time)


def handle_key(face: Face, key: int, speech: SpeechEngine) -> bool:
    """Apply a mood key press: change the face *and* say the matching line.

    Returns True if the key was one of BMO's mood keys.
    """
    entry = KEY_MOODS.get(key)
    if entry is None:
        return False
    face.mood, face.message = entry
    speech.speak(face.message)
    return True


def update_blink(face: Face, now: float) -> None:
    """Start a blink every BLINK_INTERVAL seconds, end it after BLINK_DURATION.

    BMO does not blink while sleepy, because the eyes are already closed.
    """
    if face.mood != "sleepy" and now - face.last_blink > BLINK_INTERVAL:
        face.blinking = True
        face.last_blink = now

    if face.blinking and now - face.last_blink > BLINK_DURATION:
        face.blinking = False


# -------------------------------------------------------------------- drawing


def draw_face(
    screen: pygame.Surface,
    face: Face,
    font: pygame.font.Font,
    hint_font: pygame.font.Font,
) -> None:
    """Draw the whole BMO frame onto ``screen``."""
    screen.fill(TEAL)
    pygame.draw.rect(screen, DARK, (100, 80, 400, 330), border_radius=35)

    # Eyes
    if face.mood == "sleepy" or face.blinking:
        pygame.draw.line(screen, CYAN, (180, 230), (250, 230), 6)
        pygame.draw.line(screen, CYAN, (350, 230), (420, 230), 6)
    elif face.mood == "happy":
        pygame.draw.arc(screen, CYAN, (165, 190, 100, 90), 0, 3.14, 6)
        pygame.draw.arc(screen, CYAN, (335, 190, 100, 90), 0, 3.14, 6)
    else:
        pygame.draw.circle(screen, CYAN, (215, 225), 25)
        pygame.draw.circle(screen, CYAN, (385, 225), 25)

    # Mouth
    if face.mood == "happy":
        pygame.draw.arc(screen, WHITE, (230, 260, 140, 90), 3.14, 6.28, 5)
    elif face.mood == "sleepy":
        pygame.draw.line(screen, WHITE, (250, 300), (350, 300), 5)
    else:
        pygame.draw.arc(screen, WHITE, (250, 260, 100, 70), 3.14, 6.28, 5)

    text_surface = font.render(face.message, True, WHITE)
    screen.blit(text_surface, text_surface.get_rect(center=(300, 470)))

    hint = hint_font.render(HINT_TEXT, True, DARK)
    screen.blit(hint, hint.get_rect(center=(300, 550)))


# ----------------------------------------------------------------- entry point


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("BMO")

    # Built once, not every frame.
    font = pygame.font.SysFont("Arial", 28, bold=True)
    hint_font = pygame.font.SysFont("Arial", 18)
    clock = pygame.time.Clock()

    speech = SpeechEngine()
    face = Face()
    speech.speak(face.message)

    try:
        running = True
        while running:
            now = time.time()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        handle_key(face, event.key, speech)

            update_blink(face, now)
            draw_face(screen, face, font, hint_font)
            pygame.display.flip()
            clock.tick(60)
    finally:
        # Always run, even if the loop raised, so we never leave a live
        # worker thread or an open audio device behind.
        log.info("shutting down")
        speech.shutdown()
        pygame.quit()


if __name__ == "__main__":
    main()
