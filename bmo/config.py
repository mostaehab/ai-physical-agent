"""Every tunable setting for BMO, in one place.

Keep values here rather than scattered through the code, so there is a single
obvious file to open when you want to change how BMO looks, sounds or behaves.
"""

from __future__ import annotations

# ------------------------------------------------------------------- window

WIDTH = 600
HEIGHT = 600
WINDOW_CAPTION = "BMO"
FPS = 60

# -------------------------------------------------------------------- colour

TEAL = (90, 200, 190)
DARK = (25, 40, 45)
CYAN = (80, 240, 255)
WHITE = (255, 255, 255)

# --------------------------------------------------------------------- moods

NORMAL = "normal"
HAPPY = "happy"
SLEEPY = "sleepy"

#: Mood -> the line BMO says when it switches to that mood.
#: Later phases will add curious, listening, thinking and error here.
MOOD_LINES: dict[str, str] = {
    NORMAL: "Hello! I'm BMO.",
    HAPPY: "Yay! Let's play!",
    SLEEPY: "Zzz... I'm sleepy.",
}

DEFAULT_MOOD = NORMAL
GREETING = MOOD_LINES[NORMAL]

# ------------------------------------------------------------------ blinking

#: Seconds between blinks, and how long one blink lasts.
BLINK_INTERVAL = 3.0
BLINK_DURATION = 0.15

#: BMO keeps its eyes shut in these moods, so it does not blink in them.
EYES_CLOSED_MOODS = frozenset({SLEEPY})

# -------------------------------------------------------------------- speech

#: Words per minute. BMO talks a little quicker than a narrator.
SPEECH_RATE = 175

#: None means "leave the system volume alone". Tests set this to 0.0.
SPEECH_VOLUME: float | None = None

#: Which installed voice to use. A substring of the name is enough, e.g.
#: "Zira" or "David" on Windows. None means the system default voice.
#: Run `py -3.12 voice_demo.py` to hear what is installed.
SPEECH_VOICE: str | None = "Zira"

#: Pitch, -10 (deep) to +10 (high). 0 is the voice's natural pitch.
#: Windows only: this is applied with SAPI's <pitch> markup.
#: +8 with Zira gives BMO a small, chirpy, childlike sound. See the
#: "Making BMO sound like BMO" section of the README for the limits.
#: Run `py -3.12 voice_demo.py --pitch` to hear the range.
SPEECH_PITCH = 8

#: How long to wait for the current utterance to finish when closing BMO.
SPEECH_SHUTDOWN_TIMEOUT = 5.0

# ----------------------------------------------------- which voice engine

#: "edge"    Microsoft neural voices. Much closer to the cartoon BMO, but
#:           needs an internet connection. Falls back to pyttsx3 automatically
#:           when offline, so BMO never goes mute.
#: "pyttsx3" The offline Windows SAPI voice only. Works with no network and is
#:           what a Raspberry Pi build would start from.
SPEECH_BACKEND = "edge"

# ------------------------------------------------- edge-tts (neural voice)

#: en-US-AnaNeural is Microsoft's child voice, tagged "Cute". It is the
#: closest thing to BMO in the catalogue. Run `py -3.12 voice_demo.py --edge`
#: to hear the alternatives.
EDGE_VOICE = "en-US-AnaNeural"

#: Percentages and Hz, as strings. edge-tts requires the signs and units.
EDGE_RATE = "+8%"
EDGE_PITCH = "+0Hz"
EDGE_VOLUME = "+0%"

#: Seconds. Kept short so a dead network falls back quickly instead of
#: leaving BMO silent while the display carries on.
EDGE_CONNECT_TIMEOUT = 8
EDGE_RECEIVE_TIMEOUT = 25

#: After edge-tts fails, wait this long before trying the network again.
EDGE_RETRY_COOLDOWN = 60.0

# --------------------------------------------------------------------- fonts

FONT_NAME = "Arial"
MESSAGE_FONT_SIZE = 28
HINT_FONT_SIZE = 18

HINT_TEXT = "H = Happy   S = Sleepy   N = Normal   ESC = Quit"
