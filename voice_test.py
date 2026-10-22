
import pyttsx3

def speak(text):
    engine = pyttsx3.init()
    engine.setProperty("rate", 160)
    engine.say(text)
    engine.runAndWait()
    engine.stop()

speak("Hello! I am BMO.")

input("Press Enter to speak again...")

speak("Yay! Let's play!")

input("Press Enter to finish...")
