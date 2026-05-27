"""Generate Silent logo PNG/ICO from in-app proportions (56dp box, 16dp radius, 22sp S)."""
from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("pip install pillow")

ROOT = Path(__file__).resolve().parents[1]
BOX_RATIO = 56
CORNER_RATIO = 16 / BOX_RATIO
FONT_RATIO = 22 / BOX_RATIO

ANDROID_SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_logo(size: int, *, transparent_bg: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0) if transparent_bg else (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    radius = max(2, int(round(size * CORNER_RATIO)))
    box = (0, 0, size - 1, size - 1)
    draw.rounded_rectangle(box, radius=radius, fill=(0, 0, 0, 255))

    font_size = max(8, int(round(size * FONT_RATIO)))
    font = _load_font(font_size)
    text = "S"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return img


def save_png(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    render_logo(size).convert("RGB").save(path, "PNG")
    print(f"  {path.relative_to(ROOT)} ({size}px)")


def save_ico(path: Path, sizes: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    images = [render_logo(s).convert("RGBA") for s in sizes]
    images[0].save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"  {path.relative_to(ROOT)} ({sizes})")


def main() -> None:
    print("Generating Silent logo assets…")
    android_res = ROOT / "android" / "app" / "src" / "main" / "res"
    for folder, size in ANDROID_SIZES.items():
        base = android_res / folder
        save_png(base / "ic_launcher.png", size)
        save_png(base / "ic_launcher_round.png", size)

    pc_assets = ROOT / "pc" / "assets"
    save_png(pc_assets / "icon.png", 512)
    save_png(pc_assets / "tray.png", 64)
    save_ico(pc_assets / "icon.ico", [16, 32, 48, 64, 128, 256])

    admin_public = ROOT / "backend" / "admin-ui" / "public"
    save_png(admin_public / "logo.png", 128)
    save_png(admin_public / "logo-32.png", 32)

    # favicon for admin
    render_logo(32).save(admin_public / "favicon.png", "PNG")
    print("Done.")


if __name__ == "__main__":
    main()
