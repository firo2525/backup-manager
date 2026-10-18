"""Icons aus der Windows-Symbolschrift (Segoe Fluent Icons / Segoe MDL2 Assets) als CTkImage."""
import os

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from engine.ui import theme

_FONT_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "SegoeIcons.ttf"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segmdl2.ttf"),
]
FONT_PATH = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)

GLYPHS = {
    "home": "\uE80F", "folder": "\uE8B7", "file": "\uE8A5", "history": "\uE81C", "settings": "\uE713",
    "list": "\uE8FD", "play": "\uE768", "stop": "\uE71A", "refresh": "\uE72C", "delete": "\uE74D",
    "add": "\uE710", "close": "\uE711", "info": "\uE946", "warning": "\uE7BA", "error": "\uE783",
    "check": "\uE73E", "completed": "\uE930", "undo": "\uE7A7", "drive": "\uEDA2", "search": "\uE721",
    "clock": "\uE823", "copy": "\uE8C8", "shield": "\uEA18", "sync": "\uE895", "download": "\uE896",
    "upload": "\uE898", "folder_open": "\uE838", "new_folder": "\uE8F4", "open_file": "\uE8E5",
    "moon": "\uE708", "sun": "\uE706", "filter": "\uE71C", "more": "\uE712", "save": "\uE74E",
    "library": "\uE8F1", "broom": "\uEA99", "open_local": "\uE8DA", "diagnostic": "\uE9D9",
    "calendar": "\uE787", "chevron": "\uE76C", "restore": "\uE777", "save_copy": "\uEA35", "globe": "\uE774",
    "lock": "\uE72E",
}

_cache = {}


def _render(glyph, px, color):
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    fnt = ImageFont.truetype(FONT_PATH, int(px * 0.86))
    draw = ImageDraw.Draw(img)
    l, t, r, b = draw.textbbox((0, 0), glyph, font=fnt)
    draw.text(((px - (r - l)) / 2 - l, (px - (b - t)) / 2 - t), glyph, font=fnt, fill=color)
    return img


def icon(name, size=18, color=theme.TEXT):
    """CTkImage für Hell- und Dunkelmodus; None, wenn keine Symbolschrift vorhanden ist."""
    if not FONT_PATH or name not in GLYPHS:
        return None
    if isinstance(color, str):
        color = (color, color)
    key = (name, size, tuple(color))
    if key not in _cache:
        px = size * 3
        _cache[key] = ctk.CTkImage(
            light_image=_render(GLYPHS[name], px, color[0]),
            dark_image=_render(GLYPHS[name], px, color[1]),
            size=(size, size),
        )
    return _cache[key]


def app_icon_image(px=256):
    """App-Symbol: Schild mit Sync-Pfeilen auf Indigo-Verlauf."""
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    grad = Image.new("RGBA", (px, px))
    top, bottom = (99, 102, 241), (67, 56, 202)
    gd = ImageDraw.Draw(grad)
    for y in range(px):
        k = y / max(1, px - 1)
        gd.line([(0, y), (px, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)) + (255,))
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, px - 1, px - 1], radius=int(px * 0.23), fill=255)
    img.paste(grad, (0, 0), mask)
    if FONT_PATH:
        glyph = _render(GLYPHS["shield"], int(px * 0.72), (255, 255, 255, 255))
        img.alpha_composite(glyph, (int(px * 0.14), int(px * 0.14)))
        inner = _render(GLYPHS["sync"], int(px * 0.34), (255, 255, 255, 255))
        img.alpha_composite(inner, (int(px * 0.33), int(px * 0.31)))
    return img


def ensure_app_icon(path):
    """Erzeugt app.ico (falls nicht vorhanden) und gibt den Pfad zurück."""
    if os.path.exists(path):
        return path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        app_icon_image(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return path
    except Exception:
        return None
