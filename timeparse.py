"""Parsing and formatting of human-friendly reminder times."""

import re
from datetime import datetime, time, timedelta

_REL_RE = re.compile(r"(?:\+|in\s+)?(\d+)\s*(m|mins?|minutes?|h|hrs?|hours?|d|days?)")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d")
_TIME_FORMATS = ("%H:%M", "%I:%M%p", "%I:%M %p", "%I%p", "%I %p")
DEFAULT_TIME = time(9, 0)


def _parse_time(s):
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


def parse_when(text, now=None):
    """Parse '15:30', '3pm', '+20m', 'in 2h', 'tomorrow 9am', '2026-10-05 14:00', '10/5 9am'."""
    now = now or datetime.now()
    s = text.strip().lower()
    if not s:
        return None

    m = _REL_RE.fullmatch(s)
    if m:
        n, unit = int(m.group(1)), m.group(2)[0]
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
        return (now + delta).replace(second=0, microsecond=0)

    day = None
    for word, offset in (("today", 0), ("tomorrow", 1), ("tmr", 1)):
        if s.startswith(word):
            day = (now + timedelta(days=offset)).date()
            s = s[len(word):].strip()
            break

    if day is None:
        first, _, rest = s.partition(" ")
        for fmt in _DATE_FORMATS:
            try:
                d = datetime.strptime(first, fmt)
            except ValueError:
                continue
            if fmt == "%m/%d":
                d = d.replace(year=now.year)
                if d.date() < now.date():
                    d = d.replace(year=now.year + 1)
            day, s = d.date(), rest.strip()
            break

    t = _parse_time(s) if s else None
    if s and t is None:
        return None
    if t is None:
        if day is None:
            return None
        t = DEFAULT_TIME

    if day is None:
        due = datetime.combine(now.date(), t)
        if due <= now:
            due += timedelta(days=1)
        return due
    return datetime.combine(day, t)


def next_occurrence(due, repeat, now=None):
    """Next time after `now` for a reminder repeating 'daily', 'weekdays' or 'weekly'."""
    now = now or datetime.now()
    step = timedelta(days=7 if repeat == "weekly" else 1)
    nxt = due
    while True:
        nxt += step
        if repeat == "weekdays" and nxt.weekday() >= 5:
            continue
        if nxt > now:
            return nxt


def format_due(due, now=None, all_day=False):
    now = now or datetime.now()
    clock = "" if all_day else " " + due.strftime("%I:%M %p").lstrip("0")
    if due.date() == now.date():
        return "Today" + clock
    if due.date() == (now + timedelta(days=1)).date():
        return "Tomorrow" + clock
    if abs((due.date() - now.date()).days) < 7:
        return due.strftime("%a") + clock
    return due.strftime("%a %b ") + str(due.day) + clock


# ---------------------------------------------------------------- natural language

_WD_FULL = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD_RE = (r"(?:(?P<mod>next|this)\s+)?(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday"
          r"|mon|tues?|wed|thu(?:rs?)?|fri|(?<=on\s)sat|(?<=on\s)sun|(?<=by\s)sat|(?<=by\s)sun)\b")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MON_RE = (r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
           r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_CONNECT = r"(?:\b(?:on|by|due|until|before|at|@)\s+)*"

_REPEAT_PATTERNS = [
    (r"\bevery\s*weekday\b|\bweekdays\b", "weekdays"),
    (r"\bevery\s*day\b|\bdaily\b", "daily"),
    (r"\bevery\s*week\b|\bweekly\b", "weekly"),
]
_REL_ANY = re.compile(r"(?:\bin\s+|\+)(\d+)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)\b")
_DAYWORD = re.compile(_CONNECT + r"\b(today|tonight|tomorrow|tmrw|tmr)\b")
_WEEKDAY = re.compile(_CONNECT + r"\b" + _WD_RE)
_MONTH_DAY = re.compile(_CONNECT + r"\b" + _MON_RE + r"\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\b")
_DAY_MONTH = re.compile(_CONNECT + r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+" + _MON_RE + r"\b")
_ISO_DATE = re.compile(_CONNECT + r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
_SLASH_DATE = re.compile(_CONNECT + r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?\b")
_NAMED_TIME = re.compile(_CONNECT + r"\b(noon|midnight|morning|afternoon|evening|eod|end of day)\b")
_AMPM_TIME = re.compile(_CONNECT + r"\b(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>am|pm|a|p)\b")
_AT_TIME = re.compile(r"(?:\b(?:at|by)\s+|@\s*)(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\b")
_CLOCK_TIME = re.compile(_CONNECT + r"\b(?P<h>\d{1,2}):(?P<mi>\d{2})\b")
_NAMED_TIMES = {"noon": time(12, 0), "midnight": time(23, 59), "morning": time(9, 0),
                "afternoon": time(15, 0), "evening": time(18, 0), "eod": time(23, 59),
                "end of day": time(23, 59)}


def _cut(s, m):
    return (s[:m.start()] + " " + s[m.end():]).strip()


def extract_when(text, now=None, default_time=DEFAULT_TIME):
    """Pull a date/time out of free text.

    'essay due fri 5pm !' -> ('essay', <Fri 17:00>, None, True)
    Returns (clean_text, datetime or None, repeat or None, important).
    """
    now = now or datetime.now()
    s = " " + text.strip() + " "
    low = s.lower()

    important = bool(re.search(r"(^|\s)!+(?=\s|$)", low)) or low.rstrip().endswith("!")
    s = re.sub(r"(^|\s)!+(?=\s|$)", " ", s).rstrip().rstrip("!")
    low = s.lower()

    def take(pattern):
        nonlocal s, low
        m = re.search(pattern, low) if isinstance(pattern, str) else pattern.search(low)
        if m:
            s, low = _cut(s, m), _cut(low, m)
        return m

    repeat = None
    every_day = None
    m = take(r"\bevery\s+(?P<wd>mon|tue|wed|thu|fri|sat|sun)[a-z]*\b")
    if m:
        repeat = "weekly"
        every_day = m.group("wd")
    for pat, rep in _REPEAT_PATTERNS:
        if take(pat):
            repeat = rep

    due = None
    m = take(_REL_ANY)
    if m:
        n, unit = int(m.group(1)), m.group(2)[0]
        mins = {"m": 1, "h": 60, "d": 1440, "w": 10080}[unit] * n
        due = (now + timedelta(minutes=mins)).replace(second=0, microsecond=0)

    day = None
    tonight = False
    from_weekday = False
    if due is None:
        if every_day:
            day, from_weekday = _next_weekday(every_day, None, now), True
        elif (m := take(_DAYWORD)):
            word = m.group(1)
            tonight = word == "tonight"
            day = (now + timedelta(days=0 if word in ("today", "tonight") else 1)).date()
        elif (m := take(_WEEKDAY)):
            day, from_weekday = _next_weekday(m.group("wd"), m.group("mod"), now), True
        elif (m := take(_MONTH_DAY)) or (m := take(_DAY_MONTH)):
            mon = _MONTHS.index(m.group("mon")[:3]) + 1
            day = _safe_date(now.year, mon, int(m.group("day")))
            if day and day < now.date():
                day = _safe_date(now.year + 1, mon, int(m.group("day")))
        elif (m := take(_ISO_DATE)):
            day = _safe_date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        elif (m := take(_SLASH_DATE)):
            y = m.group("y")
            year = (int(y) + 2000 if len(y) == 2 else int(y)) if y else now.year
            day = _safe_date(year, int(m.group("m")), int(m.group("d")))
            if day and not y and day < now.date():
                day = _safe_date(year + 1, int(m.group("m")), int(m.group("d")))

        t = None
        if (m := take(_NAMED_TIME)):
            t = _NAMED_TIMES[m.group(1)]
        elif (m := take(_AMPM_TIME)):
            t = _hm(int(m.group("h")), int(m.group("mi") or 0), m.group("ap"))
        elif (m := take(_AT_TIME)):
            h = int(m.group("h"))
            t = _hm(h, int(m.group("mi") or 0), "p" if 1 <= h <= 7 else None)
        elif (m := take(_CLOCK_TIME)):
            t = _hm(int(m.group("h")), int(m.group("mi")), None)
        if t is None and tonight:
            t = time(20, 0)

        if day is not None or t is not None:
            if day is None:
                due = datetime.combine(now.date(), t)
                if due <= now:
                    due += timedelta(days=1)
            else:
                due = datetime.combine(day, t or default_time)
                if from_weekday and due <= now:  # "fri 9am" said on Friday afternoon
                    due += timedelta(days=7)
                elif tonight and due <= now:  # "tonight" said after 8pm
                    due = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    clean = re.sub(r"\s+", " ", s).strip(" ,-–")
    clean = re.sub(r"\s+\b(on|by|due|at|until|before|every)$", "", clean, flags=re.I).strip(" ,-")
    return clean or text.strip(), due, repeat, important


def _next_weekday(wd_txt, mod, now):
    wd = next(i for i, name in enumerate(_WD_FULL) if name.startswith(wd_txt[:3]))
    ahead = (wd - now.weekday()) % 7
    if mod == "next" and ahead == 0:
        ahead = 7
    return (now + timedelta(days=ahead)).date()


def _safe_date(y, m, d):
    try:
        return datetime(y, m, d).date()
    except ValueError:
        return None


def _hm(h, mi, ap):
    if ap:
        ap = ap[0]
        if h == 12:
            h = 0
        if ap == "p":
            h += 12
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return time(h, mi)


def countdown(target, now=None):
    """Short badge text and urgency level: ('3h', 'urgent'), ('2d', 'soon'), ('late', 'late')."""
    now = now or datetime.now()
    secs = (target - now).total_seconds()
    if secs < 0:
        return "late", "late"
    mins = secs / 60
    if mins < 60:
        return f"{max(1, int(mins))}m", "urgent"
    hours = mins / 60
    if hours < 24:
        return f"{int(hours)}h", "urgent"
    days = hours / 24
    return f"{int(days)}d", "soon" if days < 3 else "later"
