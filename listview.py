"""Fast list view drawn on one Canvas.

Every Tk widget on Windows is a real window, so lists built from dozens of Labels/Frames
redraw slowly while the note is being resized. Here each row is a handful of canvas items
that are simply moved and re-wrapped, which keeps resizing smooth.

Rows are dicts:
  {"kind": "section", "text": ...}
  {"kind": "empty", "text": ...}
  {"kind": "item", "key", "text", "done", "meta", "meta_color", "badge": (text, bg, fg) | None,
   "star": None | bool, "open": bool, "delete": bool, "handle": bool,
   "on_toggle", "on_star", "on_open", "on_delete", "on_edit", "on_menu"(event, list, key)}
"""

import tkinter as tk


class CanvasList(tk.Canvas):
    def __init__(self, master, app, bg):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0)
        self.app = app
        self.bg = bg
        self.rows = []
        self.width = 0
        self.total_h = 0
        self.on_reorder = None  # callback(key, target_index) for drag handles
        self._editor = None
        self._drag = None
        self.bind("<Configure>", self._on_configure)

    # ---- public

    def set_rows(self, rows):
        if self._editor:
            return  # don't yank the text box out from under someone typing
        top = self.yview()[0]
        self.delete("all")
        self.rows = rows
        for i, row in enumerate(rows):
            self._make_row(i, row)
        self._layout()
        self.yview_moveto(top)

    def scroll(self, units):
        if self.total_h > self.winfo_height():
            self.yview_scroll(units, "units")

    def begin_edit(self, key):
        row = next((r for r in self.rows if r.get("key") == key), None)
        if row is None or not row.get("on_edit") or self._editor:
            return
        app = self.app
        ids = row["_ids"]
        x, y = self.coords(ids["text"])
        entry = app.entry(self)
        entry.insert(0, row["text"])
        self.itemconfigure(ids["text"], state="hidden")
        win = self.create_window(x, y - 2, anchor="nw", window=entry, width=row["_text_w"])
        self._editor = entry
        app._editing = True
        app.root.focus_force()
        entry.focus_set()
        entry.select_range(0, "end")
        finished = []

        def finish(keep):
            if finished:
                return
            finished.append(True)
            value = entry.get().strip()
            self._editor = None
            app._editing = False
            self.delete(win)
            entry.destroy()
            if keep and value and value != row["text"]:
                row["on_edit"](value)
            elif self.winfo_exists():
                self.itemconfigure(ids["text"], state="normal")

        entry.bind("<Return>", lambda e: finish(True))
        entry.bind("<Escape>", lambda e: finish(False))
        entry.bind("<FocusOut>", lambda e: finish(True))

    # ---- building

    def _make_row(self, i, row):
        app, t, f = self.app, self.app.t, self.app.fonts
        tag = f"r{i}"
        ids = row["_ids"] = {}
        kind = row["kind"]
        if kind == "section":
            ids["text"] = self.create_text(0, 0, anchor="nw", text=row["text"].upper(),
                                           fill=t["muted"], font=f["section"], tags=(tag,))
            return
        if kind == "empty":
            ids["text"] = self.create_text(0, 0, anchor="n", text=row["text"], fill=t["muted"],
                                           font=f["small"], justify="center", tags=(tag,))
            return

        done = row.get("done")
        ids["bg"] = self.create_rectangle(0, 0, 0, 0, fill=self.bg, outline="", tags=(tag,))
        if row.get("handle"):
            ids["handle"] = self.create_text(0, 0, anchor="nw", text="⠿", fill=t["border"],
                                             font=("Segoe UI Symbol", 9), tags=(tag,))
            self._hover(ids["handle"], t["border"], t["muted"], cursor="fleur")
            self.tag_bind(ids["handle"], "<ButtonPress-1>", lambda e: self._drag_start(i))
            self.tag_bind(ids["handle"], "<B1-Motion>", self._drag_motion)
            self.tag_bind(ids["handle"], "<ButtonRelease-1>", self._drag_end)
        ids["box"] = self.create_text(0, 0, anchor="nw",
                                      text=app.icon_char("BOX_CHECKED" if done else "BOX"),
                                      fill=t["done"] if done else t["accent"], font=f["icon_box"],
                                      tags=(tag,))
        self._hover(ids["box"], None, None)
        self.tag_bind(ids["box"], "<Button-1>", lambda e: row["on_toggle"]())
        if row.get("meta"):
            ids["meta"] = self.create_text(0, 0, anchor="nw", text=row["meta"],
                                           fill=t["done"] if done else row.get("meta_color") or t["accent"],
                                           font=f["small_bold"], tags=(tag,))
        ids["text"] = self.create_text(0, 0, anchor="nw", text=row["text"],
                                       fill=t["done"] if done else t["text"],
                                       font=f["done" if done else "body"], tags=(tag,))
        for key, glyph, base, hover, action in (
                ("delete", "REMOVE", t["muted"], t["danger"], "on_delete"),
                ("star", "STAR_FILLED" if row.get("star") else "STAR",
                 t["accent"] if row.get("star") else t["border"], t["accent"], "on_star"),
                ("open", "OPEN", t["muted"], t["accent"], "on_open")):
            if not row.get(key) and not (key == "star" and row.get("star") is not None):
                continue
            ids[key] = self.create_text(0, 0, anchor="ne", text=app.icon_char(glyph), fill=base,
                                        font=f["icon_small"], tags=(tag,))
            self._hover(ids[key], base, hover)
            self.tag_bind(ids[key], "<Button-1>", lambda e, a=action: row[a]())
        badge = row.get("badge")
        if badge and not done:
            text, bg, fg = badge
            ids["badge_bg"] = self.create_rectangle(0, 0, 0, 0, fill=bg or self.bg, outline="",
                                                    tags=(tag,))
            ids["badge"] = self.create_text(0, 0, anchor="center", text=text, fill=fg,
                                            font=f["badge"], tags=(tag,))

        def click(_e):
            app._click_later(row["on_toggle"])

        def double(_e):
            app._cancel_click()
            if row.get("on_edit"):
                self.begin_edit(row["key"])
            elif row.get("on_open"):
                row["on_open"]()

        for key in ("bg", "meta", "text"):
            if key in ids:
                self.tag_bind(ids[key], "<Button-1>", click)
                self.tag_bind(ids[key], "<Double-Button-1>", double)
                self._hover(ids[key], None, None)
        if row.get("on_menu"):
            self.tag_bind(tag, "<Button-3>", lambda e: row["on_menu"](e, self, row["key"]))

    def _hover(self, item, base, hover, cursor="hand2"):
        def enter(_e):
            self.configure(cursor=cursor)
            if hover:
                self.itemconfigure(item, fill=hover)

        def leave(_e):
            self.configure(cursor="")
            if base:
                self.itemconfigure(item, fill=base)

        self.tag_bind(item, "<Enter>", enter)
        self.tag_bind(item, "<Leave>", leave)

    # ---- layout

    def _on_configure(self, e):
        if e.width != self.width:
            self.width = e.width
            self._layout()
        else:
            self._update_region()

    def _layout(self):
        app = self.app
        s = app.scale
        f = app.fonts
        w = max(self.width, 60)
        pad = int(8 * s)
        row_pad = int(app.row_pad * s) + 1
        icon_w = int(18 * s)
        box_w = int(24 * s)
        handle_w = int(13 * s)
        meta_h = f["small_bold"].metrics("linespace")
        badge_h = f["badge"].metrics("linespace") + 2
        y = int(4 * s)
        for row in self.rows:
            ids = row["_ids"]
            kind = row["kind"]
            if kind == "section":
                y += int(8 * s) if y > int(4 * s) else 0
                self.coords(ids["text"], pad + int(2 * s), y + int(2 * s))
                y += f["section"].metrics("linespace") + int(6 * s)
                continue
            if kind == "empty":
                self.coords(ids["text"], w / 2, y + int(16 * s))
                self.itemconfigure(ids["text"], width=w - int(30 * s))
                bb = self.bbox(ids["text"])
                y = (bb[3] if bb else y) + int(16 * s)
                continue

            top = y + row_pad
            x = pad
            if "handle" in ids:
                self.coords(ids["handle"], x - int(4 * s), top + 1)
                x += handle_w - int(4 * s)
            box_dy = 1 if "meta" not in ids else int(meta_h / 2) - int(2 * s)
            self.coords(ids["box"], x, top + max(0, box_dy))
            x += box_w
            right = w - pad + int(2 * s)
            for key in ("delete", "star", "open"):
                if key in ids:
                    self.coords(ids[key], right, top + int(3 * s))
                    right -= icon_w
            if "badge" in ids:
                bw = f["badge"].measure(self.itemcget(ids["badge"], "text")) + int(9 * s)
                right -= int(3 * s)
                self.coords(ids["badge_bg"], right - bw, top + int(3 * s), right, top + int(3 * s) + badge_h)
                self.coords(ids["badge"], right - bw / 2, top + int(3 * s) + badge_h / 2)
                right -= bw
            text_w = max(40, right - x - int(6 * s))
            row["_text_w"] = text_w
            ty = top
            if "meta" in ids:
                self.coords(ids["meta"], x, ty)
                self.itemconfigure(ids["meta"], width=text_w)
                mb = self.bbox(ids["meta"])  # the date line can wrap when the note is narrow
                ty = max(ty + meta_h, mb[3] if mb else 0)
            self.coords(ids["text"], x, ty)
            self.itemconfigure(ids["text"], width=text_w)
            bb = self.bbox(ids["text"])
            bottom = max(bb[3] if bb else ty, top + box_w) + row_pad
            self.coords(ids["bg"], 0, y, w, bottom)
            row["_y"] = (y, bottom)
            y = bottom
        self.total_h = y + int(6 * s)
        self._update_region()

    def _update_region(self):
        self.configure(scrollregion=(0, 0, self.width, max(self.total_h, self.winfo_height())))

    # ---- drag to reorder

    def _drag_start(self, i):
        self._drag = {"i": i, "target": None, "line": None}
        self.app._drag = True

    def _drag_motion(self, e):
        if not self._drag:
            return
        y = self.canvasy(e.y)
        items = [(i, r) for i, r in enumerate(self.rows) if r["kind"] == "item" and r.get("handle")]
        others = [(i, r) for i, r in items if i != self._drag["i"]]
        target = 0
        for k, (_i, r) in enumerate(others):
            top, bottom = r["_y"]
            if y > (top + bottom) / 2:
                target = k + 1
        self._drag["target"] = target
        if others:
            line_y = others[target - 1][1]["_y"][1] if target > 0 else others[0][1]["_y"][0]
            if self._drag["line"] is None:
                self._drag["line"] = self.create_line(0, line_y, self.width, line_y,
                                                      fill=self.app.t["accent"], width=2)
            else:
                self.coords(self._drag["line"], 0, line_y, self.width, line_y)

    def _drag_end(self, _e):
        drag, self._drag = self._drag, None
        self.app._drag = None
        if not drag:
            return
        if drag["line"]:
            self.delete(drag["line"])
        if drag["target"] is not None and self.on_reorder:
            self.on_reorder(self.rows[drag["i"]]["key"], drag["target"])
