import pygame
import numpy as np
from pynput import keyboard, mouse
import os
import re

# Funkce pro nalezení posledního čísla v názvu souboru
def find_last_file_number(path, prefix):
    max_num = -1
    for file in os.listdir(path):
        if file.startswith(prefix) and file.endswith(".png"):
            num_part = re.findall(r'\d+', file)
            if num_part:
                num = int(num_part[0])
                max_num = max(max_num, num)
    return max_num

# Nastavení
canvas_size = (300, 300)
pixel_size = 2

# Inicializace Pygame
pygame.init()
screen = pygame.display.set_mode((canvas_size[0] * pixel_size, canvas_size[1] * pixel_size))
pygame.display.set_caption("optický rytmus psaní na klávesnici")

# Plátno pro pixel art
canvas = np.full((canvas_size[0], canvas_size[1]), 255, dtype=np.uint8)

# Listener pro pynput
input_received = False
def on_press(key):
    global input_received
    input_received = True

def on_click(x, y, button, pressed):
    global input_received
    if pressed:
        input_received = True

keyboard_listener = keyboard.Listener(on_press=on_press)
mouse_listener = mouse.Listener(on_click=on_click)

keyboard_listener.start()
mouse_listener.start()

# Hlavní smyčka
running = True
while running:
    # Resetování plátna pro nový obrázek
    canvas = np.full((canvas_size[0], canvas_size[1]), 255, dtype=np.uint8)

    for y in range(canvas_size[1]):
        for x in range(canvas_size[0]):
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break

            if input_received:
                canvas[x, y] = 0  # Obarvení pixelu na černo
                input_received = False

            if not running:
                break

            # Aktualizace obrazovky
            screen.fill((0, 0, 0))
            for i in range(canvas_size[0]):
                for j in range(canvas_size[1]):
                    if canvas[i, j] == 255:
                        pygame.draw.rect(screen, (255, 255, 255), 
                                         (i * pixel_size, j * pixel_size, pixel_size, pixel_size))
            pygame.display.flip()
            pygame.time.wait(100)

    if not running:
        break

    # Název souboru
    last_num = find_last_file_number('.', 'output_')
    filename = f"output_{last_num + 1:04d}.png"

    # Uložení obrázku
    pygame.image.save(screen, filename)

# Ukončení listenerů a Pygame
keyboard_listener.stop()
mouse_listener.stop()
pygame.quit()
