#!/usr/bin/env python3
"""Generate Silent brand icon: black rounded square + white S (matches SilentLogo)."""
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("pip install pillow")

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SIZE = 512
RADIUS = round(SIZE * (16 / 56))
MARGIN = round(SIZE * 0.08)


def draw_logo(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = round(size * (16 / 56))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=(0, 0, 0, 255))
    font_size = round(size * (22 / 56))
    try:
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("segoeuib.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
    text = "S"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return img


def save_ico(png: Image.Image, path: Path) -> None:
    sizes = [256, 128, 64, 48, 32, 16]
    icons = [png.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    icons[0].save(path, format="ICO", sizes=[(s, s) for s in sizes])


ANDROID_DENSITIES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}


def write_android_icons(master: Image.Image) -> None:
    res_root = ROOT.parent / "android" / "app" / "src" / "main" / "res"
    if not res_root.is_dir():
        print("skip android:", res_root, "not found")
        return
    for folder, px in ANDROID_DENSITIES.items():
        out_dir = res_root / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        icon = master.resize((px, px), Image.Resampling.LANCZOS)
        for name in ("ic_launcher.png", "ic_launcher_round.png"):
            icon.save(out_dir / name, "PNG")
        print("wrote", out_dir)


def main() -> None:
    import sys

    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_logo(SIZE)
    master.save(ASSETS / "icon.png", "PNG")
    tray = master.resize((32, 32), Image.Resampling.LANCZOS)
    tray.save(ASSETS / "tray.png", "PNG")
    save_ico(master, ASSETS / "icon.ico")
    print("wrote", ASSETS / "icon.png", ASSETS / "icon.ico", ASSETS / "tray.png")
    if "--android" in sys.argv or (ROOT.parent / "android").is_dir():
        write_android_icons(master)


if __name__ == "__main__":
    main()
