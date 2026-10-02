"""DYFW (Do Your Fucken Work): an always-on-top sticky note with tasks, reminders,
calendar feeds, a focus timer and music controls."""

import io
import json
import math
import os
import queue
import threading
import uuid
import webbrowser
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime, time, timedelta

import bubble
import calc
import colors
import ical_feeds
from listview import CanvasList
import media
import platform_utils as pu
import ui
from timeparse import countdown, extract_when, format_due, next_occurrence

APP_NAME = "DYFW"
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
DATA_DIR = os.path.join(_APPDATA, APP_NAME)
DATA_FILE = os.path.join(DATA_DIR, "data.json")
OLD_DATA_FILE = os.path.join(_APPDATA, "StickyNote", "data.json")  # pre-rename location

THEMES = {
    "Lemon": dict(bg="#fff8b8", header="#f9d949", active="#f2c418", text="#3b3a30",
                  muted="#8c8a72", done="#b3b096", accent="#a86400", entry="#fffdea",
                  border="#dcc24a", hover="#fff09a", danger="#c0392b", overdue="#d84315"),
    "Blush": dict(bg="#ffe6ee", header="#f8a5c2", active="#f48fb1", text="#3d2b33",
                  muted="#9a7f89", done="#c7aeb8", accent="#ad1457", entry="#fff4f8",
                  border="#eb9ab7", hover="#ffd3e1", danger="#c0392b", overdue="#d84315"),
    "Sky": dict(bg="#e3f2fd", header="#90caf9", active="#64b5f6", text="#1f2d3a",
                muted="#6f8597", done="#a6b8c7", accent="#1565c0", entry="#f3f9ff",
                border="#82b9e8", hover="#cfe6fa", danger="#c0392b", overdue="#d84315"),
    "Mint": dict(bg="#e6f6ea", header="#a5d6a7", active="#81c784", text="#22332a",
                 muted="#6e8a76", done="#a8bfae", accent="#2e7d32", entry="#f4fbf5",
                 border="#94c896", hover="#d3eed8", danger="#c0392b", overdue="#d84315"),
    "Lavender": dict(bg="#efe7fb", header="#c5b3f0", active="#b39ddb", text="#2e2640",
                     muted="#857a9c", done="#b7aec9", accent="#5e35b1", entry="#f8f4fe",
                     border="#b6a3e3", hover="#e1d6f7", danger="#c0392b", overdue="#d84315"),
    "Night": dict(bg="#25272c", header="#33363d", active="#454a54", text="#e8e8e8",
                  muted="#8e939c", done="#5f636b", accent="#ffca28", entry="#2f3237",
                  border="#41454e", hover="#30333a", danger="#ef5350", overdue="#ff7043"),
}
for _th in THEMES.values():
    colors.add_surface_colors(_th)

FONT_CHOICES = [("Segoe UI Variable Text", "Clean"), ("Bahnschrift", "Modern"),
                ("Segoe Print", "Handwritten"), ("Ink Free", "Marker"),
                ("Cascadia Code", "Mono")]
TEXT_SIZES = [("small", "Small"), ("normal", "Normal"), ("large", "Large")]
TEXT_BASE = {"small": 9, "normal": 10, "large": 12}
REPEATS = [("none", "Once"), ("daily", "Daily"), ("weekdays", "Weekdays"), ("weekly", "Weekly")]
LEADS = [(0, "at due time"), (15, "15 min before"), (60, "1 hour before"),
         (180, "3 hours before"), (1440, "1 day before"), (2880, "2 days before")]
DUE_SOON = [(1, "1 day"), (2, "2 days"), (3, "3 days"), (7, "1 week")]
DEFAULT_MODES = [  # id, name, focus, break, long break, long break every N sessions
    ("pomodoro", "Pomodoro", 25, 5, 15, 4),
    ("deep", "Deep work", 50, 10, 20, 3),
    ("study", "Study", 45, 15, 30, 3),
    ("sprint", "Quick sprint", 15, 3, 10, 4),
]
BADGE_COLORS = {"late": ("#d84315", "white"), "urgent": ("#e53935", "white"),
                "soon": ("#fb8c00", "white")}
GRID_CELLS = [  # key, title, important, due soon
    ("imp_soon", "Important · due soon", True, True),
    ("imp_later", "Important · has time", True, False),
    ("soon", "Less important · due soon", False, True),
    ("later", "Less important · has time", False, False),
]
ALERT_FLASH = ("#ff5252", "#ffd600")
GREEN, GREEN_HOVER = "#43a047", "#388e3c"
BUBBLE_KEY = "#010203"  # transparent color used to make the bubble round
BUBBLE_CLICK_DELAY = 0.5  # seconds the new bubble ignores clicks after minimizing
BUBBLE_NEAR_HOURS = 6  # bubble turns red for anything overdue or due within this many hours
BUBBLE_DISC = 54    # bubble diameter
BUBBLE_SHADOW = 9   # room around it for the drop shadow
BUBBLE_MARGIN = 6  # gap between the default bubble spot and the screen's top-right corner
TUCK_PEEK = 10  # px of the note left showing when tucked into a screen edge
EDGE_SNAP = 24  # dragging within this many px of a screen edge snaps the note to it
TASK_DEFAULT_TIME = time(23, 59)  # "essay due friday" = end of Friday
REMINDER_DEFAULT_TIME = time(9, 0)

CHECK_MS = 5000
TOPMOST_MS = 3000
REFRESH_MS = 60 * 1000
SYNC_MS = 30 * 60 * 1000
FEED_HORIZON_DAYS = 14
MIN_W, MIN_H = 250, 220
# Text shrinks one or two steps when the note is made narrow; your chosen size is the max.
FONT_STEPS = [(330, 0), (285, -1), (0, -2)]  # (min window width, size offset)


class Icon:
    """Segoe Fluent Icons / MDL2 Assets code points."""
    SETTINGS = ""
    CLOSE = ""
    MINIMIZE = ""
    REMOVE = ""
    ADD = ""
    EDIT = ""
    BOX = ""
    BOX_CHECKED = ""
    SYNC = ""
    OPEN = ""
    STAR = ""
    STAR_FILLED = ""
    PREV = ""
    NEXT = ""
    PLAY = ""
    PAUSE = ""
    STOP = ""
    MUSIC = ""
    TODAY = ""
    TASKS = ""
    BELL = ""
    FOCUS = ""
    GRID = ""
    CHECK = "\uE73E"
    NOTES = "\uE70B"
    COPY = "\uE8C8"


TABS = [("today", "Today", Icon.TODAY), ("tasks", "Tasks", Icon.TASKS),
        ("reminders", "Reminders", Icon.BELL), ("focus", "Focus", Icon.FOCUS),
        ("grid", "Grid", Icon.GRID), ("notes", "Notepad", Icon.NOTES),
        ("music", "Music", Icon.MUSIC)]
AUTOHIDE_DELAYS = [(2, "2 sec"), (4, "4 sec"), (8, "8 sec")]


# ---------------------------------------------------------------- persistence

def load_data():
    path = DATA_FILE if os.path.exists(DATA_FILE) else OLD_DATA_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_data(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)


def iso(dt):
    return dt.isoformat(timespec="minutes")


def parse_iso(s):
    return datetime.fromisoformat(s) if s else None


def mmss(secs):
    secs = max(0, int(round(secs)))
    return f"{secs // 60}:{secs % 60:02d}"


def hours_minutes(mins):
    h, m = divmod(int(mins), 60)
    return f"{h}h {m}m" if h else f"{m}m"


# ---------------------------------------------------------------- widgets

class ScrollList(tk.Frame):
    """Vertically scrollable container; put rows into .inner."""

    def __init__(self, master, bg):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(fill="both", expand=True)
        self.inner.bind("<Configure>", self._update_region)
        self.canvas.bind("<Configure>", self._on_resize)
        self.on_width_change = None
        self.width = 0

    def _update_region(self, _e=None):
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(),
                                            max(self.inner.winfo_reqheight(),
                                                self.canvas.winfo_height())))

    def _on_resize(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self._update_region()
        if abs(e.width - self.width) > 4:
            self.width = e.width
            if self.on_width_change:
                self.on_width_change()

    def scroll(self, units):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(units, "units")

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()


# ---------------------------------------------------------------- app

class StickyApp:
    def __init__(self, root):
        self.root = root
        self.data = load_data()
        self._migrate()
        self.queue = queue.Queue()
        self.alerts = {}  # alert key -> Toplevel
        self.hidden = False
        self.syncing = set()
        self.feed_cache = {}
        self.now_playing = None
        self._art_cache = {}
        self._theme_key = None
        self._theme = None
        self.picker = None
        self._pending_click = None
        self._editing = False
        self._drag = None
        self._missed = 0
        self._np_after = None
        self._ring_after = None
        self._resize_pending = None
        self._fit_after = None
        self._notes_save_after = None
        self._ribbons_hidden = False
        self._ribbon_offsets = (0, 0)
        self._animating = False
        self._tucked = None        # "left"/"right" while slid into a screen edge
        self._tuck_from_x = None   # where the note sits when pulled back out
        self._last_key = datetime.now() - timedelta(minutes=1)
        self._last_hover = datetime.now()
        self._np_blur = None
        self._dwm = False
        self._font_objs = {}
        self.show_signal = pu.ShowSignal()

        self.scale = root.winfo_fpixels("1i") / 96.0
        self.families = set(tkfont.families(root))
        self.ui_family = pu.pick_font(self.families, ["Segoe UI Variable Text", "Segoe UI"])
        self.display_family = pu.pick_font(self.families,
                                           ["Segoe UI Variable Display", self.ui_family])
        self.icon_family = pu.pick_font(self.families, ["Segoe Fluent Icons", "Segoe MDL2 Assets"])
        self.mono_family = pu.pick_font(self.families, ["Cascadia Mono", "Cascadia Code", "Consolas"])
        self._font_level = self._font_level_for(self.data.get("width", int(340 * self.scale)))
        self.fonts = {}
        self._make_fonts()

        root.title(APP_NAME)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        self.app_icon = pu.make_icon_photo(root)
        if self.app_icon:
            root.iconphoto(True, self.app_icon)

        self.build_ui()
        self.apply_opacity()
        root.update()  # must be mapped first, or Windows drops the saved position
        pu.hide_from_taskbar(root)
        self._apply_window_style()

        try:
            self.tray = pu.Tray(lambda cmd: self.queue.put(("tray", cmd)), pu.is_startup_enabled)
        except Exception:
            self.tray = None

        self.media = media.MediaController(lambda info: self.queue.put(("media", info)))
        self._apply_music_source()

        root.bind_all("<MouseWheel>", self._on_wheel)
        root.bind_all("<Control-n>", self._shortcut_add_task)
        root.bind_all("<Key>", self._note_keypress, add="+")
        root.after(200, self._poll_queue)
        root.after(500, self.check_reminders)
        root.after(1000, self._focus_tick)
        root.after(TOPMOST_MS, self._keep_on_top)
        root.after(REFRESH_MS, self._periodic_refresh)
        root.after(1500, self._auto_sync)
        root.after(300, self._hover_poll)
        root.bind("<Configure>", self._on_root_configure)

    # ---- state

    def _migrate(self):
        d = self.data
        d.setdefault("tasks", [])
        d.setdefault("reminders", [])
        d.setdefault("feeds", [])
        d.setdefault("panel", "today")
        d.setdefault("collapsed", False)
        d.setdefault("bubble", False)
        f = d.setdefault("focus", {})
        for k, v in (("mode", None), ("ends", None), ("paused", None), ("cycle", 0), ("log", {}),
                     ("minutes", {}), ("length", None)):
            f.setdefault(k, v)
        s = d.setdefault("settings", {})
        for k, v in (("theme", "Lemon"), ("font", "Segoe UI Variable Text"), ("opacity", 1.0),
                     ("text_size", "normal"), ("due_soon_days", 2), ("music", "auto"),
                     ("dock_art", True), ("tabs", [k for k, _l, _i in TABS]),
                     ("autohide", False), ("autohide_delay", 4), ("notes_mono", False),
                     ("notes_smart", True), ("edge_tuck", True)):
            s.setdefault(k, v)
        if "focus_modes" not in s:
            modes = [dict(id=i, name=n, focus=fm, brk=bm, long=lm, every=ev)
                     for i, n, fm, bm, lm, ev in DEFAULT_MODES]
            # keep whatever lengths the user had picked before modes existed
            modes[0].update(focus=s.get("focus_min", 25), brk=s.get("break_min", 5),
                            long=s.get("long_break_min", 15), every=s.get("long_every", 4))
            s["focus_modes"] = modes
            s["focus_mode"] = "pomodoro"
        if not s.get("tabs_notes_added"):  # new tab for people upgrading
            s["tabs_notes_added"] = True
            if "notes" not in s["tabs"]:
                s["tabs"] = [k for k, _l, _i in TABS if k in s["tabs"] or k == "notes"]
        notes = d.setdefault("notes", {})
        if not notes.get("pages"):
            notes["pages"] = [{"id": uuid.uuid4().hex, "title": "Note 1", "text": ""}]
        if notes.get("current") not in {pg["id"] for pg in notes["pages"]}:
            notes["current"] = notes["pages"][0]["id"]
        if s.get("theme") == "Custom" and not s.get("custom_theme"):
            s["theme"] = "Lemon"
        now = datetime.now()
        for t in d["tasks"]:
            t.setdefault("id", uuid.uuid4().hex)
            t.setdefault("important", False)
            t.setdefault("deadline", None)
            t.setdefault("done", False)
            if "alert" not in t:
                dl = parse_iso(t["deadline"])
                t["alert"] = bool(dl and dl.time() != TASK_DEFAULT_TIME)
                t["alert_at"] = t["deadline"] if t["alert"] else None
                t["fired"] = bool(dl and dl <= now)
        for r in d["reminders"]:
            r.setdefault("done", False)
            r.setdefault("repeat", "none")
            r.setdefault("fired", False)
            r.setdefault("id", uuid.uuid4().hex)
        for feed in d["feeds"]:
            feed.setdefault("homework_only", "instructure" in feed.get("url", ""))
        self._sort_tasks()

    @property
    def t(self):
        custom = self.settings.get("custom_theme")
        if self.settings["theme"] == "Custom" and custom:
            key = tuple(sorted(custom.items()))
            if key != self._theme_key:
                self._theme_key, self._theme = key, colors.derive_theme(custom)
            return self._theme
        return THEMES.get(self.settings["theme"], THEMES["Lemon"])

    @property
    def settings(self):
        return self.data["settings"]

    def save(self):
        try:
            save_data(self.data)
        except OSError:
            pass

    def _make_fonts(self):
        note_family = self.settings["font"]
        if note_family not in self.families:
            note_family = self.ui_family
        b = TEXT_BASE.get(self.settings["text_size"], 10) + self._font_level
        ui, disp, ic = self.ui_family, self.display_family, self.icon_family
        specs = {
            "body": (note_family, b, "normal", 0),
            "done": (note_family, b, "normal", 1),
            "alert": (note_family, b + 6, "bold", 0),
            "ui": (ui, b - 1, "normal", 0),
            "ui_bold": (ui, b - 1, "bold", 0),
            "title": (disp, b + 5, "bold", 0),
            "subtitle": (disp, b + 1, "bold", 0),
            "small": (ui, b - 2, "normal", 0),
            "small_bold": (ui, b - 2, "bold", 0),
            "badge": (ui, max(7, b - 3), "bold", 0),
            "section": (ui, b - 2, "bold", 0),
            "timer": (ui, b, "bold", 0),
            "big_timer": (disp, b * 3 + 4, "bold", 0),
            "icon": (ic, b - 1, "normal", 0),
            "icon_small": (ic, b - 2, "normal", 0),
            "icon_box": (ic, b + 1, "normal", 0),
            "icon_tab": (ic, min(b, 11), "normal", 0),
            "icon_big": (ic, b + 10, "normal", 0),
            "mono": (self.mono_family, b, "normal", 0),
            "bubble_num": (disp, b + 5, "normal", 0),
            "bubble_cap": (ui, max(6, b - 3), "normal", 0),
        }
        for name, (fam, size, weight, strike) in specs.items():
            if name in self.fonts:
                self.fonts[name].configure(family=fam, size=size, weight=weight, overstrike=strike)
            else:
                self.fonts[name] = tkfont.Font(family=fam, size=size, weight=weight,
                                               overstrike=strike)
        self.row_pad = 3 if b >= 12 else 2

    # ---- small widget helpers

    def button(self, parent, text, command, bg=None, fg=None, hover=None, font="ui",
               padx=8, pady=3, parent_bg=None, border=None, radius=None, square=False):
        t = self.t
        bg = bg or t["header"]
        parent_bg = parent_bg or parent.cget("bg")
        if fg is None:
            fg = t["header_text"] if bg in (t["header"], t["active"]) else t["text"]
        if hover is None:
            hover = t["hover"] if bg == parent_bg else colors.mix(
                bg, "#ffffff" if colors.is_dark(bg) else "#000000", 0.08)
        return ui.PillButton(parent, self, text, command, bg, fg, hover, font, padx, pady,
                             parent_bg, border, radius, square=square)

    def _font_obj(self, spec):
        if spec not in self._font_objs:
            self._font_objs[spec] = tkfont.Font(root=self.root, font=spec)
        return self._font_objs[spec]

    def icon_button(self, parent, glyph, command, bg=None, fg=None, hover_fg=None, small=False,
                    font=None):
        t = self.t
        bg = bg or t["bg"]
        fg = fg or t["muted"]
        btn = tk.Label(parent, text=glyph, bg=bg, fg=fg, cursor="hand2",
                       font=self.fonts[font or ("icon_small" if small else "icon")], padx=4, pady=3)
        btn.base_bg = bg
        btn.base_fg = fg
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(fg=hover_fg or t["text"]))
        btn.bind("<Leave>", lambda e: btn.configure(fg=btn.base_fg))
        return btn

    def entry(self, parent, placeholder=None, width=None, rounded=False):
        """Text box. rounded=True wraps it in a rounded border; pack/grid `e.outer` then."""
        t = self.t
        host = parent
        if rounded:
            box = ui.RoundedFrame(parent, fill=t["entry"], bg=parent.cget("bg"), radius=8,
                                  border=t["border"], pad=3, scale=self.scale)
            host = box.inner
        e = tk.Entry(host, bg=t["entry"], fg=t["text"], relief="flat", font=self.fonts["body"],
                     bd=0, highlightthickness=0 if rounded else 1,
                     highlightbackground=t["border"], highlightcolor=t["accent"],
                     insertbackground=t["text"])
        if width:
            e.configure(width=width)
        if rounded:
            e.pack(fill="x", padx=int(5 * self.scale), pady=int(3 * self.scale))
            e.outer = box
            e.bind("<FocusIn>", lambda ev: box.set_border(t["accent"]), add="+")
            e.bind("<FocusOut>", lambda ev: box.set_border(t["border"]), add="+")
        else:
            e.outer = e
        e.ph_on = False
        # Frameless windows don't always take keyboard focus by themselves.
        e.bind("<Button-1>", lambda ev: (self.root.focus_force(), ev.widget.focus_set()))
        if placeholder:
            def show(_ev=None):
                if not e.get():
                    e.insert(0, placeholder)
                    e.configure(fg=t["muted"])
                    e.ph_on = True

            def hide(_ev=None):
                if e.ph_on:
                    e.delete(0, "end")
                    e.configure(fg=t["text"])
                    e.ph_on = False

            e.bind("<FocusIn>", hide, add="+")
            e.bind("<FocusOut>", show, add="+")
            show()
        return e

    @staticmethod
    def value(e):
        return "" if e.ph_on else e.get().strip()

    def set_entry(self, e, text):
        """Programmatic fill (used by tests and inline helpers)."""
        e.event_generate("<FocusIn>")
        if e.ph_on:
            e.delete(0, "end")
            e.configure(fg=self.t["text"])
            e.ph_on = False
        e.delete(0, "end")
        e.insert(0, text)

    def menu(self, items, x, y):
        t = self.t
        m = tk.Menu(self.root, tearoff=0, font=self.fonts["ui"], bg=t["entry"], fg=t["text"],
                    activebackground=t["active"], activeforeground=t["header_text"], bd=0)
        for item in items:
            if item is None:
                m.add_separator()
            else:
                m.add_command(label=item[0], command=item[1])
        m.tk_popup(x, y)

    def popup_menu(self, widget, options, on_pick):
        self.menu([(label, lambda v=value: on_pick(v)) for value, label in options],
                  widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())

    def section(self, parent, text, pady=(14, 4), bg=None):
        tk.Label(parent, text=text.upper(), bg=bg or self.t["bg"], fg=self.t["muted"],
                 font=self.fonts["section"], anchor="w").pack(fill="x", padx=10, pady=pady)

    def checkbox(self, parent, text, checked, on_toggle, bg=None):
        """Settings toggle drawn as a switch (label on the left, switch on the right)."""
        t = self.t
        bg = bg or parent.cget("bg")
        row = tk.Frame(parent, bg=bg, cursor="hand2")
        sw = tk.Label(row, bg=bg, bd=0, cursor="hand2",
                      image=ui.switch_photo(self.root, checked, t["accent"],
                                            colors.mix(t["border"], t["text"], 0.15), bg, self.scale))
        sw.pack(side="right", padx=(8, 2))
        lbl = tk.Label(row, text=text, bg=bg, fg=t["text"], font=self.fonts["ui"], cursor="hand2",
                       anchor="w")
        lbl.pack(side="left", fill="x", expand=True)
        for w in (row, sw, lbl):
            w.bind("<Button-1>", lambda e: on_toggle())
        return row

    def chips(self, parent, options, current, on_pick, per_row=4, font_for=None, on_menu=None):
        t = self.t
        frame = tk.Frame(parent, bg=parent.cget("bg"))
        current = current if isinstance(current, (set, list)) else {current}
        for i, (value, label) in enumerate(options):
            sel = value in current
            chip = self.button(frame, label, lambda v=value: on_pick(v),
                               bg=t["active"] if sel else t["entry"],
                               fg=t["header_text"] if sel else t["text"],
                               font=self._font_obj(font_for(value)) if font_for else "ui",
                               padx=10, pady=3, border=None if sel else t["border"], radius=100)
            chip.grid(row=i // per_row, column=i % per_row, sticky="w", padx=(0, 5), pady=3)
            if on_menu:
                chip.bind("<Button-3>", lambda e, v=value: on_menu(e, v))
        return frame

    def menu_button(self, parent, options, current, on_pick, fmt="{} ▾", bg=None, font="small"):
        btn = self.button(parent, fmt.format(dict(options).get(current, current)), lambda: None,
                          bg=bg or self.t["entry"], font=font)
        btn.bind("<Button-1>", lambda e: self.popup_menu(btn, options, on_pick))
        return btn

    def _click_later(self, fn):
        """Run single-click action after a short delay so a double-click can cancel it."""
        self._cancel_click()
        self._pending_click = self.root.after(230, fn)

    def _cancel_click(self):
        if self._pending_click:
            self.root.after_cancel(self._pending_click)
            self._pending_click = None

    # ---- layout

    @property
    def rail_side(self):
        return self.data.get("rail_side", "left")

    def _side_for(self, x, y, w):
        """Rail goes on the side of the note that faces the middle of the screen."""
        area = pu.work_area(x + w // 2, y + 20) or (0, 0, self.root.winfo_screenwidth(), 0)
        return "right" if x + w / 2 < (area[0] + area[2]) / 2 else "left"

    def build_ui(self):
        if self._notes_save_after or hasattr(self, "note_text"):
            self._save_note()  # the text box is about to be rebuilt
        for w in self.root.winfo_children():
            if not isinstance(w, (tk.Toplevel, tk.Menu)):
                w.destroy()
        self._ribbons_hidden = False  # fresh layout: header/bottom bar are visible again
        self._tucked = None
        self._last_hover = datetime.now()  # and stay visible for a moment
        if self.data["bubble"]:
            self._build_bubble()
            return
        if getattr(self, "_bubble_layered", False):
            pu.end_layered(self.root)
            self._bubble_layered = False
            self.root.attributes("-alpha", 0.99)  # make Tk re-apply its own transparency
            self.apply_opacity()
        self.root.attributes("-transparentcolor", "")
        if self.data.get("x") is not None:
            self.data["rail_side"] = self._side_for(
                self.data["x"], self.data.get("y", 0), self.data.get("width", int(340 * self.scale)))
        t = self.t
        self.root.configure(bg=t["bg"], highlightthickness=0 if self._dwm else 1,
                            highlightbackground=t["border"])
        self._build_header()
        self.dock = self._build_dock()
        self.body = tk.Frame(self.root, bg=t["bg"])
        self._add_boxes = {}
        self._task_footers = []
        self.panels = {
            "today": self._build_today_panel(),
            "tasks": self._build_tasks_panel(),
            "reminders": self._build_reminders_panel(),
            "focus": self._build_focus_panel(),
            "grid": self._build_grid_panel(),
            "notes": self._build_notes_panel(),
            "music": self._build_music_panel(),
            "settings": self._build_settings_panel(),
        }
        self._build_grip()
        panel = self.data["panel"]
        if panel != "settings" and panel not in self.settings["tabs"]:
            panel = self.settings["tabs"][0]
        self.show_panel(panel, expand=False)
        if self.data["collapsed"]:
            self.grip.place_forget()
        else:
            self.dock.pack(side="bottom", fill="x")
            self.body.pack(fill="both", expand=True)
        self.render_music()
        self._update_focus_display()
        self._restore_geometry()
        if self.root.winfo_ismapped():
            self._apply_window_style()

    def _apply_window_style(self):
        """Rounded window corners + theme-colored border (Windows 11); square border otherwise."""
        if self.data["bubble"]:
            pu.style_window(self.root, rounded=False, border=None)
            if not getattr(self, "_bubble_layered", False):  # app started minimized
                self.root.attributes("-transparentcolor", "")
                self._bubble_layered = pu.begin_layered(self.root)
                if not self._bubble_layered:
                    self.root.attributes("-transparentcolor", BUBBLE_KEY)
                self.render_bubble()
            return
        self._dwm = pu.style_window(self.root, rounded=True, border=self.t["border"])
        self.root.configure(highlightthickness=0 if self._dwm else 1)

    def _build_header(self):
        """Vertical tab rail on the left: drag grip, tab icons, then settings/minimize/close."""
        t = self.t
        rail = tk.Frame(self.root, bg=t["header"])
        rail.pack(side=self.rail_side, fill="y")
        self.header = rail

        grip = tk.Label(rail, text="\u283f", bg=t["header"], cursor="arrow", pady=4,
                        fg=colors.mix(t["header_text"], t["header"], 0.35),
                        font=("Segoe UI Symbol", 12))
        grip.pack(side="top", fill="x", pady=(4, 2))

        def rail_icon(glyph, cmd, tip):
            b = self.icon_button(rail, glyph, cmd, bg=t["header"], fg=t["header_text"],
                                 hover_fg=t["accent"], font="icon_tab")
            b.configure(padx=10, pady=7)
            b.pack(side="bottom", fill="x")
            self._tooltip(b, tip)
            return b

        # ✕ closes the note down to the bubble; hiding to the tray / quitting is on the bubble's
        # right-click menu and the tray icon.
        close = rail_icon(Icon.CLOSE, self.enter_bubble, "Close to bubble")
        close.bind("<Enter>", lambda e: (close.configure(bg="#e5534b", fg="white"),
                                         self._show_tip(close, "Close to bubble")))
        close.bind("<Leave>", lambda e: (close.configure(bg=t["header"], fg=t["header_text"]),
                                         self._hide_tip()))
        self.min_btn = rail_icon(Icon.MINIMIZE, self.enter_bubble, "Minimize to bubble")
        self.settings_btn = rail_icon(Icon.SETTINGS, lambda: self.show_panel("settings"), "Settings")

        self.tab_widgets = {}
        for key, label, glyph in TABS:
            if key not in self.settings["tabs"]:
                continue
            f = tk.Frame(rail, bg=t["header"], cursor="hand2")
            f.pack(side="top", fill="x")
            line = tk.Frame(f, bg=t["header"], width=max(2, int(3 * self.scale)))
            line.pack(side=self.rail_side, fill="y", pady=int(5 * self.scale))
            ic = tk.Label(f, text=glyph, bg=t["header"], fg=t["header_text"],
                          font=self.fonts["icon_tab"], padx=9, pady=8, cursor="hand2")
            ic.pack(side="left", fill="x", expand=True)
            for w in (f, ic, line):
                # Click switches tab; press-and-move drags the whole note instead.
                w.bind("<ButtonPress-1>", self._drag_start)
                w.bind("<B1-Motion>", self._drag_move)
                w.bind("<ButtonRelease-1>", lambda e, k=key: self._drag_end(lambda: self.show_panel(k)))
                w.bind("<Enter>", lambda e, k=key, lb=label, wd=f: (self._style_tab(k, hover=True),
                                                                   self._show_tip(wd, lb)))
                w.bind("<Leave>", lambda e, k=key: (self._style_tab(k), self._hide_tip()))
            self.tab_widgets[key] = (f, ic, line, label)

        # Shown only while collapsed to the rail, so a running focus timer stays visible.
        self.header_timer = tk.Label(rail, bg=t["header"], fg=t["accent"], font=self.fonts["small_bold"])

        for w in (rail, grip, self.header_timer):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", lambda e: self._drag_end())
            w.bind("<Double-Button-1>", lambda e: self.toggle_collapse())

    # ---- tooltips for the rail icons

    def _tooltip(self, widget, text):
        widget.bind("<Enter>", lambda e: self._show_tip(widget, text), add="+")
        widget.bind("<Leave>", lambda e: self._hide_tip(), add="+")

    def _show_tip(self, widget, text):
        self._hide_tip()
        t = self.t
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=text, bg=t["text"], fg=t["bg"], font=self.fonts["small_bold"],
                 padx=8, pady=3).pack()
        tip.update_idletasks()
        gap = int(6 * self.scale)
        if self.rail_side == "right":
            x = widget.winfo_rootx() - tip.winfo_reqwidth() - gap
        else:
            x = widget.winfo_rootx() + widget.winfo_width() + gap
        y = widget.winfo_rooty() + (widget.winfo_height() - int(22 * self.scale)) // 2
        tip.geometry(f"+{x}+{y}")
        tip.lift()
        self._tip = tip

    def _hide_tip(self):
        tip = getattr(self, "_tip", None)
        if tip is not None and tip.winfo_exists():
            tip.destroy()
        self._tip = None

    def _style_tab(self, key, hover=False):
        if key not in self.tab_widgets:
            return
        t = self.t
        _f, ic, line, _label = self.tab_widgets[key]
        active = key == self.data["panel"]
        alert = key == "reminders" and self._missed
        if alert:
            fg = t["overdue"]
        elif active or hover:
            fg = t["header_text"]
        else:
            fg = colors.mix(t["header_text"], t["header"], 0.3)
        ic.configure(fg=fg)
        if active:
            line_color = t["accent"]
        elif hover:
            line_color = colors.mix(t["header"], t["header_text"], 0.25)
        else:
            line_color = t["header"]
        line.configure(bg=line_color)

    def _style_tabs(self):
        for key in getattr(self, "tab_widgets", {}):
            self._style_tab(key)
        if hasattr(self, "settings_btn") and self.settings_btn.winfo_exists():
            on = self.data["panel"] == "settings"
            self.settings_btn.base_fg = self.t["accent"] if on else self.t["header_text"]
            self.settings_btn.configure(fg=self.settings_btn.base_fg)

    def _build_dock(self):
        """Bottom bar: focus timer chip + music controls."""
        t = self.t
        dock = tk.Frame(self.root, bg=t["dock"])
        tk.Frame(dock, bg=colors.mix(t["border"], t["dock"], 0.4), height=1).pack(fill="x")
        inner = tk.Frame(dock, bg=t["dock"])
        corner = int(16 * self.scale)  # leave room for the resize corner (opposite the rail)
        inner.pack(fill="x", pady=6,
                   padx=(corner, 8) if self.rail_side == "right" else (8, corner))
        self.focus_chip = self.button(inner, "\u25b6 Focus", self._focus_chip_click, bg=t["header"],
                                      font="ui_bold", padx=11, pady=4, radius=100)
        self.focus_chip.pack(side="left")
        self.music_frame = tk.Frame(inner, bg=t["dock"])
        self.music_frame.pack(side="left", fill="x", expand=True, padx=(8, 0))
        return dock

    def _build_today_panel(self):
        t = self.t
        p = tk.Frame(self.body, bg=t["bg"])
        top = tk.Frame(p, bg=t["bg"])
        top.pack(fill="x", padx=12, pady=(10, 2))
        self.today_title = tk.Label(top, bg=t["bg"], fg=t["text"], font=self.fonts["title"],
                                    anchor="w")
        self.today_title.pack(fill="x")
        self.today_stats = tk.Label(top, bg=t["bg"], fg=t["muted"], font=self.fonts["small"],
                                    anchor="w")
        self.today_stats.pack(fill="x")
        self.today_list = CanvasList(p, self, t["bg"])
        self.today_list.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        return p

    def _task_entry_row(self, parent, attr):
        """Add-task box, hidden until the round + button opens it."""
        t = self.t
        row = tk.Frame(parent, bg=t["bg"])
        e = self.entry(row, "New task \u2014 e.g. call mom 3pm \u00b7 essay due fri !", rounded=True)
        e.outer.pack(fill="x")
        e.bind("<Return>", lambda ev: self.add_task(e))
        e.bind("<Escape>", lambda ev: self._close_add_box(attr))
        e.bind("<FocusOut>", lambda ev: self.root.after(150, self._close_add_box_if_empty, attr),
               add="+")
        setattr(self, attr, e)
        return row

    def _task_footer(self, parent, attr, add_attr):
        t = self.t
        foot = tk.Frame(parent, bg=t["bg"])
        foot.pack(side="bottom", fill="x", padx=10, pady=(4, 6))
        self.button(foot, Icon.ADD, lambda: self.toggle_add_box(add_attr), bg=t["accent"],
                    fg=colors.readable_on(t["accent"]), font="icon", padx=8, pady=8,
                    radius=100, square=True).pack(side="left")
        self.button(foot, "Clear done", self.clear_done_tasks, bg=t["bg"], fg=t["accent"],
                    font="small_bold", padx=10, pady=4, radius=100).pack(side="left", padx=(8, 0))
        lbl = tk.Label(foot, bg=t["bg"], fg=t["muted"], font=self.fonts["small"])
        lbl.pack(side="right")
        setattr(self, attr, lbl)
        self._task_footers.append(foot)  # auto-hides along with the header/bottom bar

    def toggle_add_box(self, attr):
        row, _entry, _before = self._add_boxes[attr]
        if row.winfo_ismapped():
            self._close_add_box(attr)
        else:
            self.open_add_box(attr)

    def open_add_box(self, attr):
        row, entry, before = self._add_boxes[attr]
        if not row.winfo_ismapped():
            row.pack(side="bottom", fill="x", padx=10, pady=(6, 0), before=before)
        self.root.focus_force()
        entry.focus_set()

    def _close_add_box(self, attr):
        row, entry, _before = self._add_boxes.get(attr, (None, None, None))
        if row is not None and row.winfo_exists() and row.winfo_ismapped():
            entry.delete(0, "end")
            row.pack_forget()
            self.root.focus_set()  # drop focus so the placeholder comes back next time

    def _close_add_box_if_empty(self, attr):
        row, entry, _before = self._add_boxes.get(attr, (None, None, None))
        if (row is not None and row.winfo_exists() and not self.value(entry)
                and self.root.focus_get() is not entry):
            self._close_add_box(attr)

    def _shortcut_add_task(self, _e=None):
        """Ctrl+N: open the add-task box (on the Tasks or Grid tab)."""
        if self.data["bubble"] or self.hidden:
            return
        if self.data["panel"] not in ("tasks", "grid"):
            self.show_panel("tasks" if "tasks" in self.settings["tabs"] else "grid")
        self.open_add_box("task_entry" if self.data["panel"] == "tasks" else "grid_entry")

    def _build_tasks_panel(self):
        t = self.t
        p = tk.Frame(self.body, bg=t["bg"])
        self._task_footer(p, "task_count", "task_entry")
        row = self._task_entry_row(p, "task_entry")
        self.task_list = CanvasList(p, self, t["bg"])
        self.task_list.pack(fill="both", expand=True, padx=4, pady=(6, 0))
        self.task_list.on_reorder = self._reorder_task
        self._add_boxes["task_entry"] = (row, self.task_entry, self.task_list)
        return p

    def _build_grid_panel(self):
        t = self.t
        p = tk.Frame(self.body, bg=t["bg"])
        self._task_footer(p, "grid_count", "grid_entry")
        row = self._task_entry_row(p, "grid_entry")
        grid = tk.Frame(p, bg=t["bg"])
        grid.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._add_boxes["grid_entry"] = (row, self.grid_entry, grid)
        for c in range(2):
            grid.columnconfigure(c, weight=1, uniform="col")
            grid.rowconfigure(c, weight=1, uniform="row")
        self.grid_cells = {}
        for i, (key, title, important, soon) in enumerate(GRID_CELLS):
            card = ui.RoundedFrame(grid, fill=t["entry"], bg=t["bg"], radius=12,
                                   border=t["border"], pad=4, stretch=True, scale=self.scale)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=3, pady=3)
            cell = card.inner
            color = t["overdue"] if key == "imp_soon" else t["accent"] if important else t["muted"]
            head = tk.Label(cell, text=title, bg=t["entry"], fg=color,
                            font=self.fonts["small_bold"], anchor="w")
            head.pack(fill="x", padx=6, pady=(4, 1))
            sl = CanvasList(cell, self, t["entry"])
            sl.pack(fill="both", expand=True, padx=2, pady=(0, 2))
            self.grid_cells[key] = (sl, head, title)
        return p

    def _build_reminders_panel(self):
        t = self.t
        p = tk.Frame(self.body, bg=t["bg"])

        form = tk.Frame(p, bg=t["bg"])
        form.pack(fill="x", padx=10, pady=(10, 2))
        self.rem_entry = self.entry(form, "e.g. call mom tomorrow 3pm", rounded=True)
        self.rem_entry.outer.pack(side="left", fill="x", expand=True)
        self.rem_entry.bind("<Return>", lambda ev: self.add_reminder())
        self.rem_repeat = "none"
        self.repeat_btn = self.button(form, "Once ▾", self._pick_repeat, bg=t["entry"],
                                      border=t["border"], font="small", padx=9, pady=7)
        self.repeat_btn.pack(side="left", padx=(6, 0))
        self.button(form, Icon.ADD, self.add_reminder, font="icon", padx=10,
                    pady=7).pack(side="left", padx=(6, 0))

        self.rem_hint = tk.Label(p, text="3pm · fri 9am · in 20m · oct 5 · every weekday 7am",
                                 bg=t["bg"], fg=t["muted"], font=self.fonts["small"], anchor="w")
        self.rem_hint.pack(fill="x", padx=10)

        foot = tk.Frame(p, bg=t["bg"])
        foot.pack(side="bottom", fill="x", padx=10, pady=(2, 4))
        self.rem_count = tk.Label(foot, bg=t["bg"], fg=t["muted"], font=self.fonts["small"])
        self.rem_count.pack(side="left")
        self.button(foot, "Clear completed", self.clear_done_reminders, bg=t["bg"],
                    fg=t["accent"], hover=t["hover"], font="small_bold").pack(side="right")

        self.rem_list = CanvasList(p, self, t["bg"])
        self.rem_list.pack(fill="both", expand=True, padx=4, pady=(6, 0))
        return p

    def _build_focus_panel(self):
        t = self.t
        p = tk.Frame(self.body, bg=t["bg"])
        sl = ScrollList(p, t["bg"])
        sl.pack(fill="both", expand=True)
        box = sl.inner

        self.section(box, "Mode", pady=(10, 4))
        self.modes_frame = tk.Frame(box, bg=t["bg"])
        self.modes_frame.pack(fill="x", padx=10)
        self.mode_editor = tk.Frame(box, bg=t["bg"])
        self.mode_editor.pack(fill="x", padx=10)

        self.ring = tk.Canvas(box, bg=t["bg"], highlightthickness=0,
                              height=int(210 * self.scale))
        self.ring.pack(fill="x", pady=(10, 4))
        self.ring.bind("<Configure>", lambda e: self._schedule_ring())

        ctrls = tk.Frame(box, bg=t["bg"])
        ctrls.pack(pady=(2, 6))
        self.focus_main_btn = self.button(ctrls, "", self._focus_main, bg=t["accent"],
                                          fg=colors.readable_on(t["accent"]),
                                          hover=colors.mix(t["accent"], "#000000", 0.12),
                                          font="ui_bold", padx=22, pady=8, radius=100)
        self.focus_main_btn.pack(side="left")
        self.focus_skip_btn = self.button(ctrls, "Skip", self._focus_skip, bg=t["entry"],
                                          border=t["border"], font="ui", padx=14, pady=8,
                                          radius=100)
        self.focus_skip_btn.pack(side="left", padx=(6, 0))
        self.focus_stop_btn = self.button(ctrls, "Stop", self.focus_stop, bg=t["entry"],
                                          border=t["border"], font="ui", padx=14, pady=8,
                                          radius=100)
        self.focus_stop_btn.pack(side="left", padx=(6, 0))

        self.focus_stats = tk.Label(box, bg=t["bg"], fg=t["muted"], font=self.fonts["small"])
        self.focus_stats.pack(pady=(4, 10))
        self.render_focus_modes()
        return p

    def _build_notes_panel(self):
        t = self.t
        smart = self.settings["notes_smart"]
        p = tk.Frame(self.body, bg=t["bg"])
        bar = tk.Frame(p, bg=t["bg"])
        bar.pack(fill="x", padx=10, pady=(8, 6))
        mode = self.checkbox(bar, "Smart", smart,
                             lambda: self.set_setting("notes_smart", not self.settings["notes_smart"]))
        mode.pack(side="left")
        self.icon_button(bar, Icon.COPY, self.copy_note, hover_fg=t["accent"]).pack(side="right")
        mono_on = self.settings["notes_mono"]
        self.button(bar, "Mono", lambda: self.set_setting("notes_mono", not self.settings["notes_mono"]),
                    bg=t["active"] if mono_on else t["bg"], border=None if mono_on else t["border"],
                    font="small_bold", padx=9, pady=2, radius=100).pack(side="right", padx=(0, 4))
        self.note_pages = tk.Frame(bar, bg=t["bg"])
        if smart:
            self.note_pages.pack(side="left", fill="x", expand=True, padx=(10, 0))
            hint = tk.Label(p, text="12*4= then Enter to calculate \u00b7 rent = 1200 saves a number "
                                    "\u00b7 Alt+\u2191/\u2193 moves a line",
                            bg=t["bg"], fg=t["muted"], font=self.fonts["small"], anchor="w",
                            justify="left")
            hint.pack(side="bottom", fill="x", padx=12, pady=(2, 4))
            hint.bind("<Configure>", lambda e: hint.configure(wraplength=max(100, e.width - 4)))

        box = ui.RoundedFrame(p, fill=t["entry"], bg=t["bg"], radius=12, border=t["border"],
                              pad=6, stretch=True, scale=self.scale)
        box.pack(fill="both", expand=True, padx=10, pady=(0, 0 if smart else 8))
        txt = tk.Text(box.inner, wrap="word", undo=True, maxundo=200, relief="flat", bd=0,
                      bg=t["entry"], fg=t["text"], insertbackground=t["text"],
                      selectbackground=colors.mix(t["entry"], t["accent"], 0.35),
                      selectforeground=t["text"], inactiveselectbackground=colors.mix(
                          t["entry"], t["accent"], 0.2),
                      font=self.fonts["mono"] if self.settings["notes_mono"] else self.fonts["body"],
                      padx=6, pady=4, spacing1=1, spacing3=1, highlightthickness=0)
        txt.pack(fill="both", expand=True)
        txt.bind("<Button-1>", lambda e: (self.root.focus_force(), txt.focus_set()), add="+")
        txt.bind("<FocusIn>", lambda e: box.set_border(t["accent"]), add="+")
        txt.bind("<FocusOut>", lambda e: box.set_border(t["border"]), add="+")
        if smart:
            txt.bind("<Return>", self._note_return)
            txt.bind("<KP_Enter>", self._note_return)
            txt.bind("<Alt-Up>", lambda e: self._move_line(-1))
            txt.bind("<Alt-Down>", lambda e: self._move_line(1))
        txt.bind("<<Modified>>", self._note_modified)
        self.note_text = txt
        self._load_note_page()
        self.render_note_pages()
        return p

    def _build_music_panel(self):
        p = tk.Frame(self.body, bg="#111111")
        self.np_canvas = tk.Canvas(p, bg="#111111", highlightthickness=0)
        self.np_canvas.pack(fill="both", expand=True)
        self.np_canvas.bind("<Configure>", lambda e: self._schedule_now_playing())
        return p

    def _build_settings_panel(self):
        t = self.t
        s = self.settings
        p = tk.Frame(self.body, bg=t["bg"])
        sl = ScrollList(p, t["bg"])
        sl.pack(fill="both", expand=True)
        box = sl.inner
        self.settings_scroll = sl
        self.wrap_labels = []

        def note(text, pady=(0, 0)):
            lbl = tk.Label(box, text=text, bg=t["bg"], fg=t["muted"], font=self.fonts["small"],
                           justify="left", anchor="w", wraplength=int(250 * self.scale))
            lbl.pack(fill="x", padx=10, pady=pady)
            self.wrap_labels.append(lbl)
            return lbl

        def labeled(text):
            row = tk.Frame(box, bg=t["bg"])
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=text, bg=t["bg"], fg=t["text"], font=self.fonts["ui"],
                     anchor="w").pack(side="left")
            return row

        # Appearance -----------------------------------------------------
        self.section(box, "Theme", pady=(10, 4))
        swatches = tk.Frame(box, bg=t["bg"])
        swatches.pack(fill="x", padx=10)
        for name, th in THEMES.items():
            sw = tk.Label(swatches, image=self._swatch(th["header"], th["bg"], th["accent"],
                                                       name == s["theme"]),
                          bg=t["bg"], bd=0, cursor="hand2")
            sw.pack(side="left", padx=(0, 6))
            sw.bind("<Button-1>", lambda e, n=name: self.set_setting("theme", n))
        self._build_custom_swatch(swatches)
        if s["theme"] == "Custom":
            self._build_custom_colors(box)

        self.section(box, "Font")
        fonts = [(fam, label) for fam, label in FONT_CHOICES if fam in self.families]
        self.chips(box, fonts, s["font"], lambda f: self.set_setting("font", f), per_row=3,
                   font_for=lambda fam: (fam, 9)).pack(fill="x", padx=10)
        row = labeled("Text size")
        self.chips(row, TEXT_SIZES, s["text_size"],
                   lambda v: self.set_setting("text_size", v)).pack(side="left", padx=8)

        self.section(box, "Opacity")
        self._build_opacity_slider(box)

        # Layout ---------------------------------------------------------
        self.section(box, "Tabs")
        self.chips(box, [(k, label) for k, label, _i in TABS], set(s["tabs"]),
                   self.toggle_tab, per_row=3).pack(fill="x", padx=10)
        note("Click to show or hide a tab. The — button on the left rail shrinks the note "
             "into a small bubble; click the bubble to open it again.", pady=(4, 0))
        self.checkbox(box, "Hide header & bottom bar when the mouse is away", s["autohide"],
                      lambda: self.set_setting("autohide", not s["autohide"])).pack(
            fill="x", padx=10, pady=(8, 0))
        self.checkbox(box, "Tuck into the screen edge when pushed against it",
                      s["edge_tuck"], lambda: self.set_setting("edge_tuck", not s["edge_tuck"])).pack(
            fill="x", padx=10, pady=(6, 0))
        row = labeled("Hide after")
        self.chips(row, AUTOHIDE_DELAYS, s["autohide_delay"],
                   lambda v: self.set_setting("autohide_delay", v)).pack(
            side="left", padx=8)

        # Tasks ----------------------------------------------------------
        self.section(box, "Tasks")
        row = labeled("“Due soon” means within")
        self.menu_button(row, DUE_SOON, s["due_soon_days"],
                         lambda v: self.set_setting("due_soon_days", v)).pack(side="left", padx=6)
        note("Type dates right in the task: “essay due fri 5pm”. End with ! to mark it "
             "important. Drag ⠿ to reorder; right-click a task for more.", pady=(4, 0))

        # Music ----------------------------------------------------------
        self.section(box, "Music")
        self.chips(box, media.SOURCES, s["music"],
                   lambda v: self.set_setting("music", v)).pack(fill="x", padx=10)
        self.checkbox(box, "Show album cover in the bottom bar", s["dock_art"],
                      lambda: self.set_setting("dock_art", not s["dock_art"])).pack(
            fill="x", padx=10, pady=(4, 0))
        if media.AVAILABLE:
            note("Works with the Spotify and Apple Music apps and their web players. If you "
                 "install either app later, DYFW picks it up automatically. The Music tab "
                 "shows the cover full-size.", pady=(4, 0))
        else:
            note("Music controls need Windows 10 or newer.", pady=(4, 0))

        # General --------------------------------------------------------
        self.section(box, "General")
        self.startup_row = tk.Frame(box, bg=t["bg"])
        self.startup_row.pack(fill="x", padx=10)
        self._render_startup_row()

        # Calendars ------------------------------------------------------
        self.section(box, "Calendars")
        note("Paste an iCal (.ics) link from Canvas, Google Calendar, Outlook, Moodle, "
             "Blackboard… Items show up under Reminders and Today.")

        self.feeds_frame = tk.Frame(box, bg=t["bg"])
        self.feeds_frame.pack(fill="x", padx=10, pady=(6, 0))

        form = tk.Frame(box, bg=t["bg"])
        form.pack(fill="x", padx=10, pady=(6, 0))
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Name", bg=t["bg"], fg=t["muted"], font=self.fonts["small"]).grid(
            row=0, column=0, sticky="w", padx=(0, 6))
        self.feed_name = self.entry(form, "Canvas", rounded=True)
        self.feed_name.outer.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        tk.Label(form, text="Link", bg=t["bg"], fg=t["muted"], font=self.fonts["small"]).grid(
            row=1, column=0, sticky="w", padx=(0, 6))
        self.feed_url = self.entry(form, "https://….ics", rounded=True)
        self.feed_url.outer.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        self.feed_lead = 1440
        self.lead_btn = self.button(form, "Remind 1 day before ▾", self._pick_new_feed_lead,
                                    bg=t["entry"], border=t["border"], font="small", pady=4)
        self.lead_btn.grid(row=2, column=1, sticky="w", pady=(4, 0))
        self.button(form, "Add calendar", self.add_feed, font="small_bold", padx=12,
                    pady=4).grid(
            row=2, column=2, sticky="e", pady=(4, 0))
        self.feed_msg = tk.Label(box, text="", bg=t["bg"], fg=t["muted"],
                                 font=self.fonts["small"], anchor="w", justify="left")
        self.feed_msg.pack(fill="x", padx=10, pady=(4, 0))

        note("Canvas: Calendar → “Calendar Feed” (bottom right) → copy link.\n"
             "Google: calendar Settings → “Secret address in iCal format”.\n"
             "Outlook: Settings → Shared calendars → Publish → ICS link.", pady=(8, 12))

        def rewrap():
            for lbl in self.wrap_labels:
                lbl.configure(wraplength=max(120, sl.width - 24))
        sl.on_width_change = rewrap
        self.render_feeds()
        return p

    def _swatch(self, header, body, accent, selected):
        """Rounded theme preview: header color with a body-colored card and an accent dot."""
        from PIL import ImageDraw, ImageTk
        t = self.t
        size = int(28 * self.scale)
        ring = t["text"] if selected else t["bg"]
        img = ui.rounded_image(size, size, int(9 * self.scale), ring, t["bg"])
        inset = max(2, int(2 * self.scale))
        face = ui.rounded_image(size - 2 * inset, size - 2 * inset, int(7 * self.scale), header, ring)
        img.paste(face, (inset, inset))
        card_w, card_h = int(size * 0.6), int(size * 0.38)
        card = ui.rounded_image(card_w, card_h, int(3 * self.scale), body, header)
        cx, cy = (size - card_w) // 2, int(size * 0.47)
        img.paste(card, (cx, cy))
        d = ImageDraw.Draw(img)
        r = max(2, int(2.5 * self.scale))
        d.ellipse((cx + card_w // 2 - r, cy + card_h // 2 - r, cx + card_w // 2 + r,
                   cy + card_h // 2 + r), fill=accent)
        photo = ImageTk.PhotoImage(img, master=self.root)
        self._swatch_refs = getattr(self, "_swatch_refs", [])[-20:] + [photo]
        return photo

    def _build_custom_swatch(self, parent):
        t = self.t
        custom = self.settings.get("custom_theme")
        selected = self.settings["theme"] == "Custom"
        if custom:
            sw = tk.Label(parent, image=self._swatch(custom["header"], custom["bg"],
                                                     custom["accent"], selected),
                          bg=t["bg"], bd=0, cursor="hand2")
        else:
            size = int(28 * self.scale)
            img = ui.rounded_photo(self.root, size, size, int(9 * self.scale), t["entry"], t["bg"],
                                   t["border"])
            sw = tk.Label(parent, image=img, text=Icon.ADD, compound="center", fg=t["muted"],
                          font=self.fonts["icon_small"], bg=t["bg"], bd=0, cursor="hand2")
        sw.pack(side="left", padx=(0, 6))
        sw.bind("<Button-1>", lambda e: self.select_custom_theme())
        tk.Label(parent, text="Custom", bg=t["bg"], fg=t["muted"],
                 font=self.fonts["small"]).pack(side="left")

    def _build_custom_colors(self, parent):
        t = self.t
        custom = self.settings["custom_theme"]
        grid = tk.Frame(parent, bg=t["bg"])
        grid.pack(fill="x", padx=10, pady=(8, 0))
        for c in range(2):
            grid.columnconfigure(c, weight=1, uniform="cc")
        for i, (key, label) in enumerate(colors.CUSTOM_KEYS):
            value = custom.get(key)
            card = ui.RoundedFrame(grid, fill=t["entry"], bg=t["bg"], radius=10,
                                   border=t["border"], pad=4, scale=self.scale)
            card.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 5), pady=3)
            cell = card.inner
            cell.configure(cursor="hand2")
            size = int(20 * self.scale)
            chip = tk.Label(cell, bd=0, bg=t["entry"], cursor="hand2",
                            image=ui.rounded_photo(self.root, size, size, int(6 * self.scale),
                                                   value or t[key], t["entry"], t["border"]))
            chip.pack(side="left", padx=6, pady=3)
            info = tk.Frame(cell, bg=t["entry"], cursor="hand2")
            info.pack(side="left", fill="x", expand=True)
            name = tk.Label(info, text=label, bg=t["entry"], fg=t["text"], font=self.fonts["ui"],
                            anchor="w", cursor="hand2")
            name.pack(fill="x")
            code = tk.Label(info, text="auto" if value is None else value.upper(), bg=t["entry"],
                            fg=t["muted"], font=self.fonts["small"], anchor="w", cursor="hand2")
            code.pack(fill="x")
            for w in (card, cell, chip, info, name, code):
                w.bind("<Button-1>", lambda e, k=key, lb=label: self.open_color_picker(k, lb))
        note = tk.Label(parent, text="Click a color to pick it on the wheel or paste a code "
                                     "(#ff8800 or 255, 136, 0).", bg=t["bg"], fg=t["muted"],
                        font=self.fonts["small"], anchor="w", justify="left",
                        wraplength=int(260 * self.scale))
        note.pack(fill="x", padx=10, pady=(2, 0))
        self.button(parent, "Reset to Lemon", self.reset_custom_theme, bg=t["bg"], fg=t["accent"],
                    hover=t["hover"], font="small_bold").pack(anchor="w", padx=6, pady=(2, 0))

    def _build_opacity_slider(self, parent):
        t = self.t
        lo = 0.3
        pad = int(10 * self.scale)
        knob = int(7 * self.scale)
        state = {"value": self.settings["opacity"]}
        row = tk.Frame(parent, bg=t["bg"])
        row.pack(fill="x", padx=10)
        pct = tk.Label(row, bg=t["bg"], fg=t["muted"], font=self.fonts["small"], width=5, anchor="e")
        pct.pack(side="right")
        track = tk.Canvas(row, height=int(22 * self.scale), bg=t["bg"], highlightthickness=0,
                          cursor="hand2")
        track.pack(side="left", fill="x", expand=True)

        def draw(_e=None):
            track.delete("all")
            w, h = track.winfo_width(), track.winfo_height()
            x = pad + (state["value"] - lo) / (1 - lo) * (w - 2 * pad)
            mid = h / 2
            track.create_line(pad, mid, w - pad, mid, fill=t["border"], width=4, capstyle="round")
            track.create_line(pad, mid, x, mid, fill=t["accent"], width=4, capstyle="round")
            track.create_oval(x - knob, mid - knob, x + knob, mid + knob, fill=t["accent"],
                              outline=t["bg"], width=2)
            pct.configure(text=f"{round(state['value'] * 100)}%")

        def drag(e):
            w = track.winfo_width()
            frac = min(1.0, max(0.0, (e.x - pad) / max(1, w - 2 * pad)))
            state["value"] = round(lo + frac * (1 - lo), 2)
            self.root.attributes("-alpha", state["value"])
            draw()

        track.bind("<Configure>", draw)
        track.bind("<Button-1>", drag)
        track.bind("<B1-Motion>", drag)
        track.bind("<ButtonRelease-1>",
                   lambda e: self.set_setting("opacity", state["value"], rebuild=False))

    def _render_startup_row(self):
        for w in self.startup_row.winfo_children():
            w.destroy()
        self.checkbox(self.startup_row, "Start with Windows", pu.is_startup_enabled(),
                      self.toggle_startup).pack(side="left")

    def _place_grip(self):
        if self.rail_side == "right":
            self.grip.place(relx=0.0, rely=1.0, anchor="sw")
        else:
            self.grip.place(relx=1.0, rely=1.0, anchor="se")
        self.grip.lift()

    def _build_grip(self):
        t = self.t
        right_rail = self.rail_side == "right"
        self.grip = tk.Label(self.root, text="◣" if right_rail else "◢", bg=t["dock"],
                             fg=t["border"], font=("Segoe UI Symbol", 9),
                             cursor="size_ne_sw" if right_rail else "size_nw_se")
        self._place_grip()
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)
        self.grip.bind("<ButtonRelease-1>", lambda e: self._save_geometry())

    def show_panel(self, key, expand=True):
        if key not in self.panels:
            key = "today"
        self.data["panel"] = key
        for panel in self.panels.values():
            panel.pack_forget()
        self.panels[key].pack(fill="both", expand=True)
        if expand and self.data["collapsed"]:
            self.toggle_collapse()
        self.refresh()
        if key == "focus":
            self.render_focus_ring()
        elif key == "music":
            self._schedule_now_playing()
        self.save()

    def toggle_collapse(self):
        collapsed = not self.data["collapsed"]
        self.data["collapsed"] = collapsed
        h = self.root.winfo_height()
        if collapsed:
            self.data["width"] = self.root.winfo_width()
            self.body.pack_forget()
            self.dock.pack_forget()
            self.grip.place_forget()
            self._update_focus_display()
            self.root.update_idletasks()
            rail_w = self.header.winfo_reqwidth()
            if self.rail_side == "right":  # shrink toward the rail on the right
                x = self.root.winfo_x() + self.root.winfo_width() - rail_w
                self.root.geometry(f"{rail_w}x{h}+{x}+{self.root.winfo_y()}")
            else:
                self.root.geometry(f"{rail_w}x{h}")
        else:
            self.dock.pack(side="bottom", fill="x")
            self.body.pack(fill="both", expand=True)
            self._place_grip()
            self._update_focus_display()
            full_w = self.data.get("width", int(340 * self.scale))
            if self.rail_side == "right":  # grow back out to the left, keeping the rail put
                x = self.root.winfo_x() - (full_w - self.root.winfo_width())
                self.root.geometry(f"{full_w}x{h}+{x}+{self.root.winfo_y()}")
            else:
                self.root.geometry(f"{full_w}x{h}")
        self.grip.lift()
        self.save()

    def set_setting(self, key, value, rebuild=True):
        self.settings[key] = value
        self.save()
        if key in ("font", "text_size"):
            self._make_fonts()
        elif key == "opacity":
            self.apply_opacity()
        elif key == "music":
            self._apply_music_source()
        if rebuild:
            scroll = self.settings_scroll.canvas.yview()[0] if self.data["panel"] == "settings" else 0
            self.build_ui()
            if scroll and self.data["panel"] == "settings":
                self.root.update_idletasks()
                self.settings_scroll.canvas.yview_moveto(scroll)

    def toggle_tab(self, key):
        tabs = list(self.settings["tabs"])
        if key in tabs:
            if len(tabs) == 1:
                return  # keep at least one tab
            tabs.remove(key)
        else:
            tabs = [k for k, _l, _i in TABS if k in tabs or k == key]
        self.set_setting("tabs", tabs)

    def apply_opacity(self):
        self.root.attributes("-alpha", max(0.3, min(1.0, self.settings["opacity"])))

    def toggle_startup(self):
        try:
            pu.set_startup(not pu.is_startup_enabled())
        except OSError:
            pass
        if hasattr(self, "startup_row") and self.startup_row.winfo_exists():
            self._render_startup_row()
        if self.tray:
            self.tray.refresh()

    # ---- custom theme

    def select_custom_theme(self):
        if not self.settings.get("custom_theme"):
            t = self.t  # start from whichever preset is showing
            self.settings["custom_theme"] = {"bg": t["bg"], "header": t["header"],
                                             "accent": t["accent"], "text": None,
                                             "dock": None, "popup": None}
        self.set_setting("theme", "Custom")

    def reset_custom_theme(self):
        lemon = THEMES["Lemon"]
        self.settings["custom_theme"] = {"bg": lemon["bg"], "header": lemon["header"],
                                         "accent": lemon["accent"], "text": None,
                                         "dock": None, "popup": None}
        self.set_setting("theme", "Custom")

    def open_color_picker(self, key, label):
        if self.picker and self.picker.winfo_exists():
            self.picker.destroy()
        initial = self.settings["custom_theme"].get(key) or self.t[key]

        def picked(color):
            if color is None and key not in colors.AUTO_KEYS:
                return
            self.settings["custom_theme"][key] = color
            self.set_setting("theme", "Custom")

        self.picker = colors.ColorPicker(self.root, initial, picked, self.t, self.fonts,
                                         self.scale, title=f"{label} color",
                                         allow_auto=key in colors.AUTO_KEYS)

    # ---- geometry: drag, resize, persist

    def _clamp(self, x, y, w=None, h=40):
        """Allow tucking the note partly off-screen, but keep enough of it showing to grab."""
        vs = pu.virtual_screen()
        if vs:
            vx, vy, vw, vh = vs
            w = w or self.root.winfo_width() or 80
            keep = min(w, int(90 * self.scale))
            x = min(max(x, vx - w + keep), vx + vw - keep)
            y = min(max(y, vy), vy + vh - min(h, int(40 * self.scale)))
        return x, y

    def _restore_geometry(self):
        w = self.data.get("width", int(340 * self.scale))
        h = self.data.get("height", int(480 * self.scale))
        x = self.data.get("x")
        y = self.data.get("y")
        if x is None or y is None:
            x = self.root.winfo_screenwidth() - w - int(40 * self.scale)
            y = int(60 * self.scale)
        x, y = self._clamp(x, y, w)
        if self.data["collapsed"]:
            self.root.update_idletasks()
            w = self.header.winfo_reqwidth()
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _save_geometry(self):
        if self.hidden or self.data["bubble"]:
            return
        # While the rail/bottom bar are auto-hidden the window is smaller; store the full size.
        rail_w, bottom = self._ribbon_offsets if self._ribbons_hidden else (0, 0)
        shift = rail_w if self.rail_side == "left" else 0  # a left rail hides off the x side
        self.data["x"] = (self._tuck_from_x if self._tucked else self.root.winfo_x()) - shift
        self.data["y"] = self.root.winfo_y()
        self.data["height"] = self.root.winfo_height() + bottom
        if not self.data["collapsed"]:
            self.data["width"] = self.root.winfo_width() + rail_w
        self.save()

    def _drag_start(self, e):
        self._win_drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y(),
                          e.x_root, e.y_root)
        self._drag_moved = False

    def _drag_move(self, e):
        if not getattr(self, "_win_drag", None):
            return
        dx, dy, ox, oy = self._win_drag
        if not self._drag_moved and abs(e.x_root - ox) + abs(e.y_root - oy) < 5:
            return  # still a click, not a drag
        self._drag_moved = True
        x, y = self._clamp(e.x_root - dx, e.y_root - dy)
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, on_click=None):
        moved = getattr(self, "_drag_moved", False)
        self._win_drag, self._drag_moved = None, False
        if moved:
            self.root.update_idletasks()  # make sure the last move is applied before saving
            self._snap_to_edges()
            self._save_geometry()
            side = self._side_for(self.data["x"], self.data["y"], self.data.get("width", 0))
            if side != self.rail_side and not self._ribbons_hidden:
                self.build_ui()  # moved across the middle: flip the rail to face inward
        elif on_click:
            on_click()

    def _resize_start(self, e):
        self._resize = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height(),
                        self.root.winfo_x() + self.root.winfo_width())

    def _resize_move(self, e):
        x0, y0, w0, h0, right_edge = self._resize
        dx = e.x_root - x0
        mirrored = self.rail_side == "right"  # corner is bottom-left: drag left to widen
        w = max(int(MIN_W * self.scale), w0 + (-dx if mirrored else dx))
        h = max(int(MIN_H * self.scale), h0 + e.y_root - y0)
        first = self._resize_pending is None
        self._resize_pending = (w, h, right_edge - w if mirrored else None)
        if first:  # apply only the latest size once Tk catches up
            self.root.after_idle(self._apply_resize)

    def _apply_resize(self):
        size, self._resize_pending = self._resize_pending, None
        if size:
            w, h, x = size
            if x is None:
                self.root.geometry(f"{w}x{h}")
            else:
                self.root.geometry(f"{w}x{h}+{x}+{self.root.winfo_y()}")

    def _on_root_configure(self, e):
        if e.widget is self.root and self._fit_after is None and not self.data["bubble"]:
            self._fit_after = self.root.after_idle(self._adapt_fonts)

    def _font_level_for(self, width):
        return next(level for min_w, level in FONT_STEPS if width >= int(min_w * self.scale))

    def _adapt_fonts(self):
        """Shrink/grow text in steps as the note is resized (the chosen size is the max)."""
        self._fit_after = None
        if self.data["bubble"] or self.data["collapsed"] or not self.root.winfo_exists():
            return
        width = self.root.winfo_width()
        if self._ribbons_hidden:
            width += self._ribbon_offsets[0]
        level = self._font_level_for(width)
        if level == self._font_level:
            return
        self._font_level = level
        self._make_fonts()  # named fonts: every label/entry updates in place
        ui.refresh_all()    # re-size rounded buttons and boxes to the new text size
        self.refresh()      # re-lay out the lists
        self.render_music()
        if self.data["panel"] == "focus":
            self._schedule_ring()

    def _on_wheel(self, e):
        w = self.root.winfo_containing(e.x_root, e.y_root)
        while w is not None:
            if isinstance(w, (ScrollList, CanvasList)):
                w.scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1))
                return
            w = w.master

    def _keep_on_top(self):
        # Fullscreen apps and other topmost windows can push us down; reassert.
        try:
            if not self.hidden:
                self.root.attributes("-topmost", True)
                self.root.lift()
            for win in self.alerts.values():
                win.lift()
            if self.picker and self.picker.winfo_exists():
                self.picker.lift()
            tip = getattr(self, "_tip", None)
            if tip is not None and tip.winfo_exists():
                tip.lift()
        except tk.TclError:
            pass
        self.root.after(TOPMOST_MS, self._keep_on_top)

    # ---- auto-hide header + bottom bar

    def _hover_poll(self):
        try:
            self._check_hover()
        except Exception:  # never let one bad check stop the hover watcher for good
            pass
        try:
            self.root.after(250, self._hover_poll)
        except tk.TclError:
            pass  # app is closing

    def _note_keypress(self, _e=None):
        self._last_key = datetime.now()

    def _area(self):
        """Usable area of the monitor the note is on (falls back to the virtual screen)."""
        x = self._tuck_from_x if self._tucked else self.root.winfo_x()
        area = pu.work_area(x + self.root.winfo_width() // 2,
                            self.root.winfo_y() + self.root.winfo_height() // 2)
        if area:
            return area
        vx, vy, vw, vh = pu.virtual_screen() or (0, 0, self.root.winfo_screenwidth(),
                                                 self.root.winfo_screenheight())
        return vx, vy, vx + vw, vy + vh

    def _snap_to_edges(self):
        if self.data["bubble"]:
            return
        left, top, right, _bottom = self._area()
        x, y, w = self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width()
        snap = int(EDGE_SNAP * self.scale)
        nx, ny = x, y
        if abs(x + w - right) <= snap:
            nx = right - w
        elif abs(x - left) <= snap:
            nx = left
        if abs(y - top) <= snap:
            ny = top
        if (nx, ny) != (x, y):
            self.root.geometry(f"+{nx}+{ny}")
            self.root.update_idletasks()

    def _docked_edge(self):
        if self.data["bubble"] or self.hidden or not self.settings["edge_tuck"]:
            return None
        left, _top, right, _bottom = self._area()
        x, w = self.root.winfo_x(), self.root.winfo_width()
        if x + w >= right - 2:
            return "right"
        if x <= left + 2:
            return "left"
        return None

    def _pointer_inside(self, margin=0):
        px, py = self.root.winfo_pointerxy()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        return (x - margin <= px < x + self.root.winfo_width() + margin
                and y - margin <= py < y + self.root.winfo_height() + margin)

    def _busy(self):
        typed_recently = (datetime.now() - self._last_key).total_seconds() < 3
        return bool(self._resize_pending is not None or self._drag or self._editing
                    or getattr(self, "_drag_moved", False) or self._typing_new_task()
                    or typed_recently or self.alerts)

    def tuck(self, edge):
        """Slide the note into the screen edge, leaving a thin strip to pull it back out."""
        left, _top, right, _bottom = self._area()
        x, y, w = self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width()
        peek = int(TUCK_PEEK * self.scale)
        target = right - peek if edge == "right" else left - w + peek
        self._tuck_from_x = x
        self._tucked = edge
        self._hide_tip()
        self._animate(180, lambda k: self.root.geometry(f"+{round(x + (target - x) * k)}+{y}"),
                      lambda: None)

    def untuck(self):
        x0, y = self.root.winfo_x(), self.root.winfo_y()
        target = self._tuck_from_x
        self._tucked = None
        self._last_hover = datetime.now()
        self._animate(140, lambda k: self.root.geometry(f"+{round(x0 + (target - x0) * k)}+{y}"),
                      lambda: None)

    def _check_tuck(self):
        """Edge tucking. Returns True when it handled this hover check."""
        if self._tucked:
            # Pull back out when the pointer reaches the visible strip (or comes close to it).
            if self._pointer_inside(margin=int(8 * self.scale)):
                self.untuck()
            return True
        edge = self._docked_edge()
        if not edge:
            return False
        if self._ribbons_hidden:
            self.show_ribbons()  # the rail is the handle that peeks out
            return True
        now = datetime.now()
        if self._pointer_inside() or self._busy():
            self._last_hover = now
        elif (now - self._last_hover).total_seconds() >= self.settings["autohide_delay"]:
            self.tuck(edge)
        return True

    def _check_hover(self):
        if self._animating:
            return
        if self.data["bubble"] or self.hidden or self.data["collapsed"]:
            if self._ribbons_hidden:
                self.show_ribbons()
            return
        if self._check_tuck():
            return
        can_hide = (self.settings["autohide"] and not self.data["bubble"] and not self.hidden
                    and not self.data["collapsed"] and hasattr(self, "header")
                    and self.header.winfo_exists())
        if not can_hide:
            if self._ribbons_hidden:
                self.show_ribbons()
            return
        px, py = self.root.winfo_pointerxy()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        inside = x <= px < x + self.root.winfo_width() and y <= py < y + self.root.winfo_height()
        busy = (self._resize_pending is not None or self._drag or self._editing
                or getattr(self, "_drag_moved", False) or self._typing_new_task())
        now = datetime.now()
        if inside or busy:
            self._last_hover = now
            if self._ribbons_hidden:
                self.show_ribbons()
        elif (not self._ribbons_hidden
              and (now - self._last_hover).total_seconds() >= self.settings["autohide_delay"]):
            self.hide_ribbons()

    def _typing_new_task(self):
        try:
            focused = self.root.focus_get()
        except (KeyError, tk.TclError):
            return False
        return any(focused is entry for _row, entry, _b in self._add_boxes.values())

    def _keep_dock_when_hidden(self):
        """The bottom bar stays up while hidden so the music controls remain usable."""
        return self.settings["music"] != "off" and media.AVAILABLE

    def _sync_focus_chip(self):
        """While auto-hidden, the bottom bar shows only music unless a focus timer is running."""
        if not hasattr(self, "focus_chip") or not self.focus_chip.winfo_exists():
            return
        show = not self._ribbons_hidden or self.focus["mode"] is not None
        if show and not self.focus_chip.winfo_ismapped():
            self.focus_chip.pack(side="left", before=self.music_frame)
        elif not show and self.focus_chip.winfo_ismapped():
            self.focus_chip.pack_forget()

    def _animate(self, duration_ms, step, done):
        """Run step(progress 0..1) with ease-in-out over duration_ms, then done()."""
        self._animating = True
        frames = max(1, duration_ms // 16)

        def tick(i):
            try:
                k = i / frames
                step(k * k * (3 - 2 * k))  # smoothstep easing
                if i < frames:
                    self.root.after(16, tick, i + 1)
                    return
                done()
            except tk.TclError:
                pass
            self._animating = False

        tick(1)

    def hide_ribbons(self):
        self.root.update_idletasks()  # need real sizes, not a just-built layout's 1px
        if self.header.winfo_width() <= 1:
            return
        for foot in self._task_footers:
            if foot.winfo_exists():
                foot.pack_forget()
        keep_dock = self._keep_dock_when_hidden()
        rail, dock = self.header, self.dock
        left = rail.winfo_width()
        bottom = 0 if keep_dock else dock.winfo_height()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        self._ribbon_offsets = (left, bottom)
        self.grip.place_forget()
        self._hide_tip()
        self._ribbons_hidden = True
        self._sync_focus_chip()
        # Slide the rail out sideways (and the bar down) while the window shrinks by the same
        # amount from those sides, so the note's content never moves.
        from_left = self.rail_side == "left"
        rail.pack_propagate(False)
        rail.configure(width=left)
        if bottom:
            dock.pack_propagate(False)
            dock.configure(height=bottom)

        def step(k):
            dl, db = round(left * k), round(bottom * k)
            rail.configure(width=max(1, left - dl))
            if bottom:
                dock.configure(height=max(1, bottom - db))
            nx = x + dl if from_left else x
            self.root.geometry(f"{max(60, w - dl)}x{max(40, h - db)}+{nx}+{y}")

        def done():
            rail.pack_forget()
            rail.pack_propagate(True)
            if bottom:
                dock.pack_forget()
                dock.pack_propagate(True)

        self._animate(200, step, done)

    def show_ribbons(self):
        if not self._ribbons_hidden:
            return
        left, bottom = self._ribbon_offsets
        x, y = self.root.winfo_x(), self.root.winfo_y()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        self._ribbons_hidden = False
        rail, dock = self.header, self.dock
        if not rail.winfo_exists():
            return
        if bottom:
            # Bottom bar first: the rail is packed "before" it, which fails while it's hidden.
            dock.pack_propagate(False)
            dock.configure(height=1)
            dock.pack(side="bottom", fill="x", before=self.body)
        rail.pack_propagate(False)
        rail.configure(width=1)
        rail.pack(side=self.rail_side, fill="y", before=dock)
        from_left = self.rail_side == "left"
        for foot in self._task_footers:
            if foot.winfo_exists():
                first = foot.master.pack_slaves()
                foot.pack(side="bottom", fill="x", padx=10, pady=(4, 6),
                          **({"before": first[0]} if first else {}))
        self._sync_focus_chip()

        def step(k):
            dl, db = round(left * k), round(bottom * k)
            rail.configure(width=max(1, dl))
            if bottom:
                dock.configure(height=max(1, db))
            nx = x - dl if from_left else x
            self.root.geometry(f"{w + dl}x{h + db}+{nx}+{y}")

        def done():
            rail.pack_propagate(True)
            dock.pack_propagate(True)
            self._place_grip()

        self._animate(140, step, done)

    # ---- bubble (minimized) mode

    @property
    def bubble_size(self):
        """Bubble window size: the disc plus room for its soft shadow."""
        return int(BUBBLE_DISC * self.scale) + 2 * int(BUBBLE_SHADOW * self.scale)

    def enter_bubble(self):
        self._save_geometry()
        size = self.bubble_size
        self._hide_tip()
        if self.data.get("bubble_custom"):  # you dragged it somewhere before: go back there
            bx, by = self.data["bubble_x"], self.data["bubble_y"]
        else:
            bx, by = self._bubble_home()
        self.data["bubble_x"], self.data["bubble_y"] = self._clamp(bx, by, size, size)
        self.data["bubble_origin"] = [self.data["bubble_x"], self.data["bubble_y"]]
        self.data["bubble"] = True
        self.save()
        self.build_ui()

    def _bubble_home(self):
        """Default bubble spot: top-right corner of the monitor the note is on."""
        _left, top, right, _bottom = self._area()
        margin = int(BUBBLE_MARGIN * self.scale)
        return right - self.bubble_size - margin, top + margin

    def bubble_to_top_right(self):
        self.data["bubble_custom"] = False
        x, y = self._bubble_home()
        self.data["bubble_x"], self.data["bubble_y"] = x, y
        self.data["bubble_origin"] = [x, y]
        self.root.geometry(f"+{x}+{y}")
        self.save()

    def exit_bubble(self):
        size = self.bubble_size
        bx, by = self.root.winfo_x(), self.root.winfo_y()
        self.data["bubble"] = False
        self.data["unseen_updates"] = 0
        # Bubble not moved: the note comes back exactly where it was. Moved: the note opens
        # with its minimize button (bottom-left of the rail) under the bubble.
        w = self.data.get("width", int(340 * self.scale))
        h = self.data.get("height", int(480 * self.scale))
        if [bx, by] != self.data.get("bubble_origin"):
            self.data["x"], self.data["y"] = bx, by + size - h
        # Whatever the anchor, open the note fully on screen (not half off the edge).
        left, top, right, bottom = self._area()
        self.data["x"] = max(left, min(self.data.get("x", left), right - w))
        self.data["y"] = max(top, min(self.data.get("y", top), bottom - h))
        self.save()
        self.build_ui()

    def _build_bubble(self):
        size = self.bubble_size
        self.root.configure(bg=BUBBLE_KEY, highlightthickness=0)
        self._bubble_layered = False
        self.bubble = tk.Canvas(self.root, width=size, height=size, bg=BUBBLE_KEY,
                                highlightthickness=0, cursor="hand2")
        self.bubble.pack()
        x, y = self._clamp(self.data.get("bubble_x", 100), self.data.get("bubble_y", 100),
                           size, size)
        self.root.geometry(f"{size}x{size}+{x}+{y}")
        if self.root.winfo_ismapped():
            pu.style_window(self.root, rounded=False, border=None)
        self._bubble_drag = None
        self._bubble_ready_at = datetime.now() + timedelta(seconds=BUBBLE_CLICK_DELAY)
        self.bubble.bind("<ButtonPress-1>", self._bubble_press)
        self.bubble.bind("<B1-Motion>", self._bubble_motion)
        self.bubble.bind("<ButtonRelease-1>", self._bubble_release)
        self.bubble.bind("<Button-3>", self._bubble_menu)
        self.root.update_idletasks()
        # Smooth edges + soft shadow need a per-pixel-alpha window; fall back to a color key.
        self._bubble_layered = self.root.winfo_ismapped() and pu.begin_layered(self.root)
        if not self._bubble_layered:
            self.root.attributes("-transparentcolor", BUBBLE_KEY)
        self.render_bubble()

    def render_bubble(self):
        """Minimized bubble: Apple-Watch-style ring on a dark disc.

        Idle: ring = today's progress (done / done + left), number = tasks left (a check when
        clear). Focus: green ring counting down, number = minutes left. Red badge = overdue or
        due soon; red dot = new calendar items.
        """
        if not self.data["bubble"] or not hasattr(self, "bubble") or not self.bubble.winfo_exists():
            return
        from PIL import Image, ImageTk
        t = self.t
        size = self.bubble_size
        disc = int(BUBBLE_DISC * self.scale)
        urgent, updates = self._bubble_attention()
        f = self.focus
        today = datetime.now().date().isoformat()
        if f["mode"] is not None:
            total = f.get("length") or 1
            remaining = self._focus_remaining()
            spec = dict(ring=bubble.FOCUS_GREEN, progress=remaining / total,
                        label=str(max(0, math.ceil(remaining / 60))))
        else:
            open_tasks = sum(1 for x in self.data["tasks"] if not x["done"])
            done_today = sum(1 for x in self.data["tasks"]
                             if x["done"] and (x.get("done_at") or "").startswith(today))
            ring = bubble.ring_color(t)
            if open_tasks:
                spec = dict(ring=ring, progress=done_today / (done_today + open_tasks),
                            label=str(open_tasks) if open_tasks < 100 else "99+")
            else:
                spec = dict(ring=ring, progress=1.0, icon=Icon.CHECK)
        img = bubble.render(size, disc, badge=urgent, dot=bool(updates and not urgent), **spec)

        c = self.bubble
        c.delete("all")
        if self._bubble_layered and pu.update_layered(self.root, img):
            return
        # Fallback (no per-pixel alpha): hard-edged shape on the transparent color key.
        if self._bubble_layered:
            self._bubble_layered = False
            self.root.attributes("-transparentcolor", BUBBLE_KEY)
        hard = img.getchannel("A").point(lambda a: 255 if a > 160 else 0)
        flat = Image.new("RGB", (size, size), colors.to_rgb(BUBBLE_KEY))
        flat.paste(img.convert("RGB"), (0, 0), hard)
        self._bubble_img = ImageTk.PhotoImage(flat, master=self.root)
        c.create_image(0, 0, anchor="nw", image=self._bubble_img)

    def _bubble_attention(self):
        """(things needing you now, unseen calendar updates) for the bubble's red badge.

        Counts missed reminders, overdue tasks, and tasks/reminders/homework due soon.
        """
        now = datetime.now()
        near = now + timedelta(hours=BUBBLE_NEAR_HOURS)
        urgent = 0
        for task in self.data["tasks"]:
            dl = parse_iso(task["deadline"])
            if not task["done"] and dl and dl <= near:
                urgent += 1
        for r in self.data["reminders"]:
            if r["done"]:
                continue
            when = parse_iso(r.get("event_start")) or parse_iso(r["due"])
            if r["fired"] or when <= near:
                urgent += 1
        return urgent, self.data.get("unseen_updates", 0) > 0

    def _bubble_press(self, e):
        if datetime.now() < self._bubble_ready_at:  # ignore clicks right after minimizing
            self._bubble_drag = None
            return
        self._bubble_drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def _bubble_motion(self, e):
        if self._bubble_drag is None:
            return
        x0, y0, wx, wy, moved = self._bubble_drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if moved or abs(dx) + abs(dy) > 4:
            self._bubble_drag = (x0, y0, wx, wy, True)
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def _bubble_release(self, _e):
        # Only a press that started on the bubble counts. The — button shrinks the note on
        # mouse-down, so the matching mouse-up lands on the freshly made bubble right under
        # the pointer; treating that as a click reopened the note straight away.
        drag, self._bubble_drag = self._bubble_drag, None
        if drag is None:
            return
        moved = drag[4]
        if moved:
            self.root.update_idletasks()  # apply the last move before reading the position
            self.data["bubble_x"], self.data["bubble_y"] = self.root.winfo_x(), self.root.winfo_y()
            self.data["bubble_custom"] = True
            self.save()
        else:
            self.exit_bubble()

    def _bubble_menu(self, e):
        f = self.focus
        items = [("Open note", self.exit_bubble)]
        if f["mode"]:
            items.append(("Stop focus timer", self.focus_stop))
        else:
            items.append(("Start focus", lambda: self.focus_start("focus")))
        if self.data.get("bubble_custom"):
            items.append(("Move to top-right", self.bubble_to_top_right))
        items += [None, ("Hide to tray", self.close_to_tray), ("Quit DYFW", self.quit)]
        self.menu(items, e.x_root, e.y_root)

    # ---- show / hide / quit / background messages

    def close_to_tray(self):
        if not self.tray:
            self.quit()
            return
        self._save_geometry()
        self.root.withdraw()
        self.hidden = True
        if not self.settings.get("tray_hint_shown"):
            self.settings["tray_hint_shown"] = True
            self.save()
            self.tray.notify("Still running in the tray. Click the note icon to bring it back; "
                             "right-click it to quit.")

    def show_note(self):
        self.root.deiconify()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.update_idletasks()
        pu.hide_from_taskbar(self.root)
        self.hidden = False

    def quit(self):
        self._save_geometry()
        self._save_note()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def _poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                if msg[0] == "tray":
                    self._handle_tray(msg[1])
                elif msg[0] == "feed":
                    self.apply_feed(*msg[1:])
                elif msg[0] == "media":
                    self.now_playing = msg[1]
                    self.render_music()
        except queue.Empty:
            pass
        if self.show_signal.poll():
            self.show_note()
            if self.data["bubble"]:
                self.exit_bubble()
        try:
            self.root.after(200, self._poll_queue)
        except tk.TclError:
            pass

    def _handle_tray(self, cmd):
        if cmd == "toggle":
            self.close_to_tray() if not self.hidden else self.show_note()
        elif cmd == "sync":
            self.sync_feeds()
        elif cmd == "startup":
            self.toggle_startup()
        elif cmd == "quit":
            self.quit()

    def _periodic_refresh(self):
        """Keep countdown badges and the Today view current."""
        if not self._editing and not self._drag:
            self.refresh()
        self.root.after(REFRESH_MS, self._periodic_refresh)

    # ---- shared list rendering

    def refresh(self):
        if self.data["bubble"]:
            self._update_missed()
            self.render_bubble()
            return
        self.render_today()
        self.render_tasks()
        self.render_grid()
        self.render_reminders()
        self._style_tabs()

    @staticmethod
    def icon_char(name):
        return getattr(Icon, name)

    def _badge_spec(self, target):
        text, level = countdown(target)
        colors_ = BADGE_COLORS.get(level)
        return (text, colors_[0], colors_[1]) if colors_ else (text, None, self.t["muted"])

    # ---- today

    def _done_today(self):
        today = datetime.now().date().isoformat()
        items = self.data["tasks"] + self.data["reminders"]
        return sum(1 for x in items if x.get("done") and (x.get("done_at") or "").startswith(today))

    def render_today(self):
        if not hasattr(self, "today_list") or not self.today_list.winfo_exists():
            return
        now = datetime.now()
        self.today_title.configure(text=now.strftime("%A, %b ") + str(now.day))
        today = now.date().isoformat()
        sessions = self.focus["log"].get(today, 0)
        mins = self.focus["minutes"].get(today, 0)
        focus_txt = f"{sessions} focus session{'' if sessions == 1 else 's'}"
        if mins:
            focus_txt += f" ({hours_minutes(mins)})"
        self.today_stats.configure(text=f"{self._done_today()} done today \u00b7 {focus_txt}")

        horizon = datetime.combine(now.date() + timedelta(days=1), time(23, 59))
        due_items = []  # (when, kind, obj)
        for task in self.data["tasks"]:
            dl = parse_iso(task["deadline"])
            if not task["done"] and dl and dl <= horizon:
                due_items.append((dl, "task", task))
        for r in self.data["reminders"]:
            if r["done"]:
                continue
            when = parse_iso(r.get("event_start")) or parse_iso(r["due"])
            limit = now + timedelta(hours=48) if r.get("source") else horizon
            if when <= limit:
                due_items.append((when, "rem", r))
        due_items.sort(key=lambda x: x[0])
        due_ids = {id(obj) for _, _, obj in due_items}
        important = [task for task in self.data["tasks"]
                     if task["important"] and not task["done"] and id(task) not in due_ids]

        rows = []
        if due_items:
            rows.append({"kind": "section", "text": "Due soon"})
            for when, kind, obj in due_items:
                rows.append(self._task_spec(obj, meta=format_due(when, now)) if kind == "task"
                            else self._reminder_spec(obj, now))
        if important:
            rows.append({"kind": "section", "text": "Important"})
            rows += [self._task_spec(task) for task in important]
        if not rows:
            rows.append({"kind": "empty",
                         "text": "Nothing urgent and nothing starred.\nStill \u2014 do your work."})
        self.today_list.set_rows(rows)

    # ---- tasks

    def _find_task(self, tid):
        return next((x for x in self.data["tasks"] if x["id"] == tid), None)

    def _sort_tasks(self):
        self.data["tasks"].sort(key=lambda x: not x["important"])  # stable: keeps manual order

    def add_task(self, entry=None):
        entry = entry or self.task_entry
        raw = self.value(entry)
        if not raw:
            return
        text, when, _repeat, important = extract_when(raw, default_time=TASK_DEFAULT_TIME)
        task = {"id": uuid.uuid4().hex, "text": text, "done": False, "important": important,
                "deadline": None}
        self._set_task_time(task, when)
        self.data["tasks"].append(task)
        self._sort_tasks()
        entry.delete(0, "end")
        self.save()
        self.refresh()

    def toggle_task(self, tid):
        task = self._find_task(tid)
        if task:
            task["done"] = not task["done"]
            task["done_at"] = iso(datetime.now()) if task["done"] else None
            if task["done"]:
                self._close_alert("task:" + tid)
            self.save()
            self.refresh()

    def toggle_important(self, tid):
        task = self._find_task(tid)
        if task:
            task["important"] = not task["important"]
            self._sort_tasks()
            self.save()
            self.refresh()

    def edit_task(self, tid, raw):
        task = self._find_task(tid)
        if task:
            text, when, _repeat, important = extract_when(raw, default_time=TASK_DEFAULT_TIME)
            task["text"] = text
            if when:
                self._set_task_time(task, when)
            if important:
                task["important"] = True
                self._sort_tasks()
            self.save()
        self.refresh()

    @staticmethod
    def _set_task_time(task, when):
        """A task with a real time ("call mom 3pm") also pops up an alert at that time.
        Date-only deadlines ("essay due fri" = end of day) don't alarm."""
        task["deadline"] = iso(when) if when else None
        task["alert"] = bool(when and when.time() != TASK_DEFAULT_TIME)
        task["alert_at"] = task["deadline"] if task["alert"] else None
        task["fired"] = False

    def clear_deadline(self, tid):
        task = self._find_task(tid)
        if task:
            self._set_task_time(task, None)
            self._close_alert("task:" + tid)
            self.save()
            self.refresh()

    def delete_task(self, tid):
        self._close_alert("task:" + tid)
        self.data["tasks"] = [x for x in self.data["tasks"] if x["id"] != tid]
        self.save()
        self.refresh()

    def clear_done_tasks(self):
        self.data["tasks"] = [x for x in self.data["tasks"] if not x["done"]]
        self.save()
        self.refresh()

    def _task_menu(self, event, task, lst):
        tid = task["id"]
        items = [("Unstar" if task["important"] else "\u2605 Mark important",
                  lambda: self.toggle_important(tid)),
                 ("Edit", lambda: lst.begin_edit(tid))]
        if task["deadline"]:
            items.append(("Remove deadline", lambda: self.clear_deadline(tid)))
        items += [None, ("Delete", lambda: self.delete_task(tid))]
        self.menu(items, event.x_root, event.y_root)

    def _task_spec(self, task, meta=None, compact=False, handle=False):
        tid = task["id"]
        dl = parse_iso(task["deadline"])
        if meta is None and dl and not compact:  # grid cells are narrow: badge only
            meta = format_due(dl)
        if meta and task.get("alert") and not task["done"]:
            meta += " \u00b7 alarm"
        return {
            "kind": "item", "key": tid, "text": task["text"], "done": task["done"],
            "meta": meta, "meta_color": self.t["accent"],
            "badge": self._badge_spec(dl) if dl else None,
            "star": task["important"], "delete": not compact, "handle": handle,
            "on_toggle": lambda: self.toggle_task(tid),
            "on_star": lambda: self.toggle_important(tid),
            "on_delete": lambda: self.delete_task(tid),
            "on_edit": lambda v: self.edit_task(tid, v),
            "on_menu": lambda e, lst, _k: self._task_menu(e, task, lst),
        }

    def _due_soon(self, task, now):
        dl = parse_iso(task["deadline"])
        return dl is not None and dl <= now + timedelta(days=self.settings["due_soon_days"])

    def _task_counts(self):
        tasks = self.data["tasks"]
        left = sum(1 for x in tasks if not x["done"])
        return f"{left} left \u00b7 {len(tasks) - left} done" if tasks else ""

    def render_tasks(self):
        if not hasattr(self, "task_list") or not self.task_list.winfo_exists():
            return
        tasks = self.data["tasks"]
        rows = [self._task_spec(task, handle=True) for task in tasks]
        if not rows:
            rows = [{"kind": "empty", "text": "Nothing here yet. Click + (or Ctrl+N) to add a task."}]
        self.task_list.set_rows(rows)
        self.task_count.configure(text=self._task_counts())

    def render_grid(self):
        if not hasattr(self, "grid_cells") or not self.grid_count.winfo_exists():
            return
        tasks = self.data["tasks"]
        now = datetime.now()
        for key, title, important, soon in GRID_CELLS:
            sl, head, _ = self.grid_cells[key]
            items = [x for x in tasks
                     if x["important"] == important and self._due_soon(x, now) == soon]
            items.sort(key=lambda x: (x["done"], x["deadline"] or "9999"))
            open_n = sum(1 for x in items if not x["done"])
            head.configure(text=f"{title}  {open_n}" if open_n else title)
            sl.set_rows([self._task_spec(task, compact=True) for task in items])
        self.grid_count.configure(text=self._task_counts())

    def _reorder_task(self, tid, k):
        """Drag-and-drop from the task list: k is the drop position among the other tasks."""
        task = self._find_task(tid)
        if task is None:
            return
        others = [x for x in self.data["tasks"] if x["id"] != tid]
        n_important = sum(1 for x in others if x["important"])
        # Dropping into the starred group stars the task; dropping below un-stars it.
        if k < n_important:
            task["important"] = True
        elif k > n_important:
            task["important"] = False
        others.insert(k, task)
        self.data["tasks"] = others
        self._sort_tasks()
        self.save()
        self.refresh()

    # ---- reminders

    def _pick_repeat(self):
        def pick(v):
            self.rem_repeat = v
            self.repeat_btn.set_text(dict(REPEATS)[v] + " ▾")
        self.popup_menu(self.repeat_btn, REPEATS, pick)

    def add_reminder(self):
        raw = self.value(self.rem_entry)
        if not raw:
            self.rem_entry.focus_set()
            return
        text, due, repeat, _imp = extract_when(raw, default_time=REMINDER_DEFAULT_TIME)
        if due is None:
            self.rem_hint.configure(text="Add a time — e.g. “at 3pm”, “in 20m”, "
                                         "“tomorrow 9am”", fg=self.t["danger"])
            self.rem_entry.focus_set()
            return
        repeat = repeat or self.rem_repeat
        repeat_txt = "" if repeat == "none" else f", repeats {dict(REPEATS)[repeat].lower()}"
        self.rem_hint.configure(text=f"“{text}” set for {format_due(due)}{repeat_txt}",
                                fg=self.t["accent"])
        self.data["reminders"].append({"id": uuid.uuid4().hex, "text": text, "due": iso(due),
                                       "fired": False, "done": False, "repeat": repeat})
        self.rem_entry.delete(0, "end")
        self.rem_entry.focus_set()
        self.save()
        self.refresh()

    def _find_reminder(self, rid):
        return next((r for r in self.data["reminders"] if r["id"] == rid), None)

    def _find_feed(self, fid):
        return next((f for f in self.data["feeds"] if f["id"] == fid), None)

    def _hide_feed_item(self, r):
        feed = self._find_feed(r.get("source"))
        if feed is not None:
            feed.setdefault("hidden", []).append(r["uid"])

    def toggle_reminder(self, rid):
        r = self._find_reminder(rid)
        if not r:
            return
        r["done"] = not r["done"]
        now = datetime.now()
        r["done_at"] = iso(now) if r["done"] else None
        if r["done"]:
            self._close_alert(rid)
        elif datetime.fromisoformat(r["due"]) <= now:
            if r["repeat"] != "none":
                r["due"] = iso(next_occurrence(datetime.fromisoformat(r["due"]), r["repeat"], now))
                r["fired"] = False
            else:
                r["fired"] = True  # already past: show as missed instead of alerting again
        self.save()
        self.refresh()

    def edit_reminder(self, rid, raw):
        r = self._find_reminder(rid)
        if r:
            text, due, repeat, _imp = extract_when(raw, default_time=REMINDER_DEFAULT_TIME)
            r["text"] = text
            if due:
                r["due"] = iso(due)
                r["fired"] = False
            if repeat:
                r["repeat"] = repeat
            self.save()
        self.refresh()

    def delete_reminder(self, rid):
        r = self._find_reminder(rid)
        if r and r.get("source"):
            self._hide_feed_item(r)
        self.data["reminders"] = [x for x in self.data["reminders"] if x["id"] != rid]
        self._close_alert(rid)
        self.save()
        self.refresh()

    def clear_done_reminders(self):
        for r in self.data["reminders"]:
            if r["done"] and r.get("source"):
                self._hide_feed_item(r)
        self.data["reminders"] = [r for r in self.data["reminders"] if not r["done"]]
        self.save()
        self.refresh()

    def complete_reminder(self, rid):
        """'Done' from the alert: repeating reminders roll forward, others get crossed out."""
        r = self._find_reminder(rid)
        if r:
            if r["repeat"] != "none" and not r.get("source"):
                r["due"] = iso(next_occurrence(datetime.fromisoformat(r["due"]), r["repeat"]))
                r["fired"] = False
            else:
                r["done"] = True
                r["done_at"] = iso(datetime.now())
        self._close_alert(rid)
        self.save()
        self.refresh()

    def snooze_reminder(self, rid, minutes):
        r = self._find_reminder(rid)
        if r:
            r["due"] = iso(datetime.now() + timedelta(minutes=minutes))
            r["fired"] = False
        self._close_alert(rid)
        self.save()
        self.refresh()

    def dismiss_alert(self, rid):
        """Alert closed with the window X: repeating reminders move on, others stay as missed."""
        r = self._find_reminder(rid)
        if r and r["repeat"] != "none" and not r.get("source"):
            r["due"] = iso(next_occurrence(datetime.fromisoformat(r["due"]), r["repeat"]))
            r["fired"] = False
            self.save()
            self.refresh()
        self._close_alert(rid)

    def _reminder_meta(self, r, now):
        if r.get("source"):
            feed = self._find_feed(r["source"])
            name = feed["name"] if feed else "Calendar"
            start = datetime.fromisoformat(r["event_start"])
            return f"{name} · due {format_due(start, now, r.get('all_day'))}"
        parts = [format_due(datetime.fromisoformat(r["due"]), now)]
        if r["repeat"] != "none":
            parts.append("↻ " + dict(REPEATS)[r["repeat"]].lower())
        if r["fired"] and not r["done"]:
            parts.append("missed")
        return " · ".join(parts)

    def _reminder_spec(self, r, now):
        t = self.t
        rid = r["id"]
        url = r.get("url")
        overdue = r["fired"] and not r["done"]
        when = parse_iso(r.get("event_start")) or parse_iso(r["due"])
        return {
            "kind": "item", "key": rid, "text": r["text"], "done": r["done"],
            "meta": self._reminder_meta(r, now),
            "meta_color": t["overdue"] if overdue else t["accent"],
            "badge": None if overdue and not r.get("source") else self._badge_spec(when),
            "delete": True, "open": bool(url),
            "on_toggle": lambda: self.toggle_reminder(rid),
            "on_delete": lambda: self.delete_reminder(rid),
            "on_open": (lambda: webbrowser.open(url)) if url else None,
            "on_edit": None if r.get("source") else (lambda v: self.edit_reminder(rid, v)),
        }

    def _update_missed(self):
        self._missed = sum(1 for r in self.data["reminders"] if r["fired"] and not r["done"])

    def render_reminders(self):
        self._update_missed()
        if not hasattr(self, "rem_list") or not self.rem_list.winfo_exists():
            return
        now = datetime.now()
        rems = sorted(self.data["reminders"],
                      key=lambda r: (r["done"], r.get("event_start") or r["due"]))
        rows = [self._reminder_spec(r, now) for r in rems]
        if not rows:
            rows = [{"kind": "empty", "text": "No reminders yet."}]
        self.rem_list.set_rows(rows)
        upcoming = sum(1 for r in rems if not r["done"])
        self.rem_count.configure(text=f"{upcoming} open \u00b7 {len(rems) - upcoming} done" if rems else "")

    def check_reminders(self):
        now = datetime.now()
        changed = False
        for r in self.data["reminders"]:
            if not r["done"] and not r["fired"] and datetime.fromisoformat(r["due"]) <= now:
                r["fired"] = True
                changed = True
                self.show_reminder_alert(r)
        for task in self.data["tasks"]:
            at = parse_iso(task.get("alert_at"))
            if task.get("alert") and not task["done"] and not task.get("fired") and at and at <= now:
                task["fired"] = True
                changed = True
                self.show_task_alert(task)
        if changed:
            self.save()
            self.refresh()
        self.root.after(CHECK_MS, self.check_reminders)

    # ---- alert popups

    def _alert(self, key, heading, text, left, right=(), right_label=None, on_close=None):
        """Flashing, beeping, always-on-top popup. Buttons are (label, command, primary)."""
        if key in self.alerts:
            self._close_alert(key)
        t = self.t
        pbg, ptext, pmuted = t["popup"], t["popup_text"], t["popup_muted"]
        win = tk.Toplevel(self.root)
        self.alerts[key] = win
        win.title(APP_NAME)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", on_close or (lambda: self._close_alert(key)))

        frame = tk.Frame(win, bg=ALERT_FLASH[0], padx=8, pady=8)
        frame.pack(fill="both", expand=True)
        inner = tk.Frame(frame, bg=pbg, padx=22, pady=18)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=heading, bg=pbg, fg=t["accent"] if pbg == t["bg"] else pmuted,
                 font=self.fonts["small_bold"]).pack(anchor="w")
        tk.Label(inner, text=text, bg=pbg, fg=ptext, font=self.fonts["alert"],
                 wraplength=int(380 * self.scale), justify="left").pack(anchor="w", pady=(6, 16))

        secondary = colors.mix(pbg, ptext, 0.1)
        btns = tk.Frame(inner, bg=pbg)
        btns.pack(fill="x")
        for i, (label, cmd, primary) in enumerate(left):
            if primary:
                b = self.button(btns, label, cmd, bg=GREEN, fg="white", hover=GREEN_HOVER,
                                font="ui_bold", padx=14, pady=6)
            else:
                b = self.button(btns, label, cmd, bg=secondary, fg=ptext, padx=10, pady=6)
            b.pack(side="left", padx=(0 if i == 0 else 6, 0))
        for label, cmd, _primary in right:
            self.button(btns, label, cmd, padx=8, pady=6).pack(side="right", padx=(4, 0))
        if right_label:
            tk.Label(btns, text=right_label, bg=pbg, fg=pmuted,
                     font=self.fonts["small"]).pack(side="right", padx=(12, 2))

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{(win.winfo_screenwidth() - w) // 2}+{(win.winfo_screenheight() - h) // 3}")
        win.update()
        pu.hide_from_taskbar(win)
        win.lift()
        win.focus_force()

        tick = [0]

        def pulse():
            if self.alerts.get(key) is not win:
                return
            tick[0] += 1
            frame.configure(bg=ALERT_FLASH[tick[0] % 2])
            if tick[0] % 3 == 1 and tick[0] < 120:  # beep ~every 1.5s for a minute
                pu.beep()
            win.after(500, pulse)

        pulse()

    def show_task_alert(self, task):
        tid = task["id"]
        dl = parse_iso(task["deadline"])
        heading = "TASK \u00b7 " + (format_due(dl).upper() if dl else "NOW")
        left = [("\u2713  Done", lambda: self._task_alert_done(tid), True)]
        right = [(label, lambda m=mins: self._snooze_task(tid, m), False)
                 for mins, label in ((60, "1 hr"), (15, "15 min"), (5, "5 min"))]
        self._alert("task:" + tid, heading, task["text"], left, right, "Snooze")

    def _task_alert_done(self, tid):
        task = self._find_task(tid)
        self._close_alert("task:" + tid)
        if task and not task["done"]:
            self.toggle_task(tid)

    def _snooze_task(self, tid, minutes):
        """Snoozing moves only the alarm; the task's deadline stays the same."""
        task = self._find_task(tid)
        if task:
            task["alert_at"] = (datetime.now() + timedelta(minutes=minutes)).isoformat(
                timespec="seconds")
            task["fired"] = False
            self.save()
        self._close_alert("task:" + tid)

    def show_reminder_alert(self, r):
        rid = r["id"]
        if rid in self.alerts:
            return
        now = datetime.now()
        if r.get("source"):
            heading = "UPCOMING · " + self._reminder_meta(r, now).upper()
        else:
            heading = "REMINDER · " + format_due(datetime.fromisoformat(r["due"]), now).upper()
        left = [("✓  Done", lambda: self.complete_reminder(rid), True)]
        if r.get("url"):
            left.append(("Open", lambda: webbrowser.open(r["url"]), False))
        right = [(label, lambda m=mins: self.snooze_reminder(rid, m), False)
                 for mins, label in ((60, "1 hr"), (15, "15 min"), (5, "5 min"))]
        self._alert(rid, heading, r["text"], left, right, "Snooze",
                    on_close=lambda: self.dismiss_alert(rid))

    def _close_alert(self, key):
        win = self.alerts.pop(key, None)
        if win:
            win.destroy()

    # ---- focus timer

    @property
    def focus(self):
        return self.data["focus"]

    @property
    def mode(self):
        modes = self.settings["focus_modes"]
        return next((m for m in modes if m["id"] == self.settings["focus_mode"]), modes[0])

    def _focus_remaining(self):
        f = self.focus
        if f["paused"] is not None:
            return f["paused"]
        ends = parse_iso(f["ends"])
        return (ends - datetime.now()).total_seconds() if ends else 0

    def _next_break_minutes(self):
        m = self.mode
        cycle = self.focus["cycle"]
        long_break = cycle and cycle % max(1, m["every"]) == 0
        return (m["long"] if long_break else m["brk"]), bool(long_break)

    def focus_start(self, kind="focus", minutes=None):
        f = self.focus
        if minutes is None:
            minutes = self.mode["focus"] if kind == "focus" else self._next_break_minutes()[0]
        f["mode"] = kind
        f["length"] = minutes * 60
        f["ends"] = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        f["paused"] = None
        self._close_alert("focus")
        self.save()
        self._update_focus_display()

    def focus_stop(self):
        f = self.focus
        f["mode"], f["ends"], f["paused"], f["cycle"], f["length"] = None, None, None, 0, None
        self._close_alert("focus")
        self.save()
        self._update_focus_display()

    def focus_pause_toggle(self):
        f = self.focus
        if not f["mode"]:
            return
        if f["paused"] is None:
            f["paused"] = max(0, self._focus_remaining())
        else:
            f["ends"] = (datetime.now() + timedelta(seconds=f["paused"])).isoformat(timespec="seconds")
            f["paused"] = None
        self.save()
        self._update_focus_display()

    def _focus_main(self):
        if not self.focus["mode"]:
            self.focus_start("focus")
        else:
            self.focus_pause_toggle()

    def _focus_skip(self):
        f = self.focus
        if f["mode"] == "focus":
            self._focus_finished()
        elif f["mode"] == "break":
            self.focus_start("focus")

    def _focus_chip_click(self):
        f = self.focus
        if not f["mode"]:
            self.focus_start("focus")
            return
        items = [("Resume" if f["paused"] is not None else "Pause", self.focus_pause_toggle)]
        if f["mode"] == "focus":
            items.append(("Finish now → break", self._focus_finished))
        else:
            items.append(("Skip break → focus", lambda: self.focus_start("focus")))
        items += [None, ("Open Focus tab", lambda: self.show_panel("focus")),
                  ("Stop timer", self.focus_stop)]
        chip = self.focus_chip
        self.menu(items, chip.winfo_rootx(), chip.winfo_rooty() - 4 - 22 * len(items))

    def _focus_finished(self):
        f = self.focus
        if f["mode"] == "focus":
            today = datetime.now().date().isoformat()
            done_secs = (f.get("length") or 0) - max(0, self._focus_remaining())
            f["log"][today] = f["log"].get(today, 0) + 1
            f["minutes"][today] = f["minutes"].get(today, 0) + max(1, round(done_secs / 60))
            f["cycle"] += 1
            f["mode"], f["ends"], f["paused"], f["length"] = None, None, None, None
            mins, long_break = self._next_break_minutes()
            n = f["log"][today]
            self._alert("focus", f"{self.mode['name'].upper()} SESSION DONE · {n} TODAY",
                        f"Nice work. Take a {mins}-minute {'long ' if long_break else ''}break.",
                        [("Start break", lambda: self.focus_start("break"), True),
                         ("5 more min", lambda: self.focus_start("focus", 5), False)],
                        [("Stop", self.focus_stop, False)])
        else:
            f["mode"], f["ends"], f["paused"], f["length"] = None, None, None, None
            self._alert("focus", "BREAK'S OVER", "Do your fucken work.",
                        [("Start focus", lambda: self.focus_start("focus"), True)],
                        [("Stop", self.focus_stop, False)])
        self.save()
        self._update_focus_display()
        self.refresh()

    def _update_focus_display(self):
        if self.data["bubble"]:
            self.render_bubble()
            return
        if not hasattr(self, "focus_chip") or not self.focus_chip.winfo_exists():
            return
        t = self.t
        f = self.focus
        if not f["mode"]:
            text, header = "▶ Focus", ""
            chip_bg = t["header"]
        else:
            left = mmss(self._focus_remaining())
            if f["paused"] is not None:
                text = f"❚❚ {left}"
            elif f["mode"] == "focus":
                text = f"● {left}"
            else:
                text = f"☕ {left}"
            header = text
            chip_bg = t["active"]
        self.focus_chip.set_text(text)
        self.focus_chip.set_colors(bg=chip_bg)
        if self.data["collapsed"] and header:
            self.header_timer.configure(text=f"{math.ceil(self._focus_remaining() / 60)}m")
            self.header_timer.pack(side="top", pady=6)
        else:
            self.header_timer.pack_forget()
        if self.data["panel"] == "focus":
            self.render_focus_ring()
        self._sync_focus_chip()

    def _focus_tick(self):
        f = self.focus
        if f["mode"] and f["paused"] is None and self._focus_remaining() <= 0:
            self._focus_finished()
        else:
            self._update_focus_display()
        self.root.after(1000, self._focus_tick)

    def render_focus_ring(self):
        if not hasattr(self, "ring") or not self.ring.winfo_exists():
            return
        from PIL import Image, ImageDraw, ImageTk
        t = self.t
        f = self.focus
        c = self.ring
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50:
            return
        size = min(w - 20, h)
        ss = 3
        big = size * ss
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        thick = int(10 * self.scale) * ss
        box = (thick, thick, big - thick, big - thick)
        d.ellipse(box, outline=t["border"], width=thick)
        running = f["mode"] is not None
        if running:
            total = f.get("length") or 1
            frac = max(0.0, min(1.0, 1 - self._focus_remaining() / total))
            color = t["accent"] if f["mode"] == "focus" else "#43a047"
            if frac > 0:
                d.arc(box, -90, -90 + 360 * frac, fill=color, width=thick)
        img = img.resize((size, size), Image.LANCZOS)
        self._ring_img = ImageTk.PhotoImage(img, master=self.root)
        c.delete("all")
        cx, cy = w / 2, h / 2
        c.create_image(cx, cy, image=self._ring_img)
        m = self.mode
        if running:
            remaining = self._focus_remaining()
            label = "FOCUS" if f["mode"] == "focus" else "BREAK"
            if f["paused"] is not None:
                label = "PAUSED"
            sub = (f"session {f['cycle'] % max(1, m['every']) + 1} of {m['every']}"
                   if f["mode"] == "focus" else "breathe")
        else:
            remaining = m["focus"] * 60
            label, sub = "READY", m["name"]
        c.create_text(cx, cy - size * 0.2, text=label, fill=t["muted"], font=self.fonts["section"])
        c.create_text(cx, cy, text=mmss(remaining), fill=t["text"], font=self.fonts["big_timer"])
        c.create_text(cx, cy + size * 0.2, text=sub, fill=t["muted"], font=self.fonts["small"])

        if hasattr(self, "focus_main_btn") and self.focus_main_btn.winfo_exists():
            main = "Start" if not running else ("Resume" if f["paused"] is not None else "Pause")
            self.focus_main_btn.set_text(main)
            today = datetime.now().date().isoformat()
            n = f["log"].get(today, 0)
            mins = f["minutes"].get(today, 0)
            self.focus_stats.configure(
                text=f"Today: {n} session{'' if n == 1 else 's'} · {hours_minutes(mins)} focused")

    def render_focus_modes(self):
        if not hasattr(self, "modes_frame") or not self.modes_frame.winfo_exists():
            return
        for w in self.modes_frame.winfo_children():
            w.destroy()
        options = [(m["id"], f"{m['name']}  {m['focus']}/{m['brk']}")
                   for m in self.settings["focus_modes"]]
        options.append(("__new__", "+ New mode"))

        def pick(v):
            if v == "__new__":
                self._edit_mode(None)
            else:
                self.settings["focus_mode"] = v
                self.save()
                self.render_focus_modes()
                self.render_focus_ring()

        def on_menu(e, v):
            if v == "__new__":
                return
            items = [("Edit", lambda: self._edit_mode(v))]
            if len(self.settings["focus_modes"]) > 1:
                items.append(("Delete", lambda: self._delete_mode(v)))
            self.menu(items, e.x_root, e.y_root)

        self.chips(self.modes_frame, options, self.settings["focus_mode"], pick, per_row=2,
                   on_menu=on_menu).pack(fill="x")
        tk.Label(self.modes_frame, text="Right-click a mode to edit it. Numbers are focus/break minutes.",
                 bg=self.t["bg"], fg=self.t["muted"], font=self.fonts["small"], anchor="w").pack(
            fill="x", pady=(2, 0))

    def _edit_mode(self, mode_id):
        t = self.t
        ed = self.mode_editor
        for w in ed.winfo_children():
            w.destroy()
        mode = next((m for m in self.settings["focus_modes"] if m["id"] == mode_id), None)
        values = mode or dict(name="", focus=30, brk=5, long=15, every=4)
        card = ui.RoundedFrame(ed, fill=t["entry"], bg=t["bg"], radius=12, border=t["border"],
                               pad=10, scale=self.scale)
        card.pack(fill="x", pady=(8, 0))
        inner = card.inner
        tk.Label(inner, text="Edit mode" if mode else "New mode", bg=t["entry"], fg=t["text"],
                 font=self.fonts["ui_bold"], anchor="w").grid(row=0, column=0, columnspan=4,
                                                               sticky="w")
        fields = {}

        def field(row, col, label, key, width=5):
            tk.Label(inner, text=label, bg=t["entry"], fg=t["muted"],
                     font=self.fonts["small"]).grid(row=row, column=col, sticky="w", pady=2)
            e = self.entry(inner, width=width, rounded=True)
            e.insert(0, str(values[key]))
            e.outer.grid(row=row, column=col + 1, sticky="ew" if key == "name" else "w",
                         padx=(4, 10), pady=2, columnspan=3 if key == "name" else 1)
            fields[key] = e

        field(1, 0, "Name", "name", width=18)
        field(2, 0, "Focus min", "focus")
        field(2, 2, "Break min", "brk")
        field(3, 0, "Long break", "long")
        field(3, 2, "Every N", "every")
        inner.columnconfigure(1, weight=1)
        msg = tk.Label(inner, text="", bg=t["entry"], fg=t["danger"], font=self.fonts["small"],
                       anchor="w")
        msg.grid(row=4, column=0, columnspan=4, sticky="w")

        def save():
            name = fields["name"].get().strip() or "My mode"
            try:
                nums = {k: int(fields[k].get()) for k in ("focus", "brk", "long", "every")}
            except ValueError:
                msg.configure(text="Use whole numbers for the minutes.")
                return
            if not (1 <= nums["focus"] <= 240 and 1 <= nums["brk"] <= 120
                    and 1 <= nums["long"] <= 180 and 1 <= nums["every"] <= 12):
                msg.configure(text="Focus 1–240, breaks 1–180 min, every 1–12 sessions.")
                return
            if mode:
                mode.update(name=name, **nums)
                self.settings["focus_mode"] = mode["id"]
            else:
                new = dict(id=uuid.uuid4().hex, name=name, **nums)
                self.settings["focus_modes"].append(new)
                self.settings["focus_mode"] = new["id"]
            self.save()
            close()
            self.render_focus_modes()
            self.render_focus_ring()

        def close():
            for w in ed.winfo_children():
                w.destroy()

        btns = tk.Frame(inner, bg=t["entry"])
        btns.grid(row=5, column=0, columnspan=4, sticky="e", pady=(6, 0))
        self.button(btns, "Cancel", close, bg=t["bg"], font="small").pack(side="right", padx=(6, 0))
        self.button(btns, "Save", save, bg=t["accent"], fg=colors.readable_on(t["accent"]),
                    hover=colors.mix(t["accent"], "#000000", 0.12),
                    font="small_bold").pack(side="right")
        fields["name"].focus_set()
        card.after_idle(card.fit)

    def _delete_mode(self, mode_id):
        s = self.settings
        s["focus_modes"] = [m for m in s["focus_modes"] if m["id"] != mode_id]
        if s["focus_mode"] == mode_id:
            s["focus_mode"] = s["focus_modes"][0]["id"]
        self.save()
        self.render_focus_modes()
        self.render_focus_ring()

    # ---- notepad

    @property
    def notes(self):
        return self.data["notes"]

    def _note_page(self):
        return next(pg for pg in self.notes["pages"] if pg["id"] == self.notes["current"])

    def _load_note_page(self):
        txt = self.note_text
        txt.delete("1.0", "end")
        txt.insert("1.0", self._note_page()["text"])
        txt.edit_reset()
        txt.edit_modified(False)

    def _note_modified(self, _e=None):
        if not self.note_text.edit_modified():
            return
        self.note_text.edit_modified(False)
        if self._notes_save_after:
            self.root.after_cancel(self._notes_save_after)
        self._notes_save_after = self.root.after(500, self._save_note)

    def _save_note(self):
        self._notes_save_after = None
        if hasattr(self, "note_text") and self.note_text.winfo_exists():
            self._note_page()["text"] = self.note_text.get("1.0", "end-1c")
            self.save()

    def render_note_pages(self):
        t = self.t
        frame = self.note_pages
        for w in frame.winfo_children():
            w.destroy()
        for pg in self.notes["pages"]:
            sel = pg["id"] == self.notes["current"]
            chip = tk.Label(frame, text=pg["title"], cursor="hand2", font=self.fonts["small_bold"]
                            if sel else self.fonts["small"],
                            bg=t["active"] if sel else t["entry"],
                            fg=t["header_text"] if sel else t["text"], padx=7, pady=2)
            chip.pack(side="left", padx=(0, 3))
            chip.bind("<Button-1>", lambda e, i=pg["id"]: self.switch_note_page(i))
            chip.bind("<Double-Button-1>", lambda e, i=pg["id"], c=chip: self._rename_note_page(i, c))
            chip.bind("<Button-3>", lambda e, i=pg["id"], c=chip: self._note_page_menu(e, i, c))
        self.icon_button(frame, Icon.ADD, self.add_note_page, small=True,
                         hover_fg=t["accent"]).pack(side="left")

    def switch_note_page(self, page_id):
        if page_id == self.notes["current"]:
            return
        self._save_note()
        self.notes["current"] = page_id
        self.save()
        self._load_note_page()
        self.render_note_pages()

    def add_note_page(self):
        self._save_note()
        n = len(self.notes["pages"]) + 1
        page = {"id": uuid.uuid4().hex, "title": f"Note {n}", "text": ""}
        self.notes["pages"].append(page)
        self.notes["current"] = page["id"]
        self.save()
        self._load_note_page()
        self.render_note_pages()
        self.note_text.focus_set()

    def _note_page_menu(self, e, page_id, chip):
        items = [("Rename", lambda: self._rename_note_page(page_id, chip))]
        if len(self.notes["pages"]) > 1:
            items.append(("Delete page", lambda: self.delete_note_page(page_id)))
        self.menu(items, e.x_root, e.y_root)

    def _rename_note_page(self, page_id, chip):
        page = next(pg for pg in self.notes["pages"] if pg["id"] == page_id)
        e = self.entry(self.note_pages, width=10)
        e.insert(0, page["title"])
        e.pack(before=chip, side="left", padx=(0, 3))
        chip.pack_forget()
        self.root.focus_force()
        e.focus_set()
        e.select_range(0, "end")
        done = []

        def finish(keep):
            if done:
                return
            done.append(True)
            if keep and e.get().strip():
                page["title"] = e.get().strip()[:20]
                self.save()
            self.render_note_pages()

        e.bind("<Return>", lambda ev: finish(True))
        e.bind("<Escape>", lambda ev: finish(False))
        e.bind("<FocusOut>", lambda ev: finish(True))

    def delete_note_page(self, page_id):
        pages = self.notes["pages"]
        self.notes["pages"] = [pg for pg in pages if pg["id"] != page_id]
        if self.notes["current"] == page_id:
            self.notes["current"] = self.notes["pages"][0]["id"]
        self.save()
        self._load_note_page()
        self.render_note_pages()

    def copy_note(self):
        txt = self.note_text
        try:
            content = txt.get("sel.first", "sel.last")
        except tk.TclError:
            content = txt.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(content)

    def _note_return(self, _e):
        """Enter after a line ending in '=' writes the answer, like a calculator."""
        txt = self.note_text
        line_no = int(txt.index("insert").split(".")[0])
        line = txt.get(f"{line_no}.0", f"{line_no}.end")
        if line.rstrip().endswith("=") and line.strip() != "=":
            expr = line.rstrip()[:-1]
            names = calc.scan_names(txt.get("1.0", f"{line_no}.0").splitlines())
            value = calc.evaluate(expr, names)
            if value is not None:
                txt.mark_set("insert", f"{line_no}.end")
                txt.insert("insert", " " + calc.fmt(value))
        return None  # let Tk insert the newline

    def _move_line(self, direction):
        txt = self.note_text
        line_no, col = (int(x) for x in txt.index("insert").split("."))
        last = int(txt.index("end-1c").split(".")[0])
        other = line_no + direction
        if not 1 <= other <= last:
            return "break"
        cur_text = txt.get(f"{line_no}.0", f"{line_no}.end")
        other_text = txt.get(f"{other}.0", f"{other}.end")
        txt.edit_separator()
        txt.delete(f"{line_no}.0", f"{line_no}.end")
        txt.insert(f"{line_no}.0", other_text)
        txt.delete(f"{other}.0", f"{other}.end")
        txt.insert(f"{other}.0", cur_text)
        txt.mark_set("insert", f"{other}.{min(col, len(cur_text))}")
        txt.see("insert")
        return "break"

    # ---- music

    def _apply_music_source(self):
        source = self.settings["music"]
        self.media.set_source(source)
        if source != "off":
            self.media.start()
        else:
            self.now_playing = None

    def _has_track(self):
        info = self.now_playing
        return bool(info and (info["title"] or info["artist"]))

    def render_music(self):
        self._schedule_now_playing()
        if not hasattr(self, "music_frame") or not self.music_frame.winfo_exists():
            return
        t = self.t
        dbg, dtext, dmuted = t["dock"], t["dock_text"], t["dock_muted"]
        mf = self.music_frame
        for w in mf.winfo_children():
            w.destroy()
        source = self.settings["music"]
        if source == "off" or not media.AVAILABLE:
            return
        info = self.now_playing
        if not self._has_track():
            if source in ("spotify", "apple"):
                name = dict(media.SOURCES)[source]
                self.button(mf, Icon.MUSIC, lambda: media.open_player(source), bg=dbg, fg=dtext,
                            hover=colors.mix(dbg, dtext, 0.1), font="icon", padx=2).pack(side="left")
                self.button(mf, f"Open {name}", lambda: media.open_player(source), bg=dbg,
                            fg=t["accent"] if dbg == t["bg"] else dtext,
                            hover=colors.mix(dbg, dtext, 0.1), font="small_bold").pack(side="left")
            else:
                tk.Label(mf, text=f"{Icon.MUSIC}  ", bg=dbg, fg=dmuted,
                         font=self.fonts["icon_small"]).pack(side="left")
                tk.Label(mf, text="Nothing playing", bg=dbg, fg=dmuted,
                         font=self.fonts["small"]).pack(side="left")
            return

        for glyph, cmd in ((Icon.NEXT, "next"), (Icon.PAUSE if info["playing"] else Icon.PLAY, "toggle"),
                           (Icon.PREV, "prev")):
            self.icon_button(mf, glyph, lambda c=cmd: self._music_cmd(c), bg=dbg, fg=dtext,
                             hover_fg=t["accent"]).pack(side="right")

        clickables = []
        if self.settings["dock_art"]:
            art = self._art_photo(info.get("art"), int(32 * self.scale))
            if art:
                lbl = tk.Label(mf, image=art, bg=dbg, bd=0, cursor="hand2")
                lbl.pack(side="left", padx=(0, 7))
                clickables.append(lbl)
        text = tk.Frame(mf, bg=dbg)
        text.pack(side="left", fill="x", expand=True)
        title = tk.Label(text, text=info["title"] or "Unknown", bg=dbg, fg=dtext,
                         font=self.fonts["small_bold"], anchor="w", cursor="hand2")
        title.pack(fill="x")
        artist = tk.Label(text, text=self._artist_line(info), bg=dbg, fg=dmuted,
                          font=self.fonts["small"], anchor="w", cursor="hand2")
        artist.pack(fill="x")
        for w in clickables + [title, artist]:
            w.bind("<Button-1>", lambda e: self._open_music_view())

    def _open_music_view(self):
        if "music" in self.settings["tabs"]:
            self.show_panel("music")
        else:
            media.open_player(self._player_target())

    def _artist_line(self, info):
        sub = info["artist"]
        app = media.app_label(info["app"])
        if app and app != "Browser":
            sub = f"{sub} · {app}" if sub else app
        return sub

    def _player_target(self):
        source = self.settings["music"]
        if source in ("spotify", "apple"):
            return source
        app = media.app_label(self.now_playing["app"]) if self.now_playing else ""
        return "apple" if app == "Apple Music" else "spotify"

    def _music_cmd(self, cmd):
        self.media.command(cmd)
        if cmd == "toggle" and self.now_playing:  # instant feedback; the poll confirms
            self.now_playing = dict(self.now_playing, playing=not self.now_playing["playing"])
            self.render_music()

    def _art_image(self, data):
        if not data:
            return None
        key = ("img", id(data))
        if key not in self._art_cache:
            try:
                from PIL import Image
                self._art_cache = {k: v for k, v in self._art_cache.items() if k[1] == id(data)}
                self._art_cache[key] = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception:
                return None
        return self._art_cache[key]

    def _art_photo(self, data, size):
        img = self._art_image(data)
        if img is None:
            return None
        key = ("thumb", id(data), size)
        if key not in self._art_cache:
            from PIL import Image, ImageTk
            thumb = ui.round_corners(img.resize((size, size), Image.LANCZOS),
                                     max(3, size // 6), self.t["dock"])
            self._art_cache[key] = ImageTk.PhotoImage(thumb, master=self.root)
        return self._art_cache[key]

    def _schedule_now_playing(self):
        if self._np_after is None:
            self._np_after = self.root.after(16, self.render_now_playing)

    def _schedule_ring(self):
        if self._ring_after is None:
            self._ring_after = self.root.after(16, self._ring_now)

    def _ring_now(self):
        self._ring_after = None
        self.render_focus_ring()

    def render_now_playing(self):
        """Lock-screen style view: blurred cover background, big cover, title, controls."""
        self._np_after = None
        if (self.data["panel"] != "music" or not hasattr(self, "np_canvas")
                or not self.np_canvas.winfo_exists()):
            return
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk
        c = self.np_canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 50:
            return
        t = self.t
        info = self.now_playing if self._has_track() else None
        art = self._art_image(info.get("art")) if info else None

        if art:
            # cover blurred + dimmed once per track at a small size, then scaled to fill
            if not self._np_blur or self._np_blur[0] is not art:
                small = art.resize((160, 160), Image.BILINEAR).filter(ImageFilter.GaussianBlur(9))
                self._np_blur = (art, ImageEnhance.Brightness(small).enhance(0.55))
            blur = self._np_blur[1]
            side = max(w, h)
            bg = blur.resize((side, side), Image.BILINEAR)
            left, top = (side - w) // 2, (side - h) // 2
            bg = bg.crop((left, top, left + w, top + h))
        else:
            top_c, bot_c = colors.to_rgb(colors.mix(t["header"], "#000000", 0.55)), (17, 17, 17)
            bg = Image.new("RGB", (w, h))
            d = ImageDraw.Draw(bg)
            for y in range(h):
                k = y / max(1, h - 1)
                d.line((0, y, w, y), fill=tuple(int(a + (b - a) * k) for a, b in zip(top_c, bot_c)))

        cover = int(min(w - 56 * self.scale, h - 170 * self.scale, 360 * self.scale))
        cover = max(cover, int(60 * self.scale))
        cx = w // 2
        cy = int(max(20 * self.scale, (h - cover - 130 * self.scale) / 2)) + cover // 2
        if art:
            ss = 3
            radius = int(14 * self.scale)
            # soft shadow
            shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle(
                (cx - cover // 2, cy - cover // 2 + 8, cx + cover // 2, cy + cover // 2 + 8),
                radius, fill=(0, 0, 0, 150))
            shadow = shadow.filter(ImageFilter.GaussianBlur(int(12 * self.scale)))
            bg = bg.convert("RGBA")
            bg.alpha_composite(shadow)
            mask = Image.new("L", (cover * ss, cover * ss), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, cover * ss - 1, cover * ss - 1),
                                                   radius * ss, fill=255)
            mask = mask.resize((cover, cover), Image.LANCZOS)
            bg.paste(art.resize((cover, cover), Image.LANCZOS), (cx - cover // 2, cy - cover // 2), mask)
            bg = bg.convert("RGB")

        self._np_img = ImageTk.PhotoImage(bg, master=self.root)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._np_img)

        text_y = cy + cover // 2 + int(26 * self.scale)
        if info:
            if not art:
                c.create_text(cx, cy, text=Icon.MUSIC, fill="#ffffff", font=self.fonts["icon_big"])
            c.create_text(cx, text_y, text=info["title"] or "Unknown", fill="#ffffff",
                          font=self.fonts["subtitle"], width=w - 30, justify="center")
            c.create_text(cx, text_y + int(24 * self.scale), text=self._artist_line(info),
                          fill="#d9d9d9", font=self.fonts["ui"], width=w - 30, justify="center")
            y = text_y + int(64 * self.scale)
            gap = int(64 * self.scale)
            for dx, glyph, cmd, font in ((-gap, Icon.PREV, "prev", "subtitle"),
                                         (0, Icon.PAUSE if info["playing"] else Icon.PLAY,
                                          "toggle", "title"),
                                         (gap, Icon.NEXT, "next", "subtitle")):
                tag = f"btn_{cmd}"
                c.create_text(cx + dx, y, text=glyph, fill="#ffffff", tags=(tag,),
                              font=(self.icon_family, self.fonts[font].cget("size") + 4))
                c.tag_bind(tag, "<Button-1>", lambda e, cm=cmd: self._music_cmd(cm))
                c.tag_bind(tag, "<Enter>", lambda e: c.configure(cursor="hand2"))
                c.tag_bind(tag, "<Leave>", lambda e: c.configure(cursor=""))
        else:
            c.create_text(cx, cy, text=Icon.MUSIC, fill="#ffffff", font=self.fonts["icon_big"])
            c.create_text(cx, text_y, text="Nothing playing", fill="#ffffff",
                          font=self.fonts["subtitle"])
            source = self.settings["music"]
            if source == "off":
                hint = "Music is off — turn it on in Settings"
            elif source in ("spotify", "apple"):
                hint = f"Open {dict(media.SOURCES)[source]}"
            else:
                hint = "Play something in Spotify, Apple Music or a browser"
            c.create_text(cx, text_y + int(26 * self.scale), text=hint, fill="#cfcfcf",
                          font=self.fonts["ui"], width=w - 30, justify="center", tags=("open",))
            if source in ("spotify", "apple"):
                c.tag_bind("open", "<Button-1>", lambda e: media.open_player(source))
                c.tag_bind("open", "<Enter>", lambda e: c.configure(cursor="hand2"))
                c.tag_bind("open", "<Leave>", lambda e: c.configure(cursor=""))

    # ---- calendar feeds

    def _pick_new_feed_lead(self):
        def pick(v):
            self.feed_lead = v
            self.lead_btn.set_text(f"Remind {dict(LEADS)[v]} ▾")
        self.popup_menu(self.lead_btn, LEADS, pick)

    def add_feed(self):
        url = ical_feeds.normalize_url(self.value(self.feed_url))
        if not url.lower().startswith(("http://", "https://")):
            self.feed_msg.configure(text="Paste the full calendar link (starts with https:// or webcal://).",
                                    fg=self.t["danger"])
            return
        canvas = "instructure" in url
        name = self.value(self.feed_name) or ("Canvas" if canvas else "Calendar")
        feed = {"id": uuid.uuid4().hex, "name": name, "url": url, "lead": self.feed_lead,
                "hidden": [], "error": None, "last_sync": None,
                "homework_only": canvas or name.lower() == "canvas"}
        self.data["feeds"].append(feed)
        self.feed_name.delete(0, "end")
        self.feed_url.delete(0, "end")
        self.feed_msg.configure(text=f"Added {name}. Syncing…", fg=self.t["accent"])
        self.save()
        self.sync_feeds([feed["id"]])

    def remove_feed(self, fid):
        self.data["feeds"] = [f for f in self.data["feeds"] if f["id"] != fid]
        for r in [r for r in self.data["reminders"] if r.get("source") == fid]:
            self._close_alert(r["id"])
        self.data["reminders"] = [r for r in self.data["reminders"] if r.get("source") != fid]
        self.feed_cache.pop(fid, None)
        self.save()
        self.render_feeds()
        self.refresh()

    def change_feed_lead(self, fid, widget):
        def pick(v):
            feed = self._find_feed(fid)
            if feed:
                feed["lead"] = v
                self._reapply_feed(fid)
        self.popup_menu(widget, LEADS, pick)

    def toggle_homework_only(self, fid):
        feed = self._find_feed(fid)
        if feed:
            feed["homework_only"] = not feed.get("homework_only")
            self._reapply_feed(fid)

    def _reapply_feed(self, fid):
        if fid in self.feed_cache:
            self.apply_feed(fid, self.feed_cache[fid], None)
        else:
            self.save()
            self.sync_feeds([fid])

    def _auto_sync(self):
        self.sync_feeds()
        self.root.after(SYNC_MS, self._auto_sync)

    def sync_feeds(self, ids=None):
        for feed in self.data["feeds"]:
            fid = feed["id"]
            if (ids and fid not in ids) or fid in self.syncing:
                continue
            self.syncing.add(fid)
            threading.Thread(target=self._sync_worker, args=(fid, feed["url"]), daemon=True).start()
        self.render_feeds()

    def _sync_worker(self, fid, url):
        try:
            events = ical_feeds.load_events(url, FEED_HORIZON_DAYS)
            self.queue.put(("feed", fid, events, None))
        except Exception as e:  # network, HTTP, parse errors
            self.queue.put(("feed", fid, None, str(e) or type(e).__name__))

    def apply_feed(self, fid, events, error):
        self.syncing.discard(fid)
        feed = self._find_feed(fid)
        if feed is None:
            return
        now = datetime.now()
        if error:
            feed["error"] = error
        else:
            self.feed_cache[fid] = events
            feed["error"] = None
            first_sync = feed.get("last_sync") is None
            feed["last_sync"] = iso(now)
            lead = timedelta(minutes=feed.get("lead", 1440))
            hidden = set(feed.get("hidden", []))
            existing = {r["uid"]: r for r in self.data["reminders"] if r.get("source") == fid}
            others = [r for r in self.data["reminders"] if r.get("source") != fid]
            kept, keys = [], set()
            filtered_out = 0
            for ev in events:
                key = ev["key"]
                keys.add(key)
                if key in hidden:
                    continue
                if feed.get("homework_only") and not ev.get("homework"):
                    filtered_out += 1
                    continue
                base = iso(ev["start"] - lead)
                r = existing.get(key)
                if r is None:
                    # On the very first sync don't fire a burst of alerts for items already in their window.
                    r = {"id": uuid.uuid4().hex, "uid": key, "source": fid, "done": False,
                         "repeat": "none", "due": base, "base_due": base,
                         "fired": first_sync and ev["start"] - lead <= now}
                    if self.data["bubble"] and not first_sync:
                        self.data["unseen_updates"] = self.data.get("unseen_updates", 0) + 1
                elif r.get("base_due") != base:  # event moved or lead time changed
                    r["due"] = r["base_due"] = base
                    r["fired"] = False
                r.update(text=ev["summary"], event_start=iso(ev["start"]),
                         all_day=ev["all_day"], url=ev.get("url"))
                kept.append(r)
            for r in existing.values():
                if r not in kept:
                    self._close_alert(r["id"])
            feed["hidden"] = [k for k in hidden if k in keys]
            feed["count"] = len(kept)
            feed["filtered"] = filtered_out
            self.data["reminders"] = others + kept
            if hasattr(self, "feed_msg") and self.feed_msg.winfo_exists():
                self.feed_msg.configure(text="")
        self.save()
        self.render_feeds()
        self.refresh()

    def render_feeds(self):
        if not hasattr(self, "feeds_frame") or not self.feeds_frame.winfo_exists():
            return
        t = self.t
        ff = self.feeds_frame
        for w in ff.winfo_children():
            w.destroy()
        for feed in self.data["feeds"]:
            fid = feed["id"]
            bg = t["entry"]
            card = ui.RoundedFrame(ff, fill=bg, bg=t["bg"], radius=12, border=t["border"], pad=6,
                                   scale=self.scale)
            card.pack(fill="x", pady=3)
            row = card.inner
            left = tk.Frame(row, bg=bg)
            left.pack(side="left", fill="x", expand=True, padx=8, pady=4)
            tk.Label(left, text=feed["name"], bg=bg, fg=t["text"],
                     font=self.fonts["ui_bold"], anchor="w").pack(fill="x")
            if fid in self.syncing:
                status, color = "Syncing…", t["muted"]
            elif feed.get("error"):
                status, color = "Couldn't sync: " + feed["error"][:80], t["danger"]
            elif feed.get("last_sync"):
                synced = format_due(datetime.fromisoformat(feed["last_sync"])).lower()
                status = f"{feed.get('count', 0)} upcoming · synced {synced}"
                if feed.get("homework_only") and feed.get("filtered"):
                    status += f" · {feed['filtered']} non-homework hidden"
                color = t["muted"]
            else:
                status, color = "Not synced yet", t["muted"]
            tk.Label(left, text=status, bg=bg, fg=color, font=self.fonts["small"],
                     anchor="w", justify="left", wraplength=int(190 * self.scale)).pack(fill="x")
            lead = tk.Label(left, text=f"Remind {dict(LEADS).get(feed.get('lead', 1440), '')} ▾",
                            bg=bg, fg=t["accent"], font=self.fonts["small"],
                            anchor="w", cursor="hand2")
            lead.pack(fill="x")
            lead.bind("<Button-1>", lambda e, f=fid, w=lead: self.change_feed_lead(f, w))
            self.checkbox(left, "Homework only", feed.get("homework_only", False),
                          lambda f=fid: self.toggle_homework_only(f), bg=bg).pack(fill="x")
            self.icon_button(row, Icon.REMOVE, lambda f=fid: self.remove_feed(f), bg=bg,
                             small=True, hover_fg=t["danger"]).pack(side="right", anchor="n", pady=4)
            self.icon_button(row, Icon.SYNC, lambda f=fid: self.sync_feeds([f]), bg=bg,
                             small=True, hover_fg=t["accent"]).pack(side="right", anchor="n", pady=4)
            card.after_idle(card.fit)


def main():
    pu.set_dpi_aware()
    if pu.already_running():
        pu.signal_existing_instance()
        return
    pu.migrate_old_startup()
    root = tk.Tk()
    StickyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
