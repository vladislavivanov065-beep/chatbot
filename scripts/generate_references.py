"""Generate colorful, moderately detailed reference drawings used as targets in the game.

Run once (locally, at build time) to (re)populate static/references/*.png.
Each image is a filled, multi-color picture with black outlines at 300x300.
"""
import math
import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "references")
SIZE = 300
LINE = 6
BLACK = (20, 20, 20)
WHITE = (255, 255, 255)
RED = (230, 57, 70)
ORANGE = (244, 140, 6)
YELLOW = (255, 209, 102)
GREEN = (64, 145, 108)
BLUE = (69, 123, 157)
SKY = (168, 218, 220)
BROWN = (121, 85, 61)
PINK = (255, 143, 171)


def blank():
    return Image.new("RGB", (SIZE, SIZE), WHITE)


def draw_apple():
    img = blank()
    d = ImageDraw.Draw(img)
    d.ellipse([70, 90, 230, 250], fill=RED, outline=BLACK, width=LINE)
    d.line([(150, 90), (140, 50)], fill=BROWN, width=8)
    d.polygon([(150, 60), (195, 40), (175, 85)], fill=GREEN, outline=BLACK, width=4)
    d.ellipse([100, 120, 135, 155], fill=(255, 205, 210))
    return img


def draw_balloon():
    img = blank()
    d = ImageDraw.Draw(img)
    d.ellipse([90, 30, 210, 190], fill=RED, outline=BLACK, width=LINE)
    d.polygon([(140, 188), (160, 188), (150, 210)], fill=RED, outline=BLACK, width=3)
    d.line([(150, 210), (138, 245), (162, 260), (145, 280)], fill=BROWN, width=4, joint="curve")
    d.ellipse([112, 55, 132, 75], fill=(255, 205, 210))
    return img


def draw_rocket():
    img = blank()
    d = ImageDraw.Draw(img)
    d.polygon([(150, 35), (192, 125), (108, 125)], fill=RED, outline=BLACK, width=LINE)
    d.rounded_rectangle([108, 120, 192, 225], radius=20, fill=(225, 225, 225), outline=BLACK, width=LINE)
    d.polygon([(108, 180), (65, 245), (108, 220)], fill=BLUE, outline=BLACK, width=5)
    d.polygon([(192, 180), (235, 245), (192, 220)], fill=BLUE, outline=BLACK, width=5)
    d.ellipse([132, 140, 168, 176], fill=SKY, outline=BLACK, width=4)
    d.polygon([(128, 223), (172, 223), (150, 270)], fill=ORANGE, outline=BLACK, width=4)
    return img


def draw_flower():
    img = blank()
    d = ImageDraw.Draw(img)
    cx, cy = 150, 135
    for i in range(6):
        angle = i * math.pi / 3
        px = cx + 55 * math.cos(angle)
        py = cy + 55 * math.sin(angle)
        d.ellipse([px - 38, py - 26, px + 38, py + 26], fill=PINK, outline=BLACK, width=4)
    d.ellipse([cx - 28, cy - 28, cx + 28, cy + 28], fill=YELLOW, outline=BLACK, width=4)
    d.line([(cx, cy + 55), (cx, 265)], fill=GREEN, width=7)
    d.polygon([(cx, 220), (cx - 35, 235), (cx, 250)], fill=GREEN, outline=BLACK, width=3)
    return img


def draw_fish():
    img = blank()
    d = ImageDraw.Draw(img)
    d.ellipse([70, 100, 230, 200], fill=ORANGE, outline=BLACK, width=LINE)
    d.polygon([(75, 150), (30, 105), (30, 195)], fill=BLUE, outline=BLACK, width=5)
    d.polygon([(150, 100), (180, 65), (192, 105)], fill=BLUE, outline=BLACK, width=4)
    d.ellipse([188, 128, 210, 150], fill=(255, 255, 255), outline=BLACK, width=3)
    d.ellipse([197, 134, 205, 142], fill=BLACK)
    return img


def draw_rainbow():
    img = blank()
    d = ImageDraw.Draw(img)
    colors = [RED, ORANGE, YELLOW, GREEN, BLUE]
    for i, c in enumerate(colors):
        r = 110 - i * 16
        d.arc([150 - r, 190 - r, 150 + r, 190 + r], start=180, end=360, fill=c, width=14)
    d.ellipse([35, 220, 100, 260], fill=(255, 255, 255), outline=BLACK, width=4)
    d.ellipse([200, 220, 265, 260], fill=(255, 255, 255), outline=BLACK, width=4)
    return img


def draw_ice_cream():
    img = blank()
    d = ImageDraw.Draw(img)
    d.polygon([(118, 150), (182, 150), (150, 255)], fill=BROWN, outline=BLACK, width=LINE)
    d.ellipse([95, 85, 205, 175], fill=PINK, outline=BLACK, width=LINE)
    d.ellipse([138, 55, 162, 79], fill=RED, outline=BLACK, width=3)
    d.line([(150, 55), (156, 38)], fill=GREEN, width=4)
    return img


def draw_house():
    img = blank()
    d = ImageDraw.Draw(img)
    d.polygon([(150, 40), (40, 140), (260, 140)], fill=RED, outline=BLACK, width=LINE)
    d.rectangle([60, 140, 240, 260], fill=YELLOW, outline=BLACK, width=LINE)
    d.rectangle([135, 190, 175, 260], fill=BROWN, outline=BLACK, width=5)
    d.rectangle([80, 160, 120, 195], fill=SKY, outline=BLACK, width=4)
    d.rectangle([180, 160, 220, 195], fill=SKY, outline=BLACK, width=4)
    d.line([(30, 260), (270, 260)], fill=GREEN, width=8)
    return img


GENERATORS = {
    "apple.png": draw_apple,
    "balloon.png": draw_balloon,
    "rocket.png": draw_rocket,
    "flower.png": draw_flower,
    "fish.png": draw_fish,
    "rainbow.png": draw_rainbow,
    "ice_cream.png": draw_ice_cream,
    "house.png": draw_house,
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # remove any previously generated references not in the current set
    current = set(GENERATORS)
    for existing in os.listdir(OUT_DIR):
        if existing.endswith(".png") and existing not in current:
            os.remove(os.path.join(OUT_DIR, existing))
    for filename, generator in GENERATORS.items():
        path = os.path.join(OUT_DIR, filename)
        generator().save(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
