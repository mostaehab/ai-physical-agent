"""Hear every voice installed on this machine, so you can pick one.

    py -3.12 voice_demo.py --edge     the neural voices BMO uses now (internet)
    py -3.12 voice_demo.py            the offline Windows voices
    py -3.12 voice_demo.py --pitch    sweep the pitch of the offline voice
    py -3.12 voice_demo.py --list     just list the offline voices, no audio

Once you have chosen, set it in bmo/config.py:

    EDGE_VOICE   = "en-US-AnaNeural"   # when SPEECH_BACKEND = "edge"
    SPEECH_VOICE = "Zira"              # the offline fallback
    SPEECH_PITCH = 8
"""

from __future__ import annotations

import logging
import sys

from bmo import config
from bmo.audio import (
    MAX_PITCH,
    MIN_PITCH,
    EdgeTtsBackend,
    Pyttsx3Backend,
    list_voices,
)

SAMPLE = "Hello! I'm BMO. Who wants to play video games?"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    logging.getLogger("comtypes").setLevel(logging.WARNING)

    if "--edge" in sys.argv:
        demo_edge_voices()
        return

    voices = list_voices()
    if not voices:
        print("No speech voices are installed on this machine.")
        return

    print(f"\n{len(voices)} voice(s) installed:\n")
    for index, (name, _) in enumerate(voices, 1):
        print(f"  {index}. {name}")

    current = config.SPEECH_VOICE or "(system default)"
    print(
        f"\nBMO is currently set to: {current} at pitch "
        f"{config.SPEECH_PITCH:+d}, {config.SPEECH_RATE} wpm"
    )

    if "--list" in sys.argv:
        return

    if "--pitch" in sys.argv:
        sweep_pitch()
        return

    print("\nSpeaking a sample in each. Listen for the one you like...\n")
    for index, (name, _) in enumerate(voices, 1):
        print(f"  {index}. {name} ...", flush=True)
        try:
            Pyttsx3Backend(voice=name).say(SAMPLE)
        except Exception as error:  # keep going through the rest
            print(f"     failed: {error}")

    print("\nTo use one, open bmo/config.py and set, for example:")
    print('    SPEECH_VOICE = "Zira"')
    print("\nA substring of the name is enough. Then run: py -3.12 main.py")
    print("To tune how high BMO sounds:  py -3.12 voice_demo.py --pitch")


#: Neural candidates worth hearing. Ana is the only true child voice.
EDGE_CANDIDATES = [
    ("en-US-AnaNeural", "child, tagged Cute - closest to BMO"),
    ("en-US-JennyNeural", "young adult, friendly"),
    ("en-US-AriaNeural", "adult, bright"),
    ("en-GB-MaisieNeural", "British child"),
]


def demo_edge_voices() -> None:
    """Speak a sample with each neural candidate. Needs internet."""
    print(
        f"\nBMO currently uses: {config.EDGE_VOICE} at rate {config.EDGE_RATE}"
    )
    print("\nSpeaking a sample with each candidate...\n")

    for name, blurb in EDGE_CANDIDATES:
        marker = "   <- current" if name == config.EDGE_VOICE else ""
        print(f"  {name:22} {blurb}{marker}", flush=True)
        try:
            EdgeTtsBackend(voice=name).say(SAMPLE)
        except Exception as error:
            print(f"     failed: {error}")
            print("     (no internet? BMO falls back to the offline voice)")

    print("\nPick one and set it in bmo/config.py:")
    print('    EDGE_VOICE = "en-US-AnaNeural"')


def sweep_pitch() -> None:
    """Speak the same line at several pitches so you can pick one."""
    voice = config.SPEECH_VOICE
    print(
        f"\nSweeping pitch on {voice or '(system default)'}. "
        f"{MIN_PITCH} is deep, {MAX_PITCH} is squeaky.\n"
    )
    for pitch in (0, 4, 6, 8, 10):
        marker = "   <- current setting" if pitch == config.SPEECH_PITCH else ""
        print(f"  pitch {pitch:+3d}{marker}", flush=True)
        try:
            Pyttsx3Backend(voice=voice, pitch=pitch).say(SAMPLE)
        except Exception as error:
            print(f"     failed: {error}")

    print("\nPick the one you liked and set it in bmo/config.py, e.g.:")
    print("    SPEECH_PITCH = 8")


if __name__ == "__main__":
    main()
