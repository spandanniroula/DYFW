"""Minimal iCalendar (.ics) feed reader for Canvas, Google, Outlook, Moodle, etc."""

import re
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

MAX_BYTES = 20 * 1024 * 1024
ALL_DAY_TIME = (9, 0)  # all-day events are treated as due at 9:00 AM

# Outlook/Exchange feeds often use Windows zone names.
_WINDOWS_ZONES = {
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "US Mountain Standard Time": "America/Phoenix",
    "Pacific Standard Time": "America/Los_Angeles",
    "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central European Standard Time": "Europe/Warsaw",
    "Romance Standard Time": "Europe/Paris",
    "India Standard Time": "Asia/Kolkata",
    "Nepal Standard Time": "Asia/Kathmandu",
    "China Standard Time": "Asia/Shanghai",
    "Tokyo Standard Time": "Asia/Tokyo",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "UTC": "UTC",
}

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def normalize_url(url):
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    return url


def fetch(url, timeout=25):
    req = urllib.request.Request(normalize_url(url), headers={"User-Agent": "DYFW/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Calendar feed is too large")
    text = raw.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        raise ValueError("That link didn't return a calendar (.ics) file")
    return text


def load_events(url, horizon_days=14, now=None):
    now = now or datetime.now()
    return events_from_ics(fetch(url), now, now + timedelta(days=horizon_days))


# ---------------------------------------------------------------- parsing

def _unfold(text):
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    return lines


def _split_prop(line):
    """'DTSTART;TZID=X:2026...' -> ('DTSTART', {'TZID': 'X'}, '2026...')"""
    in_quotes = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return None, {}, ""
    name, *params = head.split(";")
    pdict = {}
    for p in params:
        k, _, v = p.partition("=")
        pdict[k.upper()] = v.strip('"')
    return name.upper(), pdict, value


def _unescape(s):
    return (s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def _zone(tzid):
    if not ZoneInfo or not tzid:
        return None
    for name in (tzid, _WINDOWS_ZONES.get(tzid)):
        if not name:
            continue
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return None


def _parse_dt(value, params):
    """Returns (wall-clock naive datetime, tzinfo or None, all_day)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(hour=ALL_DAY_TIME[0], minute=ALL_DAY_TIME[1]), None, True
    utc = value.endswith("Z")
    v = value.rstrip("Z")
    dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S" if len(v) >= 15 else "%Y%m%dT%H%M")
    tz = timezone.utc if utc else _zone(params.get("TZID"))
    return dt, tz, False


def _to_local(wall, tz):
    if tz is None:
        return wall
    return wall.replace(tzinfo=tz).astimezone().replace(tzinfo=None)


def _add_months(dt, months):
    m = dt.month - 1 + months
    y, m = dt.year + m // 12, m % 12 + 1
    try:
        return dt.replace(year=y, month=m)
    except ValueError:  # e.g. Feb 30
        return None


def _expand_rrule(start, rule, tz, window_end):
    """Yield wall-clock occurrences for common RRULEs (DAILY/WEEKLY/MONTHLY/YEARLY)."""
    parts = dict(p.split("=", 1) for p in rule.upper().split(";") if "=" in p)
    freq = parts.get("FREQ")
    interval = max(1, int(parts.get("INTERVAL", "1") or 1))
    count = int(parts["COUNT"]) if parts.get("COUNT", "").isdigit() else None
    until = None
    if "UNTIL" in parts:
        try:
            u_wall, u_tz, _ = _parse_dt(parts["UNTIL"], {})
            if u_tz is not None and tz is not None:
                u_wall = u_wall.replace(tzinfo=u_tz).astimezone(tz).replace(tzinfo=None)
            elif u_tz is not None:
                u_wall = _to_local(u_wall, u_tz)
            until = u_wall
        except ValueError:
            pass

    def candidates():
        if freq == "DAILY":
            i = 0
            while True:
                yield start + timedelta(days=i * interval)
                i += 1
        elif freq == "WEEKLY":
            days = sorted({_WEEKDAYS[d[-2:]] for d in parts.get("BYDAY", "").split(",")
                           if d[-2:] in _WEEKDAYS}) or [start.weekday()]
            week0 = start - timedelta(days=start.weekday())
            k = 0
            while True:
                for wd in days:
                    occ = week0 + timedelta(weeks=k * interval, days=wd)
                    if occ >= start:
                        yield occ
                k += 1
        elif freq in ("MONTHLY", "YEARLY"):
            step = interval * (12 if freq == "YEARLY" else 1)
            k = 0
            while True:
                occ = _add_months(start, k * step)
                if occ:
                    yield occ
                k += 1
        else:
            yield start

    n = 0
    for occ in candidates():
        if until and occ > until:
            return
        if occ > window_end + timedelta(days=2):
            return
        n += 1
        if count is not None and n > count:
            return
        yield occ
        if n > 5000:
            return


_HOMEWORK_URL_PARTS = ("/assignments/", "/quizzes/", "/discussion_topics/", "/mod/assign/",
                       "/mod/quiz/")
_HOMEWORK_WORDS = re.compile(
    r"\b(homework|hw\d*|assignment|quiz|exam|midterm|final|project|essay|paper|lab|"
    r"problem set|pset|worksheet|due|submission|reading response|discussion post)\b", re.I)


def is_homework(uid, url, summary):
    """Canvas marks assignments in the UID ('event-assignment-123'); others by URL or wording."""
    uid = (uid or "").lower()
    if "assignment" in uid:
        return True
    if "calendar-event" in uid:  # Canvas class/calendar events
        return bool(_HOMEWORK_WORDS.search(summary or ""))
    if url and any(p in url.lower() for p in _HOMEWORK_URL_PARTS):
        return True
    return bool(_HOMEWORK_WORDS.search(summary or ""))


def events_from_ics(text, window_start, window_end):
    """Return upcoming events: dicts with key, summary, start (local naive), all_day, url."""
    raw_events, cur = [], None
    for line in _unfold(text):
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            cur = {"exdates": set()}
        elif upper == "END:VEVENT":
            if cur is not None:
                raw_events.append(cur)
            cur = None
        elif cur is not None:
            name, params, value = _split_prop(line)
            if name == "SUMMARY":
                cur["summary"] = _unescape(value).strip()
            elif name == "UID":
                cur["uid"] = value.strip()
            elif name == "URL":
                cur["url"] = value.strip()
            elif name == "STATUS":
                cur["status"] = value.strip().upper()
            elif name == "RRULE":
                cur["rrule"] = value
            elif name in ("DTSTART", "RECURRENCE-ID", "EXDATE"):
                try:
                    if name == "EXDATE":
                        for v in value.split(","):
                            cur["exdates"].add(_parse_dt(v, params)[0])
                    else:
                        cur[name] = _parse_dt(value, params)
                except ValueError:
                    pass

    overridden = {}
    for ev in raw_events:
        if "RECURRENCE-ID" in ev and "uid" in ev:
            overridden.setdefault(ev["uid"], set()).add(ev["RECURRENCE-ID"][0])

    out = []
    for ev in raw_events:
        if "DTSTART" not in ev or ev.get("status") == "CANCELLED":
            continue
        wall, tz, all_day = ev["DTSTART"]
        uid = ev.get("uid") or f"{ev.get('summary', '')}@{wall.isoformat()}"
        summary = ev.get("summary") or "(untitled event)"

        if "RECURRENCE-ID" in ev:
            occs, key_from = [wall], ev["RECURRENCE-ID"][0]
        elif "rrule" in ev:
            skip = ev["exdates"] | overridden.get(uid, set())
            occs = [o for o in _expand_rrule(wall, ev["rrule"], tz, window_end) if o not in skip]
            key_from = None
        else:
            occs, key_from = [wall], None

        recurring = "rrule" in ev or "RECURRENCE-ID" in ev
        for occ in occs:
            start = _to_local(occ, tz)
            if not (window_start <= start <= window_end):
                continue
            key = f"{uid}|{(key_from or occ).isoformat()}" if recurring else uid
            out.append({"key": key, "summary": summary, "start": start,
                        "all_day": all_day, "url": ev.get("url"),
                        "homework": is_homework(uid, ev.get("url"), summary)})
    out.sort(key=lambda e: e["start"])
    return out
