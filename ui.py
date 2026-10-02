"""Rounded, anti-aliased UI pieces for Tk: pill buttons, rounded containers, toggle switches.

Tk widgets are square and the Tk canvas doesn't anti-alias on Windows, so rounded shapes are
drawn with Pillow. Rounded rectangles are assembled from four small cached corner tiles plus
solid fills, which is cheap enough to redraw on every resize step.
"""

import tkinter as tk
import weakref

from PIL import Image, ImageDraw, ImageTk

import colors

_SS = 4  # supersampling factor for corner tiles
_corner_cache = {}
_image_cache = {}
_pills = weakref.WeakSet()
_boxes = weakref.WeakSet()


def refresh_all():
    """Re-render rounded buttons and re-fit rounded boxes after the fonts change size."""
    for pill in list(_pills):
        if pill.winfo_exists():
            pill._state_key = None
            pill._render()
    for box in list(_boxes):
        if box.winfo_exists() and not box.stretch:
            box.fit()


def _corner(r, fill, bg, border, bw):
    key = (r, fill, bg, border, bw)
    tile = _corner_cache.get(key)
    if tile is None:
        big = Image.new("RGB", (r * _SS, r * _SS), bg)
        d = ImageDraw.Draw(big)
        box = (0, 0, 2 * r * _SS - 1, 2 * r * _SS - 1)
        if border:
            d.ellipse(box, fill=border)
            inset = bw * _SS
            d.ellipse((inset, inset, box[2] - inset, box[3] - inset), fill=fill)
        else:
            d.ellipse(box, fill=fill)
        tile = big.resize((r, r), Image.LANCZOS)
        _corner_cache[key] = tile
    return tile


def rounded_image(w, h, r, fill, bg, border=None, bw=1):
    """PIL image of a rounded rectangle (corners outside the shape are painted `bg`)."""
    w, h = max(2, int(w)), max(2, int(h))
    r = max(1, min(int(r), w // 2, h // 2))
    img = Image.new("RGB", (w, h), fill)
    if border:
        ImageDraw.Draw(img).rectangle((0, 0, w - 1, h - 1), outline=border, width=bw)
    tl = _corner(r, fill, bg, border, bw)
    img.paste(tl, (0, 0))
    img.paste(tl.transpose(Image.FLIP_LEFT_RIGHT), (w - r, 0))
    img.paste(tl.transpose(Image.FLIP_TOP_BOTTOM), (0, h - r))
    img.paste(tl.transpose(Image.ROTATE_180), (w - r, h - r))
    return img


def rounded_photo(master, w, h, r, fill, bg, border=None, bw=1):
    key = (int(w), int(h), int(r), fill, bg, border, bw)
    photo = _image_cache.get(key)
    if photo is None:
        if len(_image_cache) > 400:
            _image_cache.clear()
        photo = ImageTk.PhotoImage(rounded_image(w, h, r, fill, bg, border, bw), master=master)
        _image_cache[key] = photo
    return photo


def round_corners(img, r, bg):
    """Return img with rounded corners flattened onto bg (for album art)."""
    w, h = img.size
    mask = Image.new("L", (w * _SS, h * _SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * _SS - 1, h * _SS - 1), r * _SS, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS)
    out = Image.new("RGB", (w, h), bg)
    out.paste(img, (0, 0), mask)
    return out


def switch_photo(master, on, accent, off_color, bg, scale=1.0):
    """iOS-style toggle switch image."""
    w, h = int(32 * scale), int(18 * scale)
    key = ("switch", on, accent, off_color, bg, w, h)
    photo = _image_cache.get(key)
    if photo is None:
        big = Image.new("RGB", (w * _SS, h * _SS), bg)
        d = ImageDraw.Draw(big)
        d.rounded_rectangle((0, 0, w * _SS - 1, h * _SS - 1), h * _SS // 2,
                            fill=accent if on else off_color)
        pad = 2 * _SS
        knob = h * _SS - 2 * pad
        x = w * _SS - pad - knob if on else pad
        d.ellipse((x, pad, x + knob, pad + knob), fill="#ffffff")
        photo = ImageTk.PhotoImage(big.resize((w, h), Image.LANCZOS), master=master)
        _image_cache[key] = photo
    return photo


class PillButton(tk.Label):
    """Rounded button: a Label showing a rounded-rectangle image with the text on top."""

    def __init__(self, master, app, text, command, bg, fg, hover, font, padx, pady,
                 parent_bg, border=None, radius=None, min_width=0, square=False):
        self._font_obj = app.fonts[font] if isinstance(font, str) else font
        super().__init__(master, text=text, compound="center", bg=parent_bg, fg=fg,
                         font=self._font_obj, bd=0, padx=0, pady=0, cursor="hand2",
                         highlightthickness=0)
        self.app = app
        self._text = text
        self._bg, self._hover, self._border = bg, hover, border
        self._font, self._padx, self._pady = font, padx, pady
        self._parent_bg = parent_bg
        self._radius, self._min_width, self._square = radius, min_width, square
        self._command = command
        self._state_key = None
        _pills.add(self)
        self._render()
        self.bind("<Button-1>", lambda e: self._command() if self._command else None)
        self.bind("<Enter>", lambda e: self.configure(image=self._img_hover))
        self.bind("<Leave>", lambda e: self.configure(image=self._img))

    def _render(self):
        key = (self._text, self._bg, self._hover, self._border, self._font)
        if key == self._state_key:
            return
        self._state_key = key
        app = self.app
        f = self._font_obj
        s = app.scale
        w = max(self._min_width, f.measure(self._text) + 2 * int(self._padx * s))
        h = f.metrics("linespace") + 2 * int(self._pady * s)
        if self._square:  # circle / square button
            w = h = max(w, h)
        r = self._radius if self._radius is not None else min(h // 2, int(9 * s))
        self._img = rounded_photo(app.root, w, h, r, self._bg, self._parent_bg, self._border)
        self._img_hover = rounded_photo(app.root, w, h, r, self._hover, self._parent_bg,
                                        self._border)
        self.configure(image=self._img, text=self._text)

    def set_text(self, text):
        self._text = text
        self._render()

    def set_colors(self, bg=None, fg=None, hover=None, border=False):
        if bg is not None:
            self._bg = bg
            self._hover = hover or colors.mix(bg, "#000000", 0.08)
        if border is not False:
            self._border = border
        if fg is not None:
            self.configure(fg=fg)
        self._render()

    def set_command(self, command):
        self._command = command


class RoundedFrame(tk.Canvas):
    """Container with a rounded, optionally bordered background. Put children in .inner.

    stretch=True: .inner fills the whole box (box is sized by its parent's layout).
    stretch=False: box width follows the parent; height follows .inner's content (call fit()).
    """

    def __init__(self, master, fill, bg, radius=10, border=None, pad=None, stretch=False,
                 scale=1.0):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, width=10, height=10)
        self.fill, self.parent_bg, self.border = fill, bg, border
        self.radius = int(radius * scale)
        self.pad = int(pad * scale) if pad is not None else max(3, self.radius // 2)
        self.stretch = stretch
        self.inner = tk.Frame(self, bg=fill)
        self._img_item = self.create_image(0, 0, anchor="nw")
        self._win = self.create_window(self.pad, self.pad, anchor="nw", window=self.inner)
        self._photo = None
        self._size = None
        self.bind("<Configure>", self._on_configure)
        _boxes.add(self)
        if not stretch:
            self.after_idle(self.fit)

    def set_border(self, border):
        self.border = border
        self._size = None
        self._redraw(self.winfo_width(), self.winfo_height())

    def fit(self):
        """Size the box to its content's requested height (and width, as a minimum)."""
        if not self.winfo_exists():
            return
        self.inner.update_idletasks()
        self.configure(height=self.inner.winfo_reqheight() + 2 * self.pad,
                       width=self.inner.winfo_reqwidth() + 2 * self.pad)

    def _on_configure(self, e):
        self._redraw(e.width, e.height)

    def _redraw(self, w, h):
        if w < 4 or h < 4 or (w, h) == self._size:
            return
        self._size = (w, h)
        self._photo = rounded_photo(self, w, h, self.radius, self.fill, self.parent_bg,
                                    self.border)
        self.itemconfigure(self._img_item, image=self._photo)
        inner_w = max(1, w - 2 * self.pad)
        if self.stretch:
            self.itemconfigure(self._win, width=inner_w, height=max(1, h - 2 * self.pad))
        else:
            self.itemconfigure(self._win, width=inner_w)
