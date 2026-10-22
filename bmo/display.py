"""BMO's face: what mood it is in, and how that gets drawn.

Two layers live here on purpose:

* :class:`Face` and the free functions are pure state and pure drawing. They
  need no window, so they are easy to test.
* :class:`Display` owns the Pygame window, fonts and frame clock, so ``main.py``
  does not have to.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pygame

from bmo import config

log = logging.getLogger(__name__)

#: Keyboard key -> mood name. One place to add a new mood key.
KEY_MOODS: dict[int, str] = {
    pygame.K_h: config.HAPPY,
    pygame.K_s: config.SLEEPY,
    pygame.K_n: config.NORMAL,
}


def mood_for_key(key: int) -> str | None:
    """Return the mood a key selects, or None if it is not a mood key."""
    return KEY_MOODS.get(key)


# ---------------------------------------------------------------------- state


@dataclass
class Face:
    """Everything the drawing code needs to know about BMO right now."""

    mood: str = config.DEFAULT_MOOD
    message: str = config.GREETING
    blinking: bool = False
    last_blink: float = field(default_factory=time.time)

    def set_mood(self, mood: str) -> str:
        """Switch mood and adopt that mood's line. Returns the new line."""
        if mood not in config.MOOD_LINES:
            raise ValueError(f"unknown mood {mood!r}")
        self.mood = mood
        self.message = config.MOOD_LINES[mood]
        return self.message

    @property
    def eyes_closed(self) -> bool:
        """True when the eyes should be drawn shut."""
        return self.mood in config.EYES_CLOSED_MOODS or self.blinking


def update_blink(face: Face, now: float) -> None:
    """Start a blink every BLINK_INTERVAL, end it after BLINK_DURATION.

    BMO does not blink in moods where the eyes are already closed.
    """
    if (
        face.mood not in config.EYES_CLOSED_MOODS
        and now - face.last_blink > config.BLINK_INTERVAL
    ):
        face.blinking = True
        face.last_blink = now

    if face.blinking and now - face.last_blink > config.BLINK_DURATION:
        face.blinking = False


# -------------------------------------------------------------------- drawing


def draw_face(
    screen: pygame.Surface,
    face: Face,
    font: pygame.font.Font,
    hint_font: pygame.font.Font,
) -> None:
    """Draw one complete BMO frame onto ``screen``."""
    screen.fill(config.TEAL)
    pygame.draw.rect(screen, config.DARK, (100, 80, 400, 330), border_radius=35)

    # Eyes
    if face.eyes_closed:
        pygame.draw.line(screen, config.CYAN, (180, 230), (250, 230), 6)
        pygame.draw.line(screen, config.CYAN, (350, 230), (420, 230), 6)
    elif face.mood == config.HAPPY:
        pygame.draw.arc(screen, config.CYAN, (165, 190, 100, 90), 0, 3.14, 6)
        pygame.draw.arc(screen, config.CYAN, (335, 190, 100, 90), 0, 3.14, 6)
    else:
        pygame.draw.circle(screen, config.CYAN, (215, 225), 25)
        pygame.draw.circle(screen, config.CYAN, (385, 225), 25)

    # Mouth
    if face.mood == config.HAPPY:
        pygame.draw.arc(screen, config.WHITE, (230, 260, 140, 90), 3.14, 6.28, 5)
    elif face.mood == config.SLEEPY:
        pygame.draw.line(screen, config.WHITE, (250, 300), (350, 300), 5)
    else:
        pygame.draw.arc(screen, config.WHITE, (250, 260, 100, 70), 3.14, 6.28, 5)

    text_surface = font.render(face.message, True, config.WHITE)
    screen.blit(text_surface, text_surface.get_rect(center=(300, 470)))

    hint = hint_font.render(config.HINT_TEXT, True, config.DARK)
    screen.blit(hint, hint.get_rect(center=(300, 550)))


# -------------------------------------------------------------------- window


class Display:
    """Owns the Pygame window, its fonts and the frame clock."""

    def __init__(self) -> None:
        self.screen: pygame.Surface | None = None
        self.font: pygame.font.Font | None = None
        self.hint_font: pygame.font.Font | None = None
        self.clock: pygame.time.Clock | None = None

    def open(self) -> None:
        """Create the window. Safe to call once per run."""
        pygame.init()
        self.screen = pygame.display.set_mode((config.WIDTH, config.HEIGHT))
        pygame.display.set_caption(config.WINDOW_CAPTION)
        # Fonts are built once here, not rebuilt every frame.
        self.font = pygame.font.SysFont(
            config.FONT_NAME, config.MESSAGE_FONT_SIZE, bold=True
        )
        self.hint_font = pygame.font.SysFont(config.FONT_NAME, config.HINT_FONT_SIZE)
        self.clock = pygame.time.Clock()
        log.info("display opened (%dx%d)", config.WIDTH, config.HEIGHT)

    def render(self, face: Face) -> None:
        """Draw one frame and wait out the rest of its time slice."""
        if self.screen is None:
            raise RuntimeError("Display.open() must be called before render()")
        draw_face(self.screen, face, self.font, self.hint_font)
        pygame.display.flip()
        self.clock.tick(config.FPS)

    def close(self) -> None:
        """Shut the window down. Safe to call even if open() failed."""
        pygame.quit()
        self.screen = None
        log.info("display closed")
