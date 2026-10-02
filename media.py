"""Now-playing + transport controls for Spotify / Apple Music via Windows media sessions.

Both apps (and their web players in Chrome/Edge) publish to the Windows
"System Media Transport Controls", so no logins or API keys are needed.
"""

import asyncio
import os
import subprocess
import threading
import webbrowser

try:
    import winreg
except ImportError:
    winreg = None

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _Status,
    )
    from winrt.windows.storage.streams import DataReader
    AVAILABLE = True
except Exception:  # missing package or unsupported Windows
    AVAILABLE = False

SOURCES = [("off", "Off"), ("auto", "Auto"), ("spotify", "Spotify"), ("apple", "Apple Music")]
_MATCH = {"spotify": ("spotify",), "apple": ("applemusic", "itunes")}
_APPLE_MUSIC_AUMID = "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"
POLL_SECONDS = 1.0


class MediaController:
    """Polls the active media session in a background asyncio thread.

    `post(info)` is called (from that thread) whenever what's playing changes;
    info is None or a dict with app, title, artist, playing, art (image bytes or None).
    """

    def __init__(self, post):
        self.post = post
        self.source = "auto"
        self._loop = None
        self._mgr = None
        self._last_key = ()
        self._art_key = None
        self._art = None

    def start(self):
        if AVAILABLE and self._loop is None:
            threading.Thread(target=self._run, daemon=True).start()

    def set_source(self, source):
        self.source = source
        self._last_key = ()  # force a fresh post

    def command(self, cmd):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._command(cmd), self._loop)

    # ---- background thread

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._poll_forever())

    async def _manager(self):
        if self._mgr is None:
            self._mgr = await _Manager.request_async()
        return self._mgr

    async def _pick(self, mgr):
        sessions = list(mgr.get_sessions())
        if not sessions:
            return mgr.get_current_session()
        # Music sites (Spotify/Apple Music web players) fill in an album; YouTube etc. don't.
        has_album = {}
        for s in sessions:
            try:
                props = await s.try_get_media_properties_async()
                has_album[id(s)] = bool(props.album_title)
            except Exception:
                has_album[id(s)] = False
        return pick_session(sessions, self.source, _is_playing, lambda s: has_album[id(s)])

    async def _poll_forever(self):
        while True:
            if self.source != "off":
                try:
                    info = await self._snapshot()
                except Exception:
                    info, self._mgr = None, None
                key = info and (info["app"], info["title"], info["artist"], info["playing"])
                if key != self._last_key:
                    self._last_key = key
                    self.post(info)
            await asyncio.sleep(POLL_SECONDS)

    async def _snapshot(self):
        session = await self._pick(await self._manager())
        if session is None:
            return None
        props = await session.try_get_media_properties_async()
        status = session.get_playback_info().playback_status
        info = {
            "app": session.source_app_user_model_id or "",
            "title": props.title or "",
            "artist": props.artist or "",
            "playing": status == _Status.PLAYING,
        }
        art_key = (info["app"], info["title"], info["artist"])
        if art_key != self._art_key:
            self._art_key = art_key
            self._art = await self._read_thumbnail(props.thumbnail)
        info["art"] = self._art
        return info

    async def _read_thumbnail(self, ref):
        if ref is None:
            return None
        try:
            stream = await ref.open_read_async()
            reader = DataReader(stream.get_input_stream_at(0))
            n = await reader.load_async(stream.size)
            return bytes(reader.read_buffer(n))
        except Exception:
            return None

    async def _command(self, cmd):
        try:
            session = await self._pick(await self._manager())
            if session is None:
                return
            action = {"toggle": session.try_toggle_play_pause_async,
                      "next": session.try_skip_next_async,
                      "prev": session.try_skip_previous_async}[cmd]
            await action()
            self._last_key = ()
        except Exception:
            self._mgr = None


def _is_playing(session):
    try:
        return session.get_playback_info().playback_status == _Status.PLAYING
    except Exception:
        return False


def pick_session(sessions, source, is_playing, looks_like_music=lambda s: False):
    """Choose which media session to show when several apps have audio.

    Spotify / Apple Music apps come first, then sources that look like music (they report an
    album, e.g. a web player in another browser), then everything else. In Auto mode
    something actually playing beats something paused; with a specific app chosen, that app
    wins even while paused.
    """
    order = [source] + [k for k in _MATCH if k != source] if source in _MATCH else list(_MATCH)

    def music_rank(s):
        app = (s.source_app_user_model_id or "").lower()
        rank = next((i for i, k in enumerate(order) if any(m in app for m in _MATCH[k])), None)
        if rank is not None:
            return rank
        return len(order) if looks_like_music(s) else len(order) + 1

    def key(s):
        rank = music_rank(s)
        playing = is_playing(s)
        if source in _MATCH:
            return (rank != 0, not playing, rank)
        return (not playing, rank)

    return min(sessions, key=key)


# ---------------------------------------------------------------- launching players

def _has_protocol(name):
    if not winreg:
        return False
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name).Close()
        return True
    except OSError:
        return False


def _apple_music_installed():
    pkg = _APPLE_MUSIC_AUMID.split("!")[0]
    return os.path.isdir(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", pkg))


def open_player(source):
    """Open the desktop app if installed, otherwise its web player."""
    if source == "apple":
        if _apple_music_installed():
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + _APPLE_MUSIC_AUMID])
        else:
            webbrowser.open("https://music.apple.com")
    else:
        if _has_protocol("spotify"):
            os.startfile("spotify:")
        else:
            webbrowser.open("https://open.spotify.com")


def app_label(app_id):
    a = app_id.lower()
    if "spotify" in a:
        return "Spotify"
    if "applemusic" in a or "itunes" in a:
        return "Apple Music"
    if "chrome" in a or "msedge" in a or "firefox" in a or "opera" in a or "brave" in a:
        return "Browser"
    return ""
