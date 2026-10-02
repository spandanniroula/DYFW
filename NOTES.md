# DYFW — project notes

**DYFW (Do Your Fucken Work)**: an always-on-top Windows sticky note built with Python and tkinter.

## Build
- Run `build.bat`. The exe lands at `dist\DYFW.exe`.
- Python is at `%LOCALAPPDATA%\Programs\Python\Python312` (it isn't on PATH).
- Your data lives in `%APPDATA%\DYFW\data.json`.

## Files
| File | What it does |
|---|---|
| `sticky_note.py` | Main app: UI, tasks, reminders, focus timer, notepad, settings |
| `ui.py` | Rounded buttons, cards, switches |
| `listview.py` | Fast canvas lists, for smooth resizing |
| `media.py` | Spotify / Apple Music now-playing and controls |
| `ical_feeds.py` | Canvas / Google / Outlook calendar feeds |
| `timeparse.py` | Plain-English dates ("essay due fri 5pm") |
| `calc.py` | Notepad calculator |
| `colors.py` | Color helpers, custom themes, color wheel |
| `platform_utils.py` | Tray icon, start with Windows, single instance, rounded window corners |

## Recent changes (2026-10-02)
- Tasks with a time ("call mom 3pm") pop up an alarm like reminders; date-only deadlines don't.
- Tabs moved to a vertical rail on the left (hover an icon for its name).
- Text shrinks in steps when the note is made narrow; your chosen text size is the max.
- Bubble defaults to the screen's top-right corner (a dragged spot is remembered).
- Pushed against a screen edge, the note tucks away to a thin strip and slides out on hover.
- Auto-hide slides the rail; music controls stay visible.
- Bubble redesigned: Apple-Watch-style progress ring (per-pixel-alpha window, `bubble.py`).
- The rail sits on the side facing the screen's middle (flips when dragged across it).

## To do (2026-10-03)
- [ ] Brainstorm and replace the bubble icon
- [ ] Wrap up, add a `.gitignore` (`build/`, `dist/`, `*.spec`, `icon.ico`), then upload to GitHub

## Known limit
Brave and Chrome report only one audio source per browser, so Spotify playing in a browser tab can't take priority over YouTube in another tab. The Spotify desktop app fixes this.
