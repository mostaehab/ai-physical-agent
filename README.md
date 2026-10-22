# BMO

A small BMO-inspired AI companion. Right now it is a desktop prototype: a teal
Pygame window with an animated face that changes mood and talks.

The long-term goal is a physical, wheeled robot on a Raspberry Pi with voice,
camera, memory and safe movement. The prototype is stable and the code is
organised into modules; **conversational AI is next**.

---

## Quick start

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 main.py
```

| Key   | What happens                                       |
|-------|----------------------------------------------------|
| `H`   | Happy face, BMO says "Yay! Let's play!"            |
| `S`   | Sleepy face, BMO says "Zzz... I'm sleepy."         |
| `N`   | Normal face, BMO says "Hello! I'm BMO."            |
| `ESC` | Quit (closing the window works too)                 |

---

## What works today

- Teal window, dark face panel, cyan eyes, white mouth.
- Three moods (normal, happy, sleepy) with matching eyes and mouth.
- Automatic blinking every 3 seconds, except while sleepy.
- Speech on every mood change, as many times as you like.
- A childlike neural voice (`en-US-AnaNeural`), with an automatic offline
  fallback so BMO never goes mute when the network drops.
- The animation keeps running at 60 fps while BMO is talking.
- Closing the window stops the speech thread and exits cleanly.

---

## Architecture

Small modules, each with one job. Only modules that have real code today exist;
`camera.py`, `motors.py`, `sensors.py`, the `agent/` package and the `safety/`
layer arrive in later phases rather than sitting empty now.

| File              | Responsibility                                        |
|-------------------|-------------------------------------------------------|
| `main.py`         | startup, the event loop, wiring components together   |
| `bmo/config.py`   | every tunable setting: colours, moods, timings, rate  |
| `bmo/display.py`  | face state, expressions, blinking, drawing, window    |
| `bmo/audio.py`    | speech queue, worker thread, neural + offline voices  |

```
  main thread                          speech worker thread
  -----------                          --------------------
  main.run()
    key press -> handle_key()
                   |
                   +- face.set_mood(mood)        (bmo/display.py)
                   |
                   +- speech.speak(line) -----> [ queue ] --> backend.say(line)
                   |    (returns instantly)                    (blocks here,
    update_blink(face)                                          not in the UI)
    display.render(face)
```

`SpeechEngine` owns one queue and one worker thread. One worker means
utterances can never overlap or fight over the audio device.

Adding a mood is now a two-line change: add the line to `MOOD_LINES` in
`bmo/config.py`, add its key to `KEY_MOODS` in `bmo/display.py`, then give it
eyes and a mouth in `draw_face`.

### The speech bug, and why it is fixed

**Symptom:** BMO spoke once at startup and then went silent, even though the
same code worked in `voice_test.py`.

**Cause:** `pyttsx3` caches engines in a module-level
`weakref.WeakValueDictionary`, so `pyttsx3.init()` returns the *same* engine
while any reference to it is still alive. The old worker loop kept its `engine`
variable bound across the next `init()` call, so every utterance after the
first reused one engine.

A reused engine is broken in a specific way. After the first `runAndWait()`,
pyttsx3 leaves its internal `_busy` flag `False`. On the next utterance `say()`
is therefore no longer deferred: SAPI starts speaking *before* the event loop
runs. `runAndWait()` then starts that loop, which immediately pumps the queued
`endLoop` command, which calls the driver's `stop()` and purges the utterance
that had only just started. The call returns in about 0.25 s having said
nothing. `voice_test.py` never hit this because its `engine` was a function
local that died on return, which cleared the cache entry.

**Fix:** build a genuinely fresh engine per utterance and drop every reference
to the old one *before* the next `init()` — see `Pyttsx3Backend.say` in
`bmo/audio.py`.

Measured, five consecutive utterances:

| Utterance | Before the fix | After the fix |
|-----------|----------------|---------------|
| 1         | 3.89 s spoke   | 4.41 s spoke  |
| 2         | 0.27 s silent  | 3.09 s spoke  |
| 3         | 0.23 s silent  | 3.42 s spoke  |
| 4         | 0.22 s silent  | 3.18 s spoke  |
| 5         | 0.22 s silent  | 3.22 s spoke  |

Building an engine costs about 0.3 s. That happens on the worker thread, so
the face never stalls.

---

## Tests

```powershell
py -3.12 -m unittest discover -s tests -t . -v
```

54 fast tests, no audio and no window. They cover mood state and transitions,
mood keys driving both the face and the speech, blink timing, drawing every
mood, the window wrapper, voice matching, pitch markup and its XML escaping,
offline fallback and its retry cooldown, speech queue ordering, backend
failures, and clean shutdown.

Seven further tests drive the **real** speech engines, including a live
`edge-tts` round trip. They are skipped by default because they take about
45 seconds and the edge ones need internet. They are the ones that actually catch the
bug described above, so run them after any change to `bmo/audio.py`:

```powershell
$env:BMO_AUDIO_TESTS = "1"
py -3.12 -m unittest discover -s tests -t . -v
Remove-Item Env:\BMO_AUDIO_TESTS
```

They force volume to 0, so nothing is audible. A real utterance takes over a
second; the bug made every utterance return in ~0.25 s, so the test asserts on
duration.

---

## Making BMO sound like BMO

BMO speaks with **`en-US-AnaNeural`**, Microsoft's child voice (the catalogue
tags it "Cute"). It is the closest thing to the cartoon in a stock voice
catalogue: genuinely childlike, rather than an adult voice pitched up.

It needs an internet connection. When the network is unavailable BMO
automatically drops to the offline Windows voice instead of going mute.

```python
# bmo/config.py
SPEECH_BACKEND = "edge"             # "edge" (neural) or "pyttsx3" (offline)

EDGE_VOICE = "en-US-AnaNeural"      # used when SPEECH_BACKEND = "edge"
EDGE_RATE  = "+8%"

SPEECH_VOICE = "Zira"               # the offline fallback voice
SPEECH_PITCH = 8                    # -10 deep .. +10 squeaky
SPEECH_RATE  = 175
```

Audition the options:

```powershell
py -3.12 voice_demo.py --edge     # neural candidates (needs internet)
py -3.12 voice_demo.py            # the offline Windows voices
py -3.12 voice_demo.py --pitch    # pitch sweep on the offline voice
```

### How the two backends fit together

```
  speak("Yay!")
        |
        v
  FallbackBackend
        |
        +--> EdgeTtsBackend    neural voice, needs internet
        |      (on failure: log it, rest the network for 60s)
        |
        +--> Pyttsx3Backend    offline SAPI voice, always available
```

A network blip costs one utterance in the lesser voice, then BMO retries the
network a minute later. It never goes silent, and it never retries a dead
connection on every single line.

### Want to go fully offline?

Set `SPEECH_BACKEND = "pyttsx3"`. You lose the childlike voice and get pitched
Zira, but there is no network dependency at all — which is the right starting
point for a Raspberry Pi build.

### The honest limit

Even `AnaNeural` is a generic child voice, not Niki Yang's performance. Getting
genuinely closer means voice cloning from show clips (XTTS, RVC), which wants a
GPU and will not run well on a Pi. `bmo/audio.py` defines a `SpeechBackend`
protocol, so that would drop in as another backend if you ever want it.

### Offline speech on a Raspberry Pi

`edge-tts` is pure Python and works on a Pi, so the neural voice carries over as
long as the Pi has Wi-Fi. The *fallback* is the part that changes: `pyttsx3`
uses eSpeak on Linux, which sounds considerably worse than Zira. Benchmark both
before committing.

---

## Troubleshooting

**BMO speaks once and then goes quiet.**
The regression described above. Run the live tests; if they fail, something has
started holding a reference to the pyttsx3 engine again.

**BMO sounds wrong, or you want a different voice.**
See "Making BMO sound like BMO" above, then run
`py -3.12 voice_demo.py --pitch`.

**`voice 'X' not found, using the system default`.**
That warning lists the voices you actually have. Set `SPEECH_VOICE` in
`bmo/config.py` to a substring of one of them, or to `None` for the default.

**No sound at all.**
Check the engine works on its own first:

```powershell
py -3.12 voice_test.py
```

If that is silent, the problem is Windows audio or SAPI, not BMO. Check the
output device and that a voice is installed under
Settings → Time & language → Speech.

**The window freezes while BMO talks.**
Speech should never run on the main thread. Anything that calls
`backend.say()` directly from the main thread will freeze the display; go through
`SpeechEngine.speak()`.

**Errors vanish silently.**
They should not. `main.py` configures logging at INFO, and a backend failure is
logged with a full traceback by `SpeechEngine._run`. If you see nothing at all,
check that `logging.basicConfig` has not been called earlier by something else.

**`ModuleNotFoundError: No module named 'pygame'`.**
You are probably on the wrong interpreter. This project uses Python 3.12, so
always launch with `py -3.12`, not `python`.

---

## Raspberry Pi differences (for later)

Nothing here is Pi-specific yet, but for planning:

- `pywin32` and `comtypes` are Windows-only. Leave them out of the Pi install.
- `edge-tts` is pure Python and works on a Pi, so the neural voice carries
  over as long as there is Wi-Fi.
- pyttsx3 on Linux uses eSpeak: `sudo apt install espeak`. Voice quality is
  noticeably worse; a different backend may be worth testing. `bmo/audio.py`
  already defines a `SpeechBackend` protocol so a replacement can be dropped in
  without touching the display or the queue.
- Speech quality and latency on a Pi have **not** been benchmarked.

---

## Roadmap

- [x] **Phase 1 — stabilise the prototype.** Face, moods, reliable repeatable
      speech, clean shutdown, tests, docs.
- [x] **Phase 2 — organise into modules.** `config`, `display`, `audio`,
      with `main.py` reduced to startup and the event loop.
- [ ] Phase 3 — conversational AI behind a swappable provider interface.
- [ ] Phase 4 — microphone (push-to-talk) and camera.
- [ ] Phase 5 — AI tools and simulated motors, behind a safety layer.
- [ ] Phase 6 — real Raspberry Pi hardware.
- [ ] Phase 7 — memory and personality.

---

## Project layout

```
customized-ai/
  main.py                      startup, event loop, wiring
  bmo/
    __init__.py
    config.py                  colours, moods, timings, speech settings
    display.py                 face state, blinking, drawing, window
    audio.py                   speech queue, worker thread, voice backends
  voice_demo.py                hear and tune the installed voices
  voice_test.py                standalone speech check, independent of Pygame
  requirements.txt
  README.md
  tests/
    test_display.py            moods, keys, blinking, drawing, window
    test_audio.py              queue, ordering, failures, shutdown (fast)
    test_audio_pyttsx3.py      live offline speech regression (opt-in)
    test_audio_edge.py         live neural speech, needs internet (opt-in)
  backup/
    main_original.py           the prototype as it was before Phase 1
    voice_test_original.py     ditto, kept in case you want to compare
```
