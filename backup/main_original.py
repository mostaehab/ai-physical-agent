
import pygame
import time
import threading
import queue
import pyttsx3

# ---------- Voice ----------
speech_queue = queue.Queue()

def speech_worker():
    while True:
        text = speech_queue.get()

        if text is None:
            break

        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 160)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as error:
            print("Voice error:", error)
        finally:
            speech_queue.task_done()

threading.Thread(target=speech_worker, daemon=True).start()

def speak(text):
    speech_queue.put(text)

# ---------- BMO screen ----------
pygame.init()

WIDTH, HEIGHT = 600, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("BMO")

font = pygame.font.SysFont("Arial", 28, bold=True)
clock = pygame.time.Clock()

TEAL = (90, 200, 190)
DARK = (25, 40, 45)
CYAN = (80, 240, 255)
WHITE = (255, 255, 255)

mood = "normal"
message = "Hello! I'm BMO."
last_blink = time.time()
blinking = False
blink_duration = 0.15

speak("Hello! I'm BMO.")

running = True

while running:
    now = time.time()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_h:
                mood = "happy"
                message = "Yay! Let's play!"
                speak(message)

            elif event.key == pygame.K_s:
                mood = "sleepy"
                message = "Zzz... I'm sleepy."
                speak(message)

            elif event.key == pygame.K_n:
                mood = "normal"
                message = "Hello! I'm BMO."
                speak(message)

    # Automatic blinking unless sleepy
    if mood != "sleepy" and now - last_blink > 3:
        blinking = True
        last_blink = now

    if blinking and now - last_blink > blink_duration:
        blinking = False

    # Draw BMO
    screen.fill(TEAL)
    pygame.draw.rect(screen, DARK, (100, 80, 400, 330), border_radius=35)

    if mood == "sleepy" or blinking:
        pygame.draw.line(screen, CYAN, (180, 230), (250, 230), 6)
        pygame.draw.line(screen, CYAN, (350, 230), (420, 230), 6)

    elif mood == "happy":
        pygame.draw.arc(screen, CYAN, (165, 190, 100, 90), 0, 3.14, 6)
        pygame.draw.arc(screen, CYAN, (335, 190, 100, 90), 0, 3.14, 6)

    else:
        pygame.draw.circle(screen, CYAN, (215, 225), 25)
        pygame.draw.circle(screen, CYAN, (385, 225), 25)

    if mood == "happy":
        pygame.draw.arc(screen, WHITE, (230, 260, 140, 90), 3.14, 6.28, 5)
    elif mood == "sleepy":
        pygame.draw.line(screen, WHITE, (250, 300), (350, 300), 5)
    else:
        pygame.draw.arc(screen, WHITE, (250, 260, 100, 70), 3.14, 6.28, 5)

    text_surface = font.render(message, True, WHITE)
    text_rect = text_surface.get_rect(center=(300, 470))
    screen.blit(text_surface, text_rect)

    hint = pygame.font.SysFont("Arial", 18).render(
        "H = Happy   S = Sleepy   N = Normal", True, DARK
    )
    screen.blit(hint, hint.get_rect(center=(300, 550)))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
