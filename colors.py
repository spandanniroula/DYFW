"""Color helpers, custom-theme derivation and a color-wheel picker dialog."""

import colorsys
import math
import re
import tkinter as tk

import platform_utils as pu

_HEX_RE = re.compile(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})")
_NUMS_RE = re.compile(r"(\d{1,3})")


# ---------------------------------------------------------------- conversions

def parse_color(text):
    """Accept '#ff8800', 'ff8800', '#f80', 'rgb(255,136,0)', '255, 136, 0'. Returns '#rrggbb' or None."""
    s = text.strip()
    m = _HEX_RE.fullmatch(s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h.lower()
    nums = _NUMS_RE.findall(s)
    if len(nums) == 3 and re.fullmatch(r"(rgb)?\s*\(?\s*\d{1,3}\s*[, ]\s*\d{1,3}\s*[, ]\s*\d{1,3}\s*\)?",
                                       s, re.I):
        rgb = [int(n) for n in nums]
        if all(0 <= v <= 255 for v in rgb):
            return to_hex(rgb)
    return None


def to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(round(v)))):02x}" for v in rgb)


def mix(a, b, amount):
    """Blend color a toward b by amount (0..1)."""
    ra, rb = to_rgb(a), to_rgb(b)
    return to_hex(x + (y - x) * amount for x, y in zip(ra, rb))


def luminance(hex_color):
    def chan(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(v) for v in to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_dark(hex_color):
    return luminance(hex_color) < 0.22


def readable_on(hex_color):
    return "#f2f2f2" if is_dark(hex_color) else "#2e2e2e"


# ---------------------------------------------------------------- custom theme

CUSTOM_KEYS = [("bg", "Note body"), ("header", "Header bar"), ("dock", "Bottom bar"),
               ("popup", "Pop-ups"), ("accent", "Accent"), ("text", "Text")]
AUTO_KEYS = {"dock", "popup", "text"}  # may be None = follow the other colors


def add_surface_colors(theme):
    """Fill in bottom-bar and pop-up colors (defaulting to the note body) for any theme."""
    for surface in ("dock", "popup"):
        base = theme.get(surface) or theme["bg"]
        theme[surface] = base
        if base == theme["bg"]:
            theme[surface + "_text"] = theme["text"]
            theme[surface + "_muted"] = theme["muted"]
        else:
            txt = readable_on(base)
            theme[surface + "_text"] = txt
            theme[surface + "_muted"] = mix(txt, base, 0.4)
    theme.setdefault("header_text", theme["text"])
    return theme


def derive_theme(custom):
    """Build a full theme from the user's base colors (None values = automatic)."""
    bg = custom["bg"]
    header = custom["header"]
    accent = custom["accent"]
    dark = is_dark(bg)
    text = custom.get("text") or readable_on(bg)
    white, black = "#ffffff", "#000000"
    return add_surface_colors(dict(
        dock=custom.get("dock"),
        popup=custom.get("popup"),
        bg=bg,
        header=header,
        active=mix(header, white if is_dark(header) else black, 0.14),
        text=text,
        header_text=readable_on(header),
        muted=mix(text, bg, 0.45),
        done=mix(text, bg, 0.62),
        accent=accent,
        entry=mix(bg, white, 0.06 if dark else 0.55),
        border=mix(header, text, 0.2),
        hover=mix(bg, header, 0.35),
        danger="#ef5350" if dark else "#c0392b",
        overdue="#ff7043" if dark else "#d84315",
    ))


# ---------------------------------------------------------------- picker dialog

class ColorPicker(tk.Toplevel):
    """HSV color wheel + brightness slider + hex/RGB entry. Calls on_pick('#rrggbb' or None)."""

    def __init__(self, master, initial, on_pick, theme, fonts, scale=1.0, title="Pick a color",
                 allow_auto=False):
        super().__init__(master)
        self.on_pick = on_pick
        self.t = theme
        self.fonts = fonts
        self.initial = initial
        self.size = int(200 * scale)
        self.radius = self.size // 2 - 2
        self.h, self.s, self.v = colorsys.rgb_to_hsv(*(c / 255 for c in to_rgb(initial)))
        self._typing = False

        t = theme
        self.title(title)
        self.configure(bg=t["bg"])
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

        body = tk.Frame(self, bg=t["bg"], padx=14, pady=12)
        body.pack(fill="both", expand=True)

        top = tk.Frame(body, bg=t["bg"])
        top.pack()
        self.wheel = tk.Canvas(top, width=self.size, height=self.size, bg=t["bg"],
                               highlightthickness=0, cursor="crosshair")
        self.wheel.pack(side="left")
        self.slider = tk.Canvas(top, width=int(22 * scale), height=self.size, bg=t["bg"],
                                highlightthickness=0, cursor="sb_v_double_arrow")
        self.slider.pack(side="left", padx=(10, 0))

        self._wheel_base = self._make_wheel()
        self._wheel_img = None
        self.wheel.bind("<Button-1>", self._wheel_drag)
        self.wheel.bind("<B1-Motion>", self._wheel_drag)
        self.slider.bind("<Button-1>", self._slider_drag)
        self.slider.bind("<B1-Motion>", self._slider_drag)

        mid = tk.Frame(body, bg=t["bg"])
        mid.pack(fill="x", pady=(12, 0))
        self.preview_old = tk.Frame(mid, bg=initial, width=int(28 * scale), height=int(28 * scale),
                                    highlightthickness=1, highlightbackground=t["border"])
        self.preview_old.pack(side="left")
        self.preview_new = tk.Frame(mid, bg=initial, width=int(28 * scale), height=int(28 * scale),
                                    highlightthickness=1, highlightbackground=t["border"])
        self.preview_new.pack(side="left", padx=(0, 10))

        tk.Label(mid, text="Hex", bg=t["bg"], fg=t["muted"], font=fonts["small"]).pack(side="left")
        self.hex_var = tk.StringVar(value=initial)
        self.hex_entry = self._entry(mid, self.hex_var, 9)
        self.hex_entry.pack(side="left", padx=(4, 8), ipady=2)
        self.hex_var.trace_add("write", lambda *a: self._typed(self.hex_var.get()))

        rgb_row = tk.Frame(body, bg=t["bg"])
        rgb_row.pack(fill="x", pady=(8, 0))
        self.rgb_vars = []
        for ch in "RGB":
            tk.Label(rgb_row, text=ch, bg=t["bg"], fg=t["muted"], font=fonts["small"]).pack(side="left")
            var = tk.StringVar()
            self._entry(rgb_row, var, 4).pack(side="left", padx=(3, 8), ipady=2)
            var.trace_add("write", lambda *a: self._typed_rgb())
            self.rgb_vars.append(var)
        self.msg = tk.Label(body, text="Tip: paste a code like #ff8800 or 255, 136, 0",
                            bg=t["bg"], fg=t["muted"], font=fonts["small"], anchor="w")
        self.msg.pack(fill="x", pady=(6, 0))

        btns = tk.Frame(body, bg=t["bg"])
        btns.pack(fill="x", pady=(12, 0))
        self._button(btns, "Use color", self.ok, t["accent"], readable_on(t["accent"])).pack(side="right")
        self._button(btns, "Cancel", self.cancel, t["entry"], t["text"]).pack(side="right", padx=6)
        if allow_auto:
            self._button(btns, "Auto", self.auto, t["entry"], t["text"]).pack(side="left")
        self.bind("<Return>", lambda e: self.ok())

        self._redraw(update_entries=True)
        self.update_idletasks()
        x = master.winfo_rootx() - self.winfo_reqwidth() - 10
        if x < 0:
            x = master.winfo_rootx() + master.winfo_width() + 10
        self.geometry(f"+{x}+{max(0, master.winfo_rooty())}")
        self.update()
        pu.hide_from_taskbar(self)
        self.lift()
        self.focus_force()
        self.hex_entry.focus_set()
        self.hex_entry.select_range(0, "end")

    # ---- widgets

    def _entry(self, parent, var, width):
        t = self.t
        e = tk.Entry(parent, textvariable=var, width=width, bg=t["entry"], fg=t["text"],
                     relief="flat", font=self.fonts["ui"], highlightthickness=1,
                     highlightbackground=t["border"], highlightcolor=t["accent"],
                     insertbackground=t["text"])
        e.bind("<Button-1>", lambda ev: (self.focus_force(), ev.widget.focus_set()))
        return e

    def _button(self, parent, text, cmd, bg, fg):
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=self.fonts["ui_bold"], padx=12,
                     pady=5, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    # ---- drawing

    def _make_wheel(self):
        from PIL import Image
        size, r = self.size, self.radius
        c = size / 2
        img = Image.new("RGB", (size, size))
        px = []
        for y in range(size):
            dy = c - y
            for x in range(size):
                dx = x - c
                dist = math.hypot(dx, dy)
                if dist > r:
                    px.append((0, 0, 0))
                    continue
                hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
                rr, gg, bb = colorsys.hsv_to_rgb(hue, min(1.0, dist / r), 1.0)
                px.append((int(rr * 255), int(gg * 255), int(bb * 255)))
        img.putdata(px)
        mask = Image.new("L", (size, size), 0)
        from PIL import ImageDraw
        ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
        self._mask = mask
        return img

    def _redraw(self, update_entries=False):
        from PIL import Image, ImageTk
        t = self.t
        size, r = self.size, self.radius
        c = size / 2
        shaded = self._wheel_base.point(lambda p: int(p * self.v))
        canvas_bg = Image.new("RGB", (size, size), to_rgb(t["bg"]))
        canvas_bg.paste(shaded, (0, 0), self._mask)
        self._wheel_img = ImageTk.PhotoImage(canvas_bg, master=self)
        self.wheel.delete("all")
        self.wheel.create_image(0, 0, anchor="nw", image=self._wheel_img)
        ang = self.h * 2 * math.pi
        mx, my = c + math.cos(ang) * self.s * r, c - math.sin(ang) * self.s * r
        ring = "#000000" if self.v > 0.5 else "#ffffff"
        self.wheel.create_oval(mx - 7, my - 7, mx + 7, my + 7, outline=ring, width=2)
        self.wheel.create_oval(mx - 5, my - 5, mx + 5, my + 5, outline="#ffffff" if ring == "#000000"
                               else "#000000", width=1)

        # brightness slider: full color at top, black at bottom
        self.slider.delete("all")
        w = int(self.slider.cget("width"))
        steps = 48
        for i in range(steps):
            v = 1 - i / (steps - 1)
            rgb = colorsys.hsv_to_rgb(self.h, self.s, v)
            y0 = i * size / steps
            self.slider.create_rectangle(0, y0, w, y0 + size / steps + 1, outline="",
                                         fill=to_hex(x * 255 for x in rgb))
        y = (1 - self.v) * (size - 1)
        self.slider.create_rectangle(0, y - 3, w - 1, y + 3, outline="#ffffff", width=2)
        self.slider.create_rectangle(1, y - 2, w - 2, y + 2, outline="#000000", width=1)

        color = self.color
        self.preview_new.configure(bg=color)
        if update_entries:
            self._typing = True
            self.hex_var.set(color)
            for var, val in zip(self.rgb_vars, to_rgb(color)):
                var.set(str(val))
            self._typing = False

    @property
    def color(self):
        return to_hex(x * 255 for x in colorsys.hsv_to_rgb(self.h, self.s, self.v))

    def _set_from_hex(self, hex_color):
        self.h, self.s, self.v = colorsys.rgb_to_hsv(*(c / 255 for c in to_rgb(hex_color)))

    # ---- input

    def _wheel_drag(self, e):
        c = self.size / 2
        dx, dy = e.x - c, c - e.y
        self.h = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
        self.s = min(1.0, math.hypot(dx, dy) / self.radius)
        if self.v < 0.05:
            self.v = 1.0  # picking a hue on a black wheel would do nothing
        self._redraw(update_entries=True)

    def _slider_drag(self, e):
        self.v = min(1.0, max(0.0, 1 - e.y / (self.size - 1)))
        self._redraw(update_entries=True)

    def _typed(self, text):
        if self._typing:
            return
        color = parse_color(text)
        if color:
            self._set_from_hex(color)
            self._redraw()
            self._typing = True
            for var, val in zip(self.rgb_vars, to_rgb(color)):
                var.set(str(val))
            self._typing = False
            self.msg.configure(text="", fg=self.t["muted"])
        elif len(text.strip()) >= 6:
            self.msg.configure(text="Not a color code yet — try #ff8800", fg=self.t["danger"])

    def _typed_rgb(self):
        if self._typing:
            return
        try:
            rgb = [int(v.get()) for v in self.rgb_vars]
        except ValueError:
            return
        if all(0 <= x <= 255 for x in rgb):
            color = to_hex(rgb)
            self._set_from_hex(color)
            self._redraw()
            self._typing = True
            self.hex_var.set(color)
            self._typing = False

    # ---- result

    def ok(self):
        color = parse_color(self.hex_var.get()) or self.color
        self.destroy()
        self.on_pick(color)

    def auto(self):
        self.destroy()
        self.on_pick(None)

    def cancel(self):
        self.destroy()
