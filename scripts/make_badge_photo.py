"""Make the badge portrait: cut the person out of a plain studio backdrop, turn it
black and white and add a white sticker outline.

    .venv/bin/python scripts/make_badge_photo.py [var/brand/photo.webp]

Writes var/brand/photo-cutout.png (stays on this machine; var/ is not in Git).
The backdrop is found by flooding inward from the top, left and right edges over
pixels that look like the backdrop (dark-to-mid, noticeably blue), so a dark tie
or jacket inside the figure is kept.
"""
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "var" / "brand" / "photo.webp"
OUT = ROOT / "var" / "brand" / "photo-cutout.png"
OUTLINE = 16  # px of white sticker border


def is_backdrop(rgb):
    r, g, b = rgb
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return lum < 90 and b - r > 18 and b >= g


def backdrop_mask(img):
    w, h = img.size
    px = img.load()
    seen = bytearray(w * h)
    q = deque()
    seeds = [(x, 0) for x in range(w)] + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    for x, y in seeds:
        if is_backdrop(px[x, y]) and not seen[y * w + x]:
            seen[y * w + x] = 1
            q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and is_backdrop(px[nx, ny]):
                seen[ny * w + nx] = 1
                q.append((nx, ny))
    mask = Image.frombytes("L", (w, h), bytes(0 if s else 255 for s in seen))
    # Close small gaps, then soften the edge.
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    return mask.filter(ImageFilter.GaussianBlur(1.2))


def main():
    img = Image.open(SRC).convert("RGB")
    person = backdrop_mask(img)

    bw = ImageOps.grayscale(img)
    bw = ImageOps.autocontrast(bw, cutoff=1)
    bw = ImageEnhance.Contrast(bw).enhance(1.25)
    bw = bw.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=2))

    hard = person.point(lambda v: 255 if v > 100 else 0)
    outline = hard
    for _ in range(OUTLINE // 2):
        outline = outline.filter(ImageFilter.MaxFilter(5))
    outline = outline.filter(ImageFilter.GaussianBlur(1.5))

    pad = OUTLINE * 2
    w, h = img.size
    canvas = Image.new("RGBA", (w + pad * 2, h + pad), (0, 0, 0, 0))
    white = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    canvas.paste(white, (pad, pad), outline)
    face = Image.merge("RGBA", (bw, bw, bw, ImageChops.multiply(person, Image.new("L", (w, h), 255))))
    canvas.alpha_composite(face, (pad, pad))
    bbox = canvas.getbbox()
    canvas.crop(bbox).save(OUT)
    print(f"Wrote {OUT} {canvas.crop(bbox).size}")


if __name__ == "__main__":
    main()
