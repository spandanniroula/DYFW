"""Draws the minimized bubble: an Apple-Watch-style progress ring on a dark disc.

Returns a PIL RGBA image (with a soft shadow) that platform_utils.update_layered() can put
on screen with true per-pixel transparency.
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import colors

SS = 4  # supersampling for smooth edges
DISC = "#1c1c1e"
FOCUS_GREEN = "#30d158"
BADGE_RED = "#ff3b30"
_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_font_cache = {}


def _font(kind, px):
    key = (kind, px)
    if key in _font_cache:
        return _font_cache[key]
    candidates = {
        "number": [("SegUIVar.ttf", "Semibold"), ("seguisb.ttf", None), ("segoeui.ttf", None)],
        "badge": [("SegUIVar.ttf", "Bold"), ("segoeuib.ttf", None), ("segoeui.ttf", None)],
        "icon": [("SegoeIcons.ttf", None), ("segmdl2.ttf", None)],
    }[kind]
    font = None
    for name, variation in candidates:
        try:
            font = ImageFont.truetype(os.path.join(_FONT_DIR, name), px)
            if variation:
                try:
                    font.set_variation_by_name(variation)
                except Exception:
                    pass
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    _font_cache[key] = font
    return font


def _centered_text(draw, cx, cy, text, font, fill):
    """Center by the glyphs' actual ink, so digits sit exactly in the middle."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (left + right) / 2, cy - (top + bottom) / 2), text, font=font, fill=fill)


def ring_color(theme):
    """The theme's color, unless it's too dark to read on the dark disc."""
    for c in (theme["header"], theme["accent"]):
        if colors.luminance(c) > 0.08:
            return c
    return "#0a84ff"


def render(window_px, disc_px, *, ring, progress, label=None, icon=None, badge=0, dot=False):
    """
    window_px: full image size (disc + room for the shadow), disc_px: disc diameter.
    progress: 0..1 ring fill. label: text in the middle, or icon: a Segoe icon glyph.
    badge: red count badge (0 = none), dot: small red dot instead of a count.
    """
    W, D = window_px * SS, disc_px * SS
    cx = cy = W / 2
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    # soft drop shadow
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    off = D * 0.035
    sd.ellipse((cx - D / 2, cy - D / 2 + off, cx + D / 2, cy + D / 2 + off), fill=(0, 0, 0, 120))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(D * 0.06)))

    d = ImageDraw.Draw(img)
    disc_box = (cx - D / 2, cy - D / 2, cx + D / 2, cy + D / 2)
    d.ellipse(disc_box, fill=DISC)
    # faint rim so the dark disc still reads on dark wallpapers (own layer so it blends)
    rim = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(rim).ellipse(disc_box, outline=(255, 255, 255, 34), width=SS)
    img = Image.alpha_composite(img, rim)
    d = ImageDraw.Draw(img)

    # activity ring: dim track + progress arc with round caps, starting at 12 o'clock
    width = D * 0.105
    inset = D * 0.085 + width / 2
    r = D / 2 - inset
    ring_box = (cx - r - width / 2, cy - r - width / 2, cx + r + width / 2, cy + r + width / 2)
    d.ellipse(ring_box, outline=colors.mix(ring, DISC, 0.72), width=int(width))
    progress = max(0.0, min(1.0, progress))
    if progress > 0.001:
        end = -90 + 360 * progress
        d.arc(ring_box, -90, end, fill=ring, width=int(width))
        for ang in (-90, end):
            a = math.radians(ang)
            px, py = cx + r * math.cos(a), cy + r * math.sin(a)
            d.ellipse((px - width / 2, py - width / 2, px + width / 2, py + width / 2), fill=ring)

    # center content
    if icon:
        _centered_text(d, cx, cy, icon, _font("icon", int(D * 0.30)), ring)
    elif label:
        size = D * (0.40 if len(label) <= 2 else 0.30)
        _centered_text(d, cx, cy, label, _font("number", int(size)), "#ffffff")

    # notification badge / dot, iOS style, at the disc's top-right
    if badge or dot:
        bd = D * (0.36 if badge else 0.19)
        bx, by = cx + D * 0.36, cy - D * 0.36
        d.ellipse((bx - bd / 2, by - bd / 2, bx + bd / 2, by + bd / 2), fill=BADGE_RED)
        if badge:
            text = str(badge) if badge < 10 else "9+"
            _centered_text(d, bx, by, text, _font("badge", int(bd * (0.62 if len(text) == 1 else 0.5))),
                           "#ffffff")

    return img.resize((window_px, window_px), Image.LANCZOS)
