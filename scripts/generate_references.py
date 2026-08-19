"""Generate simple reference line-drawings used as drawing targets in the game.

Run once (locally, at build time) to (re)populate static/references/*.png.
Each image is a simple black outline on a white background.
"""
import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "references")
SIZE = 300
LINE = 8
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def blank():
    return Image.new("RGB", (SIZE, SIZE), WHITE)


def draw_circle():
    img = blank()
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 260, 260], outline=BLACK, width=LINE)
    return img


def draw_square():
    img = blank()
    d = ImageDraw.Draw(img)
    d.rectangle([50, 50, 250, 250], outline=BLACK, width=LINE)
    return img


def draw_triangle():
    img = blank()
    d = ImageDraw.Draw(img)
    d.polygon([(150, 40), (40, 260), (260, 260)], outline=BLACK, width=LINE)
    return img


def draw_star():
    import math
    img = blank()
    d = ImageDraw.Draw(img)
    cx, cy = 150, 150
    r_outer, r_inner = 120, 50
    points = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = r_outer if i % 2 == 0 else r_inner
        points.append((cx + r * math.cos(angle), cy - r * math.sin(angle)))
    d.polygon(points, outline=BLACK, width=LINE)
    return img


def draw_heart():
    img = blank()
    d = ImageDraw.Draw(img)
    d.pieslice([50, 60, 150, 160], 130, 360, outline=BLACK, width=LINE)
    d.pieslice([150, 60, 250, 160], 180, 50, outline=BLACK, width=LINE)
    d.line([(58, 130), (150, 260)], fill=BLACK, width=LINE)
    d.line([(242, 130), (150, 260)], fill=BLACK, width=LINE)
    return img


def draw_house():
    img = blank()
    d = ImageDraw.Draw(img)
    d.polygon([(150, 40), (40, 140), (260, 140)], outline=BLACK, width=LINE)
    d.rectangle([60, 140, 240, 260], outline=BLACK, width=LINE)
    d.rectangle([135, 190, 175, 260], outline=BLACK, width=LINE)
    return img


def draw_smiley():
    img = blank()
    d = ImageDraw.Draw(img)
    d.ellipse([40, 40, 260, 260], outline=BLACK, width=LINE)
    d.ellipse([95, 110, 125, 140], outline=BLACK, width=LINE)
    d.ellipse([175, 110, 205, 140], outline=BLACK, width=LINE)
    d.arc([90, 130, 210, 220], start=20, end=160, fill=BLACK, width=LINE)
    return img


def draw_tree():
    img = blank()
    d = ImageDraw.Draw(img)
    d.polygon([(150, 40), (80, 140), (220, 140)], outline=BLACK, width=LINE)
    d.polygon([(150, 100), (60, 200), (240, 200)], outline=BLACK, width=LINE)
    d.rectangle([130, 200, 170, 260], outline=BLACK, width=LINE)
    return img


GENERATORS = {
    "circle.png": draw_circle,
    "square.png": draw_square,
    "triangle.png": draw_triangle,
    "star.png": draw_star,
    "heart.png": draw_heart,
    "house.png": draw_house,
    "smiley.png": draw_smiley,
    "tree.png": draw_tree,
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for filename, generator in GENERATORS.items():
        path = os.path.join(OUT_DIR, filename)
        generator().save(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
