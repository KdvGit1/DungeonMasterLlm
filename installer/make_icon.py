"""Draw the app icon (installer/dndmaster.ico): a gold-rimmed crimson d20 face."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def draw(size: int) -> Image.Image:
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = s / 2
    r = s * 0.47
    hexagon = [(cx + r * math.cos(math.radians(90 + 60 * i)), cy + r * math.sin(math.radians(90 + 60 * i)))
               for i in range(6)]
    d.polygon(hexagon, fill=(122, 31, 31, 255), outline=(217, 173, 85, 255), width=max(2, s // 28))
    tri_r = r * 0.62
    tri = [(cx + tri_r * math.cos(math.radians(-90 + 120 * i)), cy + tri_r * math.sin(math.radians(-90 + 120 * i)) + s * 0.03)
           for i in range(3)]
    d.polygon(tri, outline=(240, 207, 133, 255), width=max(2, s // 36))
    for p in tri:
        d.line([p, (p[0] + (cx - p[0]) * 0.0, p[1])], fill=(240, 207, 133, 255))
    try:
        font = ImageFont.truetype(str(Path(__file__).parent.parent / "web/vendor/fonts/Cinzel.ttf"), int(s * 0.26))
    except OSError:
        font = ImageFont.load_default()
    d.text((cx, cy + s * 0.07), "20", font=font, fill=(246, 231, 193, 255), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).parent / "dndmaster.ico"
    big = draw(256)
    big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(Path(__file__).parent / "dndmaster.png")
    print(out)


if __name__ == "__main__":
    main()
