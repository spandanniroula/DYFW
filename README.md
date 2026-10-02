# DYFW — Do Your Fucken Work

An always-on-top sticky note for Windows that keeps your tasks, reminders, homework and focus
timer in one small window — so you actually do your work.

**[Download DYFW.exe](https://github.com/spandanniroula/DYFW/releases/latest)** (Windows 10/11, no install needed)

## Features

- **Tasks** — type naturally: `essay due fri 5pm !` sets a deadline and stars it. Tasks with a
  time (`call mom 3pm`) pop up an alarm. Drag to reorder, countdown badges, priority grid view.
- **Reminders** — `gym every weekday 7am`, `in 20m`, `tomorrow 9am`; flashing pop-ups with snooze.
- **Calendars** — paste an iCal link from Canvas, Google Calendar or Outlook; homework shows up
  with a "homework only" filter for Canvas.
- **Focus timer** — Pomodoro / deep-work modes (or make your own) with a progress ring.
- **Notepad** — plain or "Smart" mode with a built-in calculator (`rent/3=` → answer) and pages.
- **Music** — now playing + controls for Spotify / Apple Music (or anything Windows can control),
  with a lock-screen-style cover view.
- **Stays out of the way** — tucks into the screen edge, auto-hides its toolbar, or shrinks into
  a bubble that shows your progress ring and turns red when something is due.
- **Yours** — themes, a custom color wheel, fonts, text size, opacity, start with Windows.

Your data stays on your PC in `%APPDATA%\DYFW\data.json`.

## Build from source

Needs Python 3.10+ on Windows.

```bat
git clone https://github.com/spandanniroula/DYFW.git
cd DYFW
build.bat
```

The exe ends up in `dist\DYFW.exe`. To run without building: `pip install -r requirements.txt`
then `python sticky_note.py`.

## Project layout

| File | What it does |
|---|---|
| `sticky_note.py` | Main app: UI, tasks, reminders, focus, notepad, settings |
| `ui.py` | Rounded buttons, cards and switches |
| `listview.py` | Fast canvas-drawn lists (smooth resizing) |
| `bubble.py` | The minimized progress-ring bubble |
| `media.py` | Spotify / Apple Music now-playing via Windows media sessions |
| `ical_feeds.py` | Canvas / Google / Outlook calendar feeds |
| `timeparse.py` | Natural-language dates and times |
| `calc.py` | Notepad calculator |
| `colors.py` | Color helpers, custom themes, color picker |
| `platform_utils.py` | Tray icon, start with Windows, rounded / layered windows |

## Known limit

Chromium browsers (Chrome, Brave, Edge) report one audio source per browser, so Spotify playing
in one tab can't be prioritized over YouTube in another tab. The Spotify desktop app doesn't
have this problem.
