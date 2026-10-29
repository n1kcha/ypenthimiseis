#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Υπενθυμίσεις καταστημάτων — τοπικό παράθυρο στα ελληνικά.
Διαβάζει κοινό Google Calendar μέσω μυστικού συνδέσμου ICS (χωρίς login Gmail).
Το «Το είδα» ισχύει μόνο σε ΑΥΤΟ το PC.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import struct
import sys
import threading
import time
import wave
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows needs tzdata for zoneinfo in some setups
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import requests
from icalendar import Calendar
import recurring_ical_events

APP_NAME = "Υπενθυμίσεις καταστημάτων"
POLL_DEFAULT = 30
HELLENIC = ZoneInfo("Europe/Athens") if ZoneInfo else timezone(timedelta(hours=3))


DATA_DIR_NAME = "Ypenthimiseis"


def app_dir() -> Path:
    """Φάκελος δεδομένων (config.json, state.json, chime.wav).

    - Από τον κώδικα (python app.py): ο φάκελος του app.py, όπως πριν.
    - Ως .exe (PyInstaller): %LOCALAPPDATA%\\Ypenthimiseis, που είναι εγγράψιμος
      από τον χρήστη χωρίς admin (εκεί εγκαθιστά και ο εγκαταστάτης).
    """
    if getattr(sys, "frozen", False):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            d = Path(local) / DATA_DIR_NAME
            try:
                d.mkdir(parents=True, exist_ok=True)
                return d
            except Exception:
                pass
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE = app_dir()
CONFIG_PATH = BASE / "config.json"
STATE_PATH = BASE / "state.json"
CHIME_PATH = BASE / "chime.wav"
LOG_PATH = BASE / "app.log"


def log(msg: str) -> None:
    """Μικρό αρχείο καταγραφής (χρήσιμο όταν τρέχει ως .exe χωρίς κονσόλα)."""
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 256 * 1024:
            LOG_PATH.replace(LOG_PATH.with_suffix(".old.log"))
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
            f.flush()
    except Exception:
        pass


_crash_file = None


def install_crash_logging() -> None:
    """Κάθε σφάλμα που δεν πιάστηκε γράφεται στο app.log του φακέλου δεδομένων.

    - Python εξαιρέσεις (κύριο νήμα, άλλα νήματα, callbacks του Tk) → app.log
    - «σκληρά» κρασαρίσματα (π.χ. Tcl_Panic, access violation) → faulthandler στο
      app.log με το traceback όλων των νημάτων.
    - Στο .exe χωρίς κονσόλα sys.stdout/stderr είναι None: πάνε κι αυτά στο app.log."""
    global _crash_file
    import faulthandler
    import traceback

    def log_exc(prefix, et, ev, tb):
        log(f"{prefix}: " + "".join(traceback.format_exception(et, ev, tb)).rstrip())

    sys.excepthook = lambda et, ev, tb: log_exc("unhandled", et, ev, tb)
    threading.excepthook = lambda a: log_exc(
        f"unhandled in thread {getattr(a.thread, 'name', '?')}", a.exc_type, a.exc_value,
        a.exc_traceback)
    try:
        _crash_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_crash_file, all_threads=True)
        if sys.stderr is None:
            sys.stderr = _crash_file
        if sys.stdout is None:
            sys.stdout = _crash_file
    except Exception:
        pass


def tk_report_exception(exc, val, tb) -> None:
    import traceback

    log("tk callback: " + "".join(traceback.format_exception(exc, val, tb)).rstrip())


def ensure_chime_wav(path: Path) -> Path:
    """Απαλό δίφωνο κουδούνι κάθε ~3 δευτ., διάρκεια αρχείου 30 δευτ."""
    if path.exists() and path.stat().st_size > 1000:
        return path
    sr = 22050
    duration = 30.0
    interval = 3.0
    n = int(sr * duration)
    amp = 0.22
    raw = []
    for i in range(n):
        sec = i / sr
        cycle = sec % interval
        v = 0.0
        if cycle < 1.4:
            env = math.exp(-2.4 * cycle) * (1.0 if cycle > 0.01 else cycle / 0.01)
            v += amp * env * math.sin(2 * math.pi * 523.25 * cycle)
            if cycle > 0.12:
                c2 = cycle - 0.12
                env2 = math.exp(-2.4 * c2)
                v += amp * 0.7 * env2 * math.sin(2 * math.pi * 659.25 * c2)
        raw.append(max(-1.0, min(1.0, v)))
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(x * 32767)) for x in raw))
    return path


class SoundPlayer:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self, seconds: int = 30):
        self.stop()
        self._stop = threading.Event()
        wav = ensure_chime_wav(CHIME_PATH)

        def run():
            try:
                if sys.platform.startswith("win"):
                    import winsound

                    winsound.PlaySound(
                        str(wav),
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                    )
                    self._stop.wait(timeout=max(1, seconds))
                    winsound.PlaySound(None, winsound.SND_PURGE)
                else:
                    time.sleep(min(seconds, 1))
            except Exception:
                pass

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if sys.platform.startswith("win"):
            try:
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass



def load_json(path: Path, default):
    try:
        # utf-8-sig: δέχεται και αρχεία με BOM (π.χ. γραμμένα από Σημειωματάριο)
        with path.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def calendar_urls(cfg: dict) -> list[str]:
    urls = []
    extra = cfg.get("ics_urls") or []
    if isinstance(extra, str):
        extra = [extra]
    for u in extra:
        if u and "XXXX" not in str(u):
            urls.append(str(u).strip())
    one = cfg.get("ics_url")
    if one and "XXXX" not in str(one):
        urls.insert(0, str(one).strip())
    # unique, keep order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


CONFIG_DEFAULTS = {
    "store_name": "Κατάστημα",
    "store_id": "",
    "ics_url": "",
    "ics_urls": [],
    "poll_seconds": POLL_DEFAULT,
    "minutes_before": 0,
    "show_missed_max_minutes": 15,
    "sound": True,
    "sound_seconds": 10,
}

STORE_ID_RE = re.compile(r"^[a-z0-9_-]+$")


def apply_defaults(cfg: dict) -> dict:
    cfg = dict(cfg or {})
    for k, v in CONFIG_DEFAULTS.items():
        cfg.setdefault(k, list(v) if isinstance(v, list) else v)
    return cfg


def read_config_raw(path: Path | None = None) -> dict:
    data = load_json(path or CONFIG_PATH, {})
    return data if isinstance(data, dict) else {}


def config_is_complete(cfg: dict) -> bool:
    return bool(calendar_urls(cfg or {}))


def load_config() -> dict:
    cfg = read_config_raw()
    if not config_is_complete(cfg):
        raise SystemExit(
            "Λείπει το config.json με ics_url ή ics_urls.\n"
            "Αντίγραψε το config.example.json σε config.json και βάλε τα μυστικά ICS URL."
        )
    return apply_defaults(cfg)


def build_config(values: dict, existing: dict | None = None) -> tuple[dict, list[str]]:
    """Ελέγχει τα πεδία της φόρμας ρυθμίσεων και φτιάχνει το νέο config.

    values: store_name, store_id, ics_url, ics_urls (κείμενο, ένα ανά γραμμή ή λίστα),
            ics_names ({url: όνομα}, προαιρετικό), sound (bool), sound_seconds (κείμενο/αριθμός).
    Κρατά τα υπόλοιπα πεδία του existing (poll_seconds κ.λπ.).
    Επιστρέφει (config, λίστα λαθών στα ελληνικά).
    """
    errors: list[str] = []
    cfg = apply_defaults(existing or {})

    name = str(values.get("store_name") or "").strip()
    sid = str(values.get("store_id") or "").strip().lower()
    ics = str(values.get("ics_url") or "").strip()
    extra_raw = values.get("ics_urls") or []
    if isinstance(extra_raw, str):
        extra_raw = extra_raw.splitlines()
    extras = [str(u).strip() for u in extra_raw if str(u).strip()]

    if not name:
        errors.append("Συμπλήρωσε το όνομα του καταστήματος.")
    if not sid:
        errors.append("Συμπλήρωσε το ID του καταστήματος (π.χ. peristeri ή 12).")
    elif not STORE_ID_RE.match(sid):
        errors.append(
            "Το ID δέχεται μόνο λατινικά γράμματα, αριθμούς, - ή _ (π.χ. peristeri ή 12)."
        )
    if not ics:
        errors.append("Πρόσθεσε το κεντρικό ημερολόγιο (σύνδεσμος ICS) και σημείωσέ το ως «Κεντρικό».")
    elif not ics.lower().startswith("http"):
        errors.append("Ο κεντρικός σύνδεσμος ICS πρέπει να ξεκινά με http:// ή https://")
    for u in extras:
        if not u.lower().startswith("http"):
            errors.append(f"Ο επιπλέον σύνδεσμος πρέπει να ξεκινά με http: {u[:60]}")
            break

    raw_sec = str(values.get("sound_seconds", "") or "").strip() or "10"
    try:
        sec = int(raw_sec)
        if not 1 <= sec <= 600:
            raise ValueError
    except ValueError:
        errors.append("Τα δευτερόλεπτα ήχου πρέπει να είναι ακέραιος από 1 έως 600.")
        sec = 10

    cfg["store_name"] = name or cfg.get("store_name") or "Κατάστημα"
    cfg["store_id"] = sid
    cfg["ics_url"] = ics
    cfg["ics_urls"] = [u for u in extras if u != ics]
    # ics_names (προαιρετικό, {url: όνομα}): οι παλιές εκδόσεις απλώς το αγνοούν
    names = values.get("ics_names") if "ics_names" in values else cfg.get("ics_names")
    keep = {ics, *cfg["ics_urls"]}
    names = {str(u).strip(): str(n).strip() for u, n in (names or {}).items()
             if str(n or "").strip() and str(u).strip() in keep} if isinstance(names, dict) else {}
    if names:
        cfg["ics_names"] = names
    else:
        cfg.pop("ics_names", None)
    if "sound" in values:
        cfg["sound"] = bool(values.get("sound"))
    cfg["sound_seconds"] = sec
    return cfg, errors


def save_config(cfg: dict, path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json(path, cfg)


def norm_tag(s: str) -> str:
    return "".join(ch for ch in s.lower().strip() if ch.isalnum() or ch in "-_")


def parse_target_tags(title: str, description: str) -> tuple[list[str] | None, str]:
    """
    [όλα] ή χωρίς αγκύλες = όλα τα μαγαζιά.
    [peristeri] ή [peristeri,kalaamata] = μόνο αυτά.
    Επιστρέφει (λίστα tags ή None για όλα, καθαρός τίτλος).
    """
    import re

    text = title or ""
    m = re.match(r"^\s*\[([^\]]+)\]\s*(.*)$", text)
    tags = None
    clean = text.strip()
    if m:
        raw = m.group(1)
        clean = (m.group(2) or "").strip() or text.strip()
        parts = [norm_tag(p) for p in raw.replace(";", ",").split(",")]
        parts = [p for p in parts if p]
        if parts and any(p in ("ola", "all", "όλα") for p in parts):
            tags = None
        elif parts:
            tags = parts
    return tags, clean


def event_key(uid: str, start: datetime) -> str:
    if start.tzinfo is None:
        start = start.replace(tzinfo=HELLENIC)
    return f"{uid}|{start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


class ReminderEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.state = load_json(STATE_PATH, {"dismissed": [], "snooze_until": {}})
        self.lock = threading.Lock()
        self.events = []  # list of dicts
        self.last_error = ""
        self.last_sync = None
        self.wake = threading.Event()  # ξυπνά τον βρόχο (συγχρονισμός/νέες ρυθμίσεις)

    def reload_config(self) -> bool:
        """Ξαναδιαβάζει το config.json χωρίς επανεκκίνηση. True αν φορτώθηκε."""
        raw = read_config_raw()
        if not config_is_complete(raw):
            return False
        with self.lock:
            self.cfg = apply_defaults(raw)
        self.wake.set()
        return True

    def is_dismissed(self, key: str) -> bool:
        return key in self.state.get("dismissed", [])

    def dismiss(self, key: str) -> None:
        with self.lock:
            d = list(self.state.get("dismissed", []))
            if key not in d:
                d.append(key)
            # κράτα μόνο πρόσφατα keys για να μη φουσκώνει το αρχείο
            self.state["dismissed"] = d[-2000:]
            self.state.setdefault("snooze_until", {}).pop(key, None)
            save_json(STATE_PATH, self.state)

    def snooze(self, key: str, minutes: int = 5) -> None:
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        with self.lock:
            self.state.setdefault("snooze_until", {})[key] = until.isoformat()
            save_json(STATE_PATH, self.state)

    def snoozed(self, key: str) -> bool:
        raw = self.state.get("snooze_until", {}).get(key)
        if not raw:
            return False
        try:
            until = datetime.fromisoformat(raw)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) < until
        except Exception:
            return False

    def fetch(self) -> None:
        urls = calendar_urls(self.cfg)
        now = datetime.now(HELLENIC)
        window_start = now - timedelta(hours=2)
        window_end = now + timedelta(days=2)
        out = []
        errors = []
        for url in urls:
            try:
                r = requests.get(url, timeout=25)
                r.raise_for_status()
                cal = Calendar.from_ical(r.content)
                instances = recurring_ical_events.of(cal).between(window_start, window_end)
            except Exception as e:
                errors.append(str(e))
                continue
            for ev in instances:
                if ev.name != "VEVENT":
                    continue
                dtstart = ev.get("dtstart")
                if dtstart is None:
                    continue
                start = dtstart.dt
                if not isinstance(start, datetime):
                    # ολοήμερα: εμφάνιση στις 09:00 Ελλάδας
                    start = datetime.combine(start, datetime.min.time()).replace(
                        tzinfo=HELLENIC
                    ) + timedelta(hours=9)
                elif start.tzinfo is None:
                    start = start.replace(tzinfo=HELLENIC)
                else:
                    start = start.astimezone(HELLENIC)

                dtend = ev.get("dtend")
                end = None
                if dtend is not None:
                    end = dtend.dt
                    if isinstance(end, datetime):
                        if end.tzinfo is None:
                            end = end.replace(tzinfo=HELLENIC)
                        else:
                            end = end.astimezone(HELLENIC)

                uid = str(ev.get("uid") or f"no-uid-{start.isoformat()}")
                title = str(ev.get("summary") or "Υπενθύμιση")
                desc = str(ev.get("description") or "").strip()
                tags, clean_title = parse_target_tags(title, desc)
                out.append(
                    {
                        "uid": uid,
                        "key": event_key(uid, start),
                        "title": clean_title,
                        "raw_title": title,
                        "tags": tags,
                        "description": desc,
                        "start": start,
                        "end": end,
                    }
                )
        out.sort(key=lambda x: x["start"])
        with self.lock:
            self.events = out
            self.last_error = " | ".join(errors)
            self.last_sync = datetime.now(HELLENIC)

    def _for_this_store(self, ev: dict) -> bool:
        tags = ev.get("tags")
        if not tags:
            return True
        sid = norm_tag(str(self.cfg.get("store_id") or self.cfg.get("store_name") or ""))
        if not sid:
            return True
        return sid in tags

    def due_events(self) -> list:
        now = datetime.now(HELLENIC)
        before = timedelta(minutes=int(self.cfg.get("minutes_before") or 0))
        missed = timedelta(minutes=int(self.cfg.get("show_missed_max_minutes") or 15))
        due = []
        with self.lock:
            events = list(self.events)
        for ev in events:
            key = ev["key"]
            if self.is_dismissed(key) or self.snoozed(key):
                continue
            if not self._for_this_store(ev):
                continue
            trigger = ev["start"] - before
            if trigger <= now <= ev["start"] + missed:
                due.append(ev)
        return due


# ---------------------------------------------------------------- Εμφάνιση (κοινά)

AMBER = "#F5B400"
AMBER_HOVER = "#FFC51F"
AMBER_SOFT = "#FFD452"
INK = "#1A1A1A"
CREAM = "#FBF7EC"
LINE = "#E7E2D4"
FIELD_BORDER = "#CFC8B6"
MUTED = "#6B6B6B"
OK_FG = "#1B7F3B"
ERR_FG = "#C62828"
GREEK_DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

_FONT_CACHE: dict = {}


def _font_families(root) -> set:
    if "families" not in _FONT_CACHE:
        from tkinter import font as tkfont

        try:
            _FONT_CACHE["families"] = {f.lower() for f in tkfont.families(root)}
        except Exception:
            _FONT_CACHE["families"] = set()
    return _FONT_CACHE["families"]


def ui_font(root, size: int, weight: str = "normal") -> tuple:
    """Γραμματοσειρά για το UI. weight: normal | semi | bold | black.

    Windows: Segoe UI / Segoe UI Semibold / Segoe UI Black (υπάρχουν από Windows 7+).
    Αν λείπουν: Segoe UI bold, μετά Tahoma/Arial (έχουν ελληνικά), αλλιώς TkDefaultFont.
    Linux (τεστ/προεπισκόπηση): Noto Sans ή DejaVu Sans."""
    fams = _font_families(root)
    bold = "bold" if weight in ("bold", "black") else "normal"
    if "segoe ui" in fams:
        if weight == "semi" and "segoe ui semibold" in fams:
            return ("Segoe UI Semibold", size, "normal")
        if weight == "black" and "segoe ui black" in fams:
            return ("Segoe UI Black", size, "normal")
        return ("Segoe UI", size, bold)
    for fam in ("Noto Sans", "DejaVu Sans", "Tahoma", "Arial"):
        if fam.lower() in fams:
            return (fam, size, bold)
    return ("TkDefaultFont", size, bold)


def _rounded_photo(master, w: int, h: int, r: int, fill: str, bg: str, outline=None,
                   width: int = 0):
    """Στρογγυλεμένο ορθογώνιο ως tk.PhotoImage του `master` (σχέδιο με PIL, εξομάλυνση 4x,
    και φόρτωση ως PNG από το ίδιο το Tk). None αν λείπει το PIL."""
    try:
        import base64
        import io
        import tkinter as tk
        from PIL import Image, ImageDraw
    except Exception:
        return None
    k = 4
    im = Image.new("RGB", (w * k, h * k), bg)
    ImageDraw.Draw(im).rounded_rectangle(
        (0, 0, w * k - 1, h * k - 1), r * k, fill=fill, outline=outline, width=width * k
    )
    buf = io.BytesIO()
    im.resize((w, h), Image.LANCZOS).save(buf, format="PNG")
    try:
        return tk.PhotoImage(master=master, data=base64.b64encode(buf.getvalue()).decode("ascii"),
                             format="png")
    except Exception:
        return None


class CanvasPainter:
    """Σχήματα/κουμπιά πάνω σε tk.Canvas. Δουλεύει ίδια σε Windows 10/11 (Tk 8.6):
    μόνο εικόνες, κείμενο και ορθογώνια — καμία διαφάνεια παραθύρου."""

    def __init__(self, canvas):
        self.c = canvas
        self.keep: list = []
        self.clicks: dict = {}  # κείμενο κουμπιού → χειριστής κλικ (και για τεστ)

    def rrect(self, x, y, w, h, r, fill, bg, outline=None, width=0):
        ph = _rounded_photo(self.c, w, h, r, fill, bg, outline, width)
        if ph is None:  # χωρίς PIL: απλό ορθογώνιο
            return self.c.create_rectangle(x, y, x + w, y + h, fill=fill,
                                           outline=outline or fill, width=width)
        self.keep.append(ph)
        return self.c.create_image(x, y, image=ph, anchor="nw")

    def button(self, x, y, w, h, r, text, font, fill, hover, fg, command, bg,
               outline=None, width=0):
        normal = _rounded_photo(self.c, w, h, r, fill, bg, outline, width)
        over = _rounded_photo(self.c, w, h, r, hover, bg, outline, width)
        if normal is None:
            item = self.c.create_rectangle(x, y, x + w, y + h, fill=fill,
                                           outline=outline or fill, width=width)

            def set_state(hot):
                if self.alive():
                    self.c.itemconfigure(item, fill=hover if hot else fill)
        else:
            self.keep += [normal, over]
            item = self.c.create_image(x, y, image=normal, anchor="nw")

            def set_state(hot):
                if self.alive():
                    self.c.itemconfigure(item, image=over if hot else normal)
        txt = self.c.create_text(x + w // 2, y + h // 2, text=text, font=font, fill=fg)
        def hot(on):
            set_state(on)
            if self.alive():
                self.c.configure(cursor="hand2" if on else "")

        def click(e):
            # ΠΟΤΕ destroy μέσα στο binding του ίδιου του canvas (Tcl_Panic / κρασάρισμα):
            # η εντολή τρέχει αφού τελειώσει η επεξεργασία του γεγονότος.
            if self.alive():
                self.c.after_idle(command)

        self.clicks[text] = click
        for it in (item, txt):
            self.c.tag_bind(it, "<Enter>", lambda e: hot(True))
            self.c.tag_bind(it, "<Leave>", lambda e: hot(False))
            self.c.tag_bind(it, "<ButtonRelease-1>", click)
        return item, txt

    def alive(self) -> bool:
        try:
            return bool(self.c.winfo_exists())
        except Exception:
            return False

    def release(self) -> None:
        """Σβήνει τις εικόνες ρητά, στο νήμα του Tk (όχι αργότερα από τον GC σε άλλο νήμα)."""
        for ph in self.keep:
            try:
                ph.tk.call("image", "delete", ph.name)
            except Exception:
                pass
            ph.name = ""  # ώστε το __del__ να μην ξανακαλέσει το Tcl
        self.keep = []


def load_photo(name: str, master=None):
    """PNG από τα πόρους της εφαρμογής ως tk.PhotoImage (Tk 8.6 διαβάζει PNG)."""
    import tkinter as tk

    p = find_resource(name)
    if not p:
        return None
    try:
        return tk.PhotoImage(master=master, file=str(p))
    except Exception:
        return None


def set_window_icon(win) -> None:
    try:
        ico = find_resource("icon.ico")
        if ico and sys.platform.startswith("win"):
            win.iconbitmap(str(ico))
        else:
            ph = load_photo("icon_48.png", win)
            if ph is not None:
                win.iconphoto(True, ph)
                win._icon_ref = ph
    except Exception:
        pass


def win11_round_corners(win) -> None:
    """Στρογγυλές γωνίες παραθύρου στα Windows 11 (DWM). Στα 10 απλώς αγνοείται."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        pref = ctypes.c_int(2)  # DWMWA_WINDOW_CORNER_PREFERENCE=33, DWMWCP_ROUND=2
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
    except Exception:
        pass


def screen_work_area(win) -> tuple[int, int, int, int]:
    """Περιοχή εργασίας της οθόνης (χωρίς τη γραμμή εργασιών): x, y, πλάτος, ύψος.

    Στα Windows από το SystemParametersInfo(SPI_GETWORKAREA). Η εφαρμογή δεν είναι
    DPI-aware, οπότε στο 125%/150% τα νούμερα είναι ήδη «λογικά» pixels (π.χ. 1366x768 στο
    150% ≈ 911x485), στην ίδια κλίμακα με το Tk."""
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):
                w, h = r.right - r.left, r.bottom - r.top
                if w > 200 and h > 200:
                    return r.left, r.top, w, h
        except Exception:
            pass
    return 0, 0, sw, sh


def fit_text(canvas, item, text: str, max_h: int) -> str:
    """Κόβει το κείμενο (με …) ώστε το item να μη ξεπερνά max_h pixels ύψος."""
    def height(t):
        canvas.itemconfigure(item, text=t)
        x1, y1, x2, y2 = canvas.bbox(item)
        return y2 - y1

    if height(text) <= max_h:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if height(text[:mid].rstrip() + "…") <= max_h:
            lo = mid
        else:
            hi = mid - 1
    cut = text[:lo]
    if " " in cut[-20:]:
        cut = cut[: cut.rfind(" ")]
    final = cut.rstrip(" ,.;·-") + "…"
    canvas.itemconfigure(item, text=final)
    return final


class Overlay:
    """Μεγάλο πορτοκαλί παράθυρο στο κέντρο, πάντα από πάνω (σχέδιο C).

    Enter = «Το είδα», Esc = «Σε 5 λεπτά» (τα πλήκτρα ενεργοποιούνται λίγο μετά το
    άνοιγμα, για να μην κλείσει κατά λάθος από κάποιον που πληκτρολογεί).

    Νήματα: ΟΛΗ η δουλειά Tk γίνεται στο νήμα που δημιούργησε το Overlay (το νήμα των
    υπενθυμίσεων). Ένα κρυφό tk.Tk() ζει όσο και η εφαρμογή και δεν καταστρέφεται ποτέ,
    κάθε υπενθύμιση είναι ένα Toplevel, και οι εικόνες σβήνονται ρητά στο ίδιο νήμα.
    Έτσι κανένα αντικείμενο Tcl δεν σβήνεται από τον GC σε άλλο νήμα (Tcl_Panic)."""

    WIDTH = 720
    KEY_GUARD_SECONDS = 1.5
    MAX_SCREEN_FRACTION = 0.8  # το παράθυρο μεγαλώνει έως ~80% του ύψους εργασίας
    MIN_DESC_LINES = 3         # ορατές γραμμές περιγραφής, ακόμη και σε μικρή οθόνη
    work_area = None           # (x, y, w, h) για τεστ/προεπισκόπηση· αλλιώς από το σύστημα

    def __init__(self, engine: ReminderEngine, on_idle=None):
        self.engine = engine
        self.on_idle = on_idle
        self.root = None
        self.current_key = None
        self._tk = None
        self._sound = SoundPlayer()
        self._keys_after = 0.0
        self.layout: dict = {}
        self.base = None  # κρυφό tk.Tk(), ένα για όλη τη ζωή του νήματος
        self._painter = None
        self._desc = None
        self._top_job = None
        self._closing = []

    def ensure_base(self):
        import tkinter as tk

        if self.base is None:
            self.base = tk.Tk()
            self.base.withdraw()
            self.base.title(APP_NAME)
            self.base.report_callback_exception = tk_report_exception
        return self.base

    def pump(self) -> None:
        """Επεξεργάζεται εκκρεμή γεγονότα του κρυφού root (μόνο από το νήμα του)."""
        if self.base is not None:
            try:
                self.base.update()
            except Exception as e:
                log(f"tk pump: {e!r}")

    # -- κατασκευή (χωρίς mainloop, για να μπορεί να ελεγχθεί σε τεστ)
    def build(self, ev: dict, position: tuple[int, int] | None = None):
        import tkinter as tk
        from tkinter import font as tkfont

        self._tk = tk
        base = self.ensure_base()
        if self.root is not None:  # προηγούμενο παράθυρο που δεν έκλεισε κανονικά
            self._closing.append((self.root, self._painter))
            self.root = self._painter = None
        self._finish_pending()
        self.current_key = ev["key"]
        root = self.root = tk.Toplevel(base)
        root.title(APP_NAME)
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        set_window_icon(root)
        root.protocol("WM_DELETE_WINDOW", self._dismiss)

        W = self.WIDTH
        wx, wy, ww, wh = self.work_area or screen_work_area(root)
        max_h = int(wh * self.MAX_SCREEN_FRACTION)
        hard_h = max(200, wh - 16)  # ποτέ έξω από την οθόνη: τα κουμπιά πάντα ορατά
        f = lambda size, weight="normal": ui_font(root, size, weight)  # noqa: E731

        def linespace(font) -> int:
            return tkfont.Font(root=root, font=font).metrics("linespace")
        c = tk.Canvas(root, width=W, height=440, bg=AMBER, bd=0,
                      highlightthickness=1, highlightbackground="#C99300")
        c.pack(fill="both", expand=True)
        p = CanvasPainter(c)
        self._painter = p

        title = " ".join(str(ev.get("title") or "").split()) or "Υπενθύμιση"
        start = ev["start"]
        time_txt = start.strftime("%H:%M")
        date_txt = f"{GREEK_DAYS[start.weekday()]} {start.strftime('%d/%m/%Y')}"
        store = str(self.engine.cfg.get("store_name") or "")
        label = "Υ Π Ε Ν Θ Υ Μ Ι Σ Η"
        if position and position[1] > 1:
            label += f"   ·   {position[0]} από {position[1]}"

        def draw_header(compact: bool):
            """Πάνω μέρος. compact=True για μεγάλα κείμενα / μικρές οθόνες: μικρότερο
            καμπανάκι και ώρα, ώστε να μένει χώρος για την περιγραφή."""
            c.delete("all")
            c.create_rectangle(0, 0, W + 2, 10, fill=INK, width=0)
            bx, by = (36, 40) if compact else (44, 50)
            names = ("bell_84.png", "bell_150.png") if compact else ("bell_150.png", "icon_128.png")
            bell = load_photo(names[0], c) or load_photo(names[1], c)
            bell_bottom = by
            if bell is not None:
                p.keep.append(bell)
                c.create_image(bx, by, image=bell, anchor="nw")
                bell_bottom = by + bell.height()
            x0 = 144 if compact else 230
            right = W - 32
            col_w = right - x0
            ly = 42 if compact else 56
            c.create_text(x0, ly, text=label, anchor="nw", font=f(12 if compact else 13, "black"),
                          fill=INK)
            # Τίτλος: αναδίπλωση στο πλάτος της στήλης, μικραίνει αν χρειαστεί
            sizes, lines = ((24, 22, 20), 3) if compact else ((32, 28, 25, 22, 20), 3)
            t_item = c.create_text(x0, ly + (24 if compact else 28), text=title, anchor="nw",
                                   width=col_w, font=f(sizes[0], "black"), fill=INK)
            title_size = sizes[0]
            for size in sizes:
                title_size = size
                c.itemconfigure(t_item, font=f(size, "black"))
                x1, y1, x2, y2 = c.bbox(t_item)
                if y2 - y1 <= lines * linespace(f(size, "black")) + 2:
                    break
            else:
                if compact:  # δεν χωρά ούτε σε 3 γραμμές: 2 γραμμές εδώ, ολόκληρος στο πλαίσιο
                    lines = 2
            fit_text(c, t_item, title, lines * linespace(f(title_size, "black")) + 2)
            title_bottom = c.bbox(t_item)[3]
            tm = c.create_text(x0 - 2, title_bottom + 2, text=time_txt, anchor="nw",
                               font=f(34 if compact else 50, "black"), fill=INK)
            tx1, ty1, tx2, ty2 = c.bbox(tm)
            side_x = tx2 + 16
            side_txt = (f"{date_txt}  ·  {store}" if compact else f"{date_txt}\n{store}").strip(" ·\n")
            side = c.create_text(side_x, (ty1 + ty2) // 2 if compact else ty1 + 14, text=side_txt,
                                 anchor="w" if compact else "nw", width=max(120, right - side_x),
                                 font=f(13 if compact else 14, "semi"), fill="#4A3600")
            y = max(bell_bottom, ty2, c.bbox(side)[3]) + (16 if compact else 22)
            return y, title_size, t_item

        y, title_size, t_item = draw_header(False)

        # Περιγραφή: ολόκληρη, χωρίς «…». Το παράθυρο μεγαλώνει όσο χρειάζεται (έως ~80%
        # της οθόνης)· πέρα από αυτό γίνεται πιο «συμπαγές» και το κείμενο κυλά μέσα στο
        # πλαίσιο (τροχός ποντικιού / βελάκια / PgUp-PgDn).
        desc = str(ev.get("description") or "").strip()
        desc = re.sub(r"\n\s*\n+", "\n\n", desc)
        BUTTONS = 22 + 64 + 32  # κενό + κουμπιά + κάτω περιθώριο
        PAD = 14
        tw = W - 104 - 14  # πλάτος κειμένου (χώρος για τη μπάρα κύλισης)
        line = linespace(f(14))

        def natural_height(title_cut: bool) -> int:
            """Φυσικό ύψος του κειμένου του πλαισίου, με τις ίδιες γραμματοσειρές."""
            h = 0
            for txt, fnt in ((title if title_cut else "", f(15, "bold")), (desc, f(14))):
                if txt:
                    m = c.create_text(0, 0, text=txt, anchor="nw", width=tw, font=fnt)
                    x1, y1, x2, y2 = c.bbox(m)
                    h += y2 - y1 + (8 if h else 0)
                    c.delete(m)
            return h

        title_cut = c.itemcget(t_item, "text") != title
        natural = natural_height(title_cut)
        compact = False
        if natural and y + natural + 4 + 2 * PAD + BUTTONS > max_h:
            compact = True
            y, title_size, t_item = draw_header(True)
            title_cut = c.itemcget(t_item, "text") != title
            natural = natural_height(title_cut)
        shown_title = c.itemcget(t_item, "text")
        scroll = False
        if natural:
            room = max_h - y - 2 * PAD - BUTTONS
            if room < self.MIN_DESC_LINES * line:  # μικρή οθόνη: μεγάλωσε ως το όριο
                room = min(self.MIN_DESC_LINES * line, hard_h - y - 2 * PAD - BUTTONS)
            room = max(line, room)
            if natural + 4 <= room:
                box_h = natural + 4
            else:  # ολόκληρες γραμμές, για να μη φαίνεται μισή γραμμή στο κάτω μέρος
                box_h, scroll = max(line, (room // line) * line), True
            panel = p.rrect(32, y, W - 64, box_h + 2 * PAD, 14, AMBER_SOFT, AMBER)
            txtw = tk.Text(c, bg=AMBER_SOFT, fg=INK, bd=0, highlightthickness=0, relief="flat",
                           wrap="word", font=f(14), padx=0, pady=0, cursor="arrow",
                           takefocus=0, exportselection=0, insertwidth=0,
                           selectbackground=AMBER_SOFT, selectforeground=INK, inactiveselectbackground=AMBER_SOFT)
            txtw.tag_configure("title", font=f(15, "bold"), spacing3=8)
            if title_cut:
                txtw.insert("end", title + ("\n" if desc else ""), "title")
            if desc:
                txtw.insert("end", desc)
            txtw.configure(state="disabled")
            txt_item = c.create_window(52, y + PAD, window=txtw, anchor="nw", width=tw, height=box_h)
            self._desc = txtw
            # Λεπτή μπάρα κύλισης στο ίδιο ύφος (εμφανίζεται μόνο όταν χρειάζεται).
            sb = tk.Canvas(c, width=8, height=box_h, bg=AMBER_SOFT, highlightthickness=0, bd=0)
            thumb = sb.create_rectangle(1, 0, 7, 0, fill="#9A7400", width=0)
            sb_item = c.create_window(W - 32 - 18, y + PAD, window=sb, anchor="nw",
                                      state="hidden")

            fit = {"box_h": box_h, "room": room, "tw": tw, "y": y, "panel": panel, "txt_item": txt_item,
                   "sb": sb, "sb_item": sb_item}

            def yset(a, b, sb=sb, thumb=thumb, sb_item=sb_item):
                box_h = fit["box_h"]
                a, b = float(a), float(b)
                need = b - a < 0.999
                c.itemconfigure(sb_item, state="normal" if need else "hidden")
                y1 = a * box_h
                sb.coords(thumb, 1, y1, 7, max(y1 + 28, b * box_h))
                self.layout["scrollable"] = need

            def jump(e):
                a, b = txtw.yview()
                txtw.yview_moveto(max(0.0, e.y / fit["box_h"] - (b - a) / 2))

            txtw.configure(yscrollcommand=yset)
            sb.bind("<Button-1>", jump)
            sb.bind("<B1-Motion>", jump)
            y += box_h + 2 * PAD + 22
            c.tag_lower(panel)
        else:
            fit = None
            self._desc = None
            y += 4

        p.button(32, y, 380, 64, 16, "✓  ΤΟ ΕΙΔΑ", f(18, "black"), INK, "#33302A", AMBER,
                 self._dismiss, AMBER)
        p.button(W - 32 - 240, y, 240, 64, 16, "Σε 5 λεπτά", f(16, "bold"), AMBER, "#FFC93D",
                 INK, self._snooze, AMBER, outline=INK, width=3)
        H = y + 64 + 32
        c.configure(height=H)
        px = wx + max(0, (ww - W) // 2)
        py = wy + max(0, (wh - H) // 2)
        root.geometry(f"{W}x{H}+{px}+{py}")
        self.layout = {"height": H, "title_size": title_size, "title": shown_title,
                       "title_cut": title_cut, "scroll": scroll, "scrollable": False,
                       "compact": compact,
                       "max_h": max_h, "work_h": wh}

        # Κύλιση περιγραφής: τροχός ποντικιού (οπουδήποτε στο παράθυρο) και βελάκια/PgUp/PgDn.
        def wheel(e):
            if self._desc is not None:
                step = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
                self._desc.yview_scroll(step * 3, "units")
            return "break"

        def keyscroll(n, what):
            if self._desc is not None:
                self._desc.yview_scroll(n, what)
            return "break"

        for w_ in (root, c):
            w_.bind("<MouseWheel>", wheel)
            w_.bind("<Button-4>", wheel)
            w_.bind("<Button-5>", wheel)
        if self._desc is not None:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self._desc.bind(seq, wheel)
        root.bind("<Down>", lambda e: keyscroll(1, "units"))
        root.bind("<Up>", lambda e: keyscroll(-1, "units"))
        root.bind("<Next>", lambda e: keyscroll(1, "pages"))
        root.bind("<Prior>", lambda e: keyscroll(-1, "pages"))

        for key in ("<Return>", "<KP_Enter>"):
            root.bind(key, lambda e: self._key(self._dismiss))
        root.bind("<Escape>", lambda e: self._key(self._snooze))
        self._keys_after = time.monotonic() + self.KEY_GUARD_SECONDS
        root.deiconify()
        root.update_idletasks()
        if fit is not None and not scroll:
            self._fit_desc(root, c, fit, p, PAD, line, (wx, wy, ww, wh))
        win11_round_corners(root)
        root.lift()
        root.focus_force()
        self._top_job = base.after(4000, self._keep_on_top)
        return root

    def _fit_desc(self, root, c, fit, p, PAD, line, work):
        """Διόρθωση μετά την εμφάνιση: οι γραμματοσειρές των Windows αναδιπλώνουν λίγο
        διαφορετικά από τη μέτρηση στον καμβά. Αν το πραγματικό κείμενο δεν χωρά, μεγάλωσε
        το πλαίσιο (μέχρι το όριο) ή γύρισε σε κύλιση — ποτέ κομμένο."""
        txtw = self._desc
        if txtw is None or self.root is not root:
            return
        try:
            ready = txtw.winfo_ismapped() and abs(txtw.winfo_width() - fit["tw"]) <= 2
        except Exception:
            return
        if not ready:  # δεν έχει πάρει ακόμα το πλάτος του: ξαναδοκίμασε σε λίγο
            tries = fit.get("tries", 0)
            if tries < 40:
                fit["tries"] = tries + 1
                self.base.after(25, lambda: self._fit_desc(root, c, fit, p, PAD, line, work))
            return
        try:
            real = txtw.count("1.0", "end", "update", "ypixels")
        except Exception:
            return
        if isinstance(real, tuple):
            real = real[0]
        real = int(real or 0)
        old = fit["box_h"]
        self.layout["desc_real"] = real
        self.layout["desc_box"] = old
        if real <= old:
            return
        if real + 4 <= fit["room"]:
            new = real + 4
        else:
            new = max(line, (fit["room"] // line) * line)
            self.layout["scroll"] = True
        delta = new - old
        if delta <= 0:
            return
        top = fit["y"]
        bottom = top + old + 2 * PAD
        for item in c.find_all():
            bb = c.bbox(item)
            if bb and bb[1] >= bottom - 1 and item != fit["panel"]:
                c.move(item, 0, delta)
        c.delete(fit["panel"])
        panel = p.rrect(32, top, int(c.cget("width")) - 64, new + 2 * PAD, 14, AMBER_SOFT, AMBER)
        c.tag_lower(panel)
        fit.update(box_h=new, panel=panel)
        c.itemconfigure(fit["txt_item"], height=new)
        fit["sb"].configure(height=new)
        W = int(c.cget("width"))
        H = int(c.cget("height")) + delta
        c.configure(height=H)
        wx, wy, ww, wh = work
        root.geometry(f"{W}x{H}+{wx + max(0, (ww - W) // 2)}+{wy + max(0, (wh - H) // 2)}")
        self.layout["height"] = H
        root.update_idletasks()

    def show(self, ev: dict, position: tuple[int, int] | None = None) -> None:
        self.build(ev, position)
        if self.engine.cfg.get("sound"):
            self._sound.start(int(self.engine.cfg.get("sound_seconds") or 30))
        self.base.mainloop()  # επιστρέφει με base.quit() όταν κλείσει η υπενθύμιση
        self._sound.stop()
        self._finish_pending()
        self.root = None
        self.current_key = None

    def _keep_on_top(self):
        self._top_job = None
        if self.root is None or self.base is None:
            return
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
            self._top_job = self.base.after(4000, self._keep_on_top)
        except Exception:
            pass

    def _key(self, action):
        if time.monotonic() >= self._keys_after:
            action()

    def _dismiss(self):
        if self.current_key:
            self.engine.dismiss(self.current_key)
        self._close()

    def _snooze(self):
        if self.current_key:
            self.engine.snooze(self.current_key, 5)
        self._close()

    def _close(self):
        """Κλείνει την τρέχουσα υπενθύμιση. Η καταστροφή του παραθύρου γίνεται σε
        after_idle (όχι μέσα στο binding που την ζήτησε) και ΜΟΝΟ το Toplevel: το
        κρυφό root, το tray και η εφαρμογή συνεχίζουν."""
        self._sound.stop()
        if self.root is None:
            return
        win, self.root = self.root, None
        self.current_key = None
        try:
            win.withdraw()
        except Exception:
            pass
        self._closing.append((win, self._painter))
        self._painter = None
        self._desc = None
        if self._top_job is not None and self.base is not None:
            try:
                self.base.after_cancel(self._top_job)
            except Exception:
                pass
            self._top_job = None
        if self.base is not None:
            self.base.after_idle(self._finish_and_quit)

    def _finish_pending(self) -> None:
        while self._closing:
            win, painter = self._closing.pop()
            try:
                win.destroy()
            except Exception:
                pass
            if painter is not None:
                painter.release()

    def _finish_and_quit(self) -> None:
        self._finish_pending()
        if self.base is not None:
            self.base.quit()


def play_loop(engine: ReminderEngine):
    overlay = Overlay(engine)
    while True:
        try:
            engine.fetch()
            if engine.last_error:
                log(f"fetch: {engine.last_error}")
            due = engine.due_events()
            for i, ev in enumerate(due, 1):
                if engine.is_dismissed(ev["key"]) or engine.snoozed(ev["key"]):
                    continue
                overlay.show(ev, (i, len(due)))
        except Exception as e:
            log(f"loop: {e!r}")
        # Αναμονή σε μικρά κομμάτια ώστε το κρυφό παράθυρο Tk να απαντά στα Windows.
        deadline = time.monotonic() + max(10, int(engine.cfg.get("poll_seconds") or POLL_DEFAULT))
        while time.monotonic() < deadline and not engine.wake.is_set():
            overlay.pump()
            engine.wake.wait(timeout=0.5)
        engine.wake.clear()


# ---------------------------------------------------------------- Ρυθμίσεις

def clean_ics_url(text: str) -> str:
    """Αφαιρεί κενά/αλλαγές γραμμής (συχνά μετά από επικόλληση) και κάνει webcal:// -> https://."""
    u = "".join(str(text or "").split())
    if u.lower().startswith("webcal://"):
        u = "https://" + u[len("webcal://"):]
    return u


def short_url(u: str) -> str:
    """Σύντομη μορφή για τη λίστα: διακομιστής/…/τελευταίο κομμάτι (κρύβει τα μυστικά tokens)."""
    from urllib.parse import urlparse

    try:
        p = urlparse(u)
    except Exception:
        return u[:50]
    last = p.path.rstrip("/").rsplit("/", 1)[-1]
    host = p.netloc or u[:40]
    return f"{host}/…/{last}" if last else host


def check_ics(url: str) -> tuple[bool, str]:
    """Κατεβάζει το ICS. (True, «Εντάξει — βρέθηκαν N γεγονότα.») ή (False, μήνυμα λάθους)."""
    url = clean_ics_url(url)
    if not url:
        return False, "Επικολλήστε πρώτα τον σύνδεσμο ICS."
    if not url.lower().startswith(("http://", "https://")):
        return False, "Ο σύνδεσμος πρέπει να ξεκινά με https:// (ή http://)."
    try:
        r = requests.get(url, timeout=20)
    except requests.exceptions.Timeout:
        return False, "Ο διακομιστής δεν απάντησε εγκαίρως (20 δευτ.). Δοκιμάστε ξανά."
    except requests.exceptions.ConnectionError:
        return False, "Δεν υπάρχει σύνδεση με τον διακομιστή. Ελέγξτε το ίντερνετ και τον σύνδεσμο."
    except Exception as e:
        return False, f"Ο σύνδεσμος δεν είναι έγκυρος ({str(e)[:80]})."
    if r.status_code in (401, 403, 404):
        return False, (f"Ο σύνδεσμος δεν βρέθηκε ή δεν επιτρέπεται (HTTP {r.status_code}). "
                       "Αντιγράψτε τον ξανά από το ημερολόγιο.")
    if r.status_code >= 400:
        return False, f"Σφάλμα διακομιστή (HTTP {r.status_code}). Δοκιμάστε αργότερα."
    try:
        cal = Calendar.from_ical(r.content)
        n = sum(1 for comp in cal.walk() if comp.name == "VEVENT")
    except Exception:
        return False, ("Η διεύθυνση δεν είναι ημερολόγιο ICS. Στο Google Calendar χρησιμοποιήστε "
                       "τη «Μυστική διεύθυνση σε μορφή iCal».")
    return True, f"Εντάξει — βρέθηκαν {n} γεγονότα."


def calendars_from_config(cfg: dict) -> list[list]:
    """[[url, όνομα, κεντρικό], ...] από ics_url / ics_urls / ics_names (και παλιά config)."""
    names = cfg.get("ics_names") if isinstance(cfg.get("ics_names"), dict) else {}
    out: list[list] = []
    seen = set()
    central = str(cfg.get("ics_url") or "").strip()
    if central and "XXXX" not in central:
        out.append([central, str(names.get(central, "") or ""), True])
        seen.add(central)
    extra = cfg.get("ics_urls") or []
    if isinstance(extra, str):
        extra = extra.splitlines()
    for u in extra:
        u = str(u).strip()
        if u and "XXXX" not in u and u not in seen:
            out.append([u, str(names.get(u, "") or ""), False])
            seen.add(u)
    return out


def calendar_fields(cals: list) -> dict:
    """Αντίστροφο του calendars_from_config: ics_url, ics_urls, ics_names."""
    central = next((c for c in cals if c[2]), None)
    return {
        "ics_url": central[0] if central else "",
        "ics_urls": [c[0] for c in cals if not c[2]],
        "ics_names": {c[0]: c[1].strip() for c in cals if c[1] and c[1].strip()},
    }


EDIT_KEYCODES = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>", 65: "select-all"}


def ctrl_key_action(keycode: int, keysym: str):
    """Ctrl+γράμμα με βάση το φυσικό πλήκτρο (κωδικοί Windows).

    Με ενεργό ελληνικό πληκτρολόγιο το Ctrl+V δίνει keysym 'Greek_omega' και η
    προεπιλεγμένη σύνδεση του Tk δεν κάνει τίποτα· εδώ το πιάνουμε από τον keycode.
    Επιστρέφει None όταν το χειρίζεται ήδη το Tk (λατινικό πληκτρολόγιο)."""
    action = EDIT_KEYCODES.get(keycode)
    if action is None:
        return None
    if action != "select-all" and keysym.lower() in ("v", "c", "x"):
        return None
    return action


def add_edit_bindings(w) -> None:
    """Ctrl+V/C/X/A σε κάθε διάταξη πληκτρολογίου + μενού δεξιού κλικ."""
    import tkinter as tk

    def select_all():
        if isinstance(w, tk.Text):
            w.tag_add("sel", "1.0", "end-1c")
        else:
            w.select_range(0, "end")
            w.icursor("end")

    def on_ctrl(e):
        act = ctrl_key_action(e.keycode, e.keysym)
        if act == "select-all":
            select_all()
            return "break"
        if act:
            w.event_generate(act)
            return "break"
        return None

    w.bind("<Control-KeyPress>", on_ctrl, add="+")
    menu = tk.Menu(w, tearoff=0)
    menu.add_command(label="Αποκοπή", command=lambda: w.event_generate("<<Cut>>"))
    menu.add_command(label="Αντιγραφή", command=lambda: w.event_generate("<<Copy>>"))
    menu.add_command(label="Επικόλληση", command=lambda: w.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Επιλογή όλων", command=select_all)
    w.bind("<Button-3>", lambda e: (w.focus_set(), menu.tk_popup(e.x_root, e.y_root)))


def apply_settings_style(root):
    """ttk «clam» με τα χρώματα της εφαρμογής (ίδια εμφάνιση σε Windows 10/11)."""
    from tkinter import ttk

    f = lambda size, weight="normal": ui_font(root, size, weight)  # noqa: E731
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg="#FFFFFF")
    s.configure(".", background="#FFFFFF", foreground=INK, font=f(11))
    s.configure("TFrame", background="#FFFFFF")
    s.configure("Foot.TFrame", background=CREAM)
    s.configure("TLabel", background="#FFFFFF", foreground=INK)
    s.configure("Muted.TLabel", foreground=MUTED, font=f(9))
    s.configure("Section.TLabel", font=f(12, "bold"))
    s.configure("Welcome.TLabel", font=f(11, "semi"), foreground="#4A3600", background="#FFF3CC")
    s.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=FIELD_BORDER,
                lightcolor=FIELD_BORDER, darkcolor=FIELD_BORDER, padding=6)
    s.map("TEntry", bordercolor=[("focus", AMBER)], lightcolor=[("focus", AMBER)])
    s.configure("TButton", background="#FFFFFF", bordercolor=FIELD_BORDER, lightcolor="#FFFFFF",
                darkcolor="#FFFFFF", padding=(14, 7), font=f(10, "semi"), focuscolor="#FFFFFF")
    s.map("TButton", background=[("disabled", "#F4F4F4"), ("active", "#FFF6DA")])
    s.configure("Primary.TButton", background=AMBER, bordercolor=AMBER, lightcolor=AMBER,
                darkcolor=AMBER, font=f(11, "bold"), padding=(18, 8))
    s.map("Primary.TButton", background=[("active", AMBER_HOVER)])
    s.configure("TCheckbutton", background="#FFFFFF", font=f(11), focuscolor="#FFFFFF",
                indicatorsize=16, indicatormargin=(0, 0, 8, 0), indicatorbackground="#FFFFFF",
                indicatorforeground=INK, upperbordercolor=FIELD_BORDER,
                lowerbordercolor=FIELD_BORDER)
    s.map("TCheckbutton", indicatorbackground=[("selected", AMBER), ("active", "#FFF6DA")],
          background=[("active", "#FFFFFF")])
    s.configure("Cal.Treeview", rowheight=34, font=f(11), background="#FFFFFF",
                fieldbackground="#FFFFFF", bordercolor=FIELD_BORDER)
    s.configure("Cal.Treeview.Heading", font=f(10, "semi"), background=CREAM,
                bordercolor=LINE, relief="flat")
    s.map("Cal.Treeview", background=[("selected", "#FFE7A3")], foreground=[("selected", INK)])
    s.configure("TSpinbox", padding=4, arrowsize=14, fieldbackground="#FFFFFF",
                bordercolor=FIELD_BORDER, lightcolor=FIELD_BORDER, darkcolor=FIELD_BORDER)
    return s


def amber_header(win, title: str, subtitle: str):
    import tkinter as tk

    band = tk.Canvas(win, height=76, bg=AMBER, highlightthickness=0, bd=0)
    band.pack(fill="x", side="top")
    ph = load_photo("icon_48.png", band)
    x = 24
    if ph is not None:
        band._img = ph
        band.create_image(24, 38, image=ph, anchor="w")
        x = 86
    band.create_text(x, 27, text=title, anchor="w", font=ui_font(win, 15, "bold"), fill=INK)
    band.create_text(x, 52, text=subtitle, anchor="w", font=ui_font(win, 10), fill="#4A3600")
    return band


def footer(win):
    import tkinter as tk
    from tkinter import ttk

    foot = tk.Frame(win, bg=CREAM)
    foot.pack(fill="x", side="bottom")
    tk.Frame(foot, bg=LINE, height=1).pack(fill="x")
    fr = ttk.Frame(foot, padding=(24, 12), style="Foot.TFrame")
    fr.pack(fill="x")
    return fr


class CalendarDialog:
    """«Προσθήκη / Αλλαγή ημερολογίου». Μετά το κλείσιμο: result = (url, όνομα, κεντρικό) ή None."""

    def __init__(self, parent, url: str = "", name: str = "", central: bool = False,
                 title: str = "Προσθήκη ημερολογίου", existing_urls=(), check=None):
        import tkinter as tk
        from tkinter import ttk

        self.result = None
        self._existing = {u for u in existing_urls if u and u != url}
        self._check = check or check_ics
        d = self.top = tk.Toplevel(parent)
        d.withdraw()
        d.title(title)
        d.configure(bg="#FFFFFF")
        d.transient(parent)
        d.resizable(False, False)
        try:
            d.attributes("-topmost", True)
        except Exception:
            pass
        set_window_icon(d)
        f = lambda size, weight="normal": ui_font(d, size, weight)  # noqa: E731

        amber_header(d, title, "Επικολλήστε τον σύνδεσμο ICS του ημερολογίου")
        fr = footer(d)
        ttk.Button(fr, text="ΟΚ", style="Primary.TButton", command=self.ok).pack(side="right")
        ttk.Button(fr, text="Άκυρο", command=self.cancel).pack(side="right", padx=8)

        body = ttk.Frame(d, padding=(24, 16, 24, 10))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Σύνδεσμος ICS", style="Section.TLabel").pack(anchor="w")
        ttk.Label(body, text="Google Calendar: Ρυθμίσεις ημερολογίου → «Μυστική διεύθυνση σε μορφή iCal».",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        box = tk.Frame(body, bg=FIELD_BORDER, padx=1, pady=1)
        box.pack(fill="x")
        self.t_url = tk.Text(box, height=4, width=60, wrap="char", font=f(11), relief="flat",
                             bd=8, highlightthickness=0, bg="#FFFFFF", fg=INK,
                             insertbackground=INK, selectbackground="#FFE7A3",
                             selectforeground=INK, undo=True)
        self.t_url.pack(fill="x")
        self.t_url.insert("1.0", clean_ics_url(url))
        self.t_url.bind("<FocusIn>", lambda e: box.configure(bg=AMBER))
        self.t_url.bind("<FocusOut>", lambda e: box.configure(bg=FIELD_BORDER))
        self.t_url.bind("<Return>", lambda e: "break")  # ο σύνδεσμος είναι μία γραμμή
        add_edit_bindings(self.t_url)

        row = ttk.Frame(body)
        row.pack(fill="x", pady=(8, 12))
        ttk.Button(row, text="Επικόλληση από πρόχειρο", command=self.paste).pack(side="left")
        self.b_check = ttk.Button(row, text="Έλεγχος", command=self.check)
        self.b_check.pack(side="left", padx=8)

        ttk.Label(body, text="Όνομα (προαιρετικό)", style="Section.TLabel").pack(anchor="w")
        self.v_name = tk.StringVar(value=name)
        e = ttk.Entry(body, textvariable=self.v_name, font=f(11))
        e.pack(fill="x", pady=(4, 10))
        e.bind("<Return>", lambda ev: self.ok())
        add_edit_bindings(e)
        self.v_central = tk.BooleanVar(value=central)
        ttk.Checkbutton(body, text="Κεντρικό ημερολόγιο (υπενθυμίσεις για όλα τα καταστήματα)",
                        variable=self.v_central).pack(anchor="w")
        self.status = tk.Label(body, text="", font=f(10, "semi"), bg="#FFFFFF", wraplength=540,
                               justify="left", anchor="w")
        self.status.pack(fill="x", pady=(10, 0))

        d.bind("<Escape>", lambda e: self.cancel())
        d.protocol("WM_DELETE_WINDOW", self.cancel)
        d.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph_ = parent.winfo_width(), parent.winfo_height()
        w, h = d.winfo_reqwidth(), d.winfo_reqheight()
        d.geometry(f"+{max(0, px + (pw - w) // 2)}+{max(0, py + (ph_ - h) // 3)}")
        d.deiconify()
        self.t_url.focus_set()
        try:
            d.grab_set()
        except Exception:
            pass

    def url(self) -> str:
        return clean_ics_url(self.t_url.get("1.0", "end"))

    def say(self, ok: bool, msg: str) -> None:
        self.status.configure(text=("✓ " if ok else "✗ ") + msg, fg=OK_FG if ok else ERR_FG)

    def paste(self) -> None:
        try:
            txt = self.top.clipboard_get()
        except Exception:
            self.say(False, "Το πρόχειρο είναι άδειο.")
            return
        self.t_url.delete("1.0", "end")
        self.t_url.insert("1.0", clean_ics_url(txt))
        self.status.configure(text="")

    def check(self, done=None) -> None:
        u = self.url()
        self.status.configure(text="Έλεγχος…", fg=MUTED)
        self.b_check.state(["disabled"])
        res: dict = {}
        th = threading.Thread(target=lambda: res.update(r=self._check(u)), daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                self.top.after(150, poll)
                return
            try:
                self.b_check.state(["!disabled"])
                self.say(*res.get("r", (False, "Άγνωστο σφάλμα.")))
            except Exception:  # το παράθυρο έκλεισε στο μεταξύ
                return
            if done:
                done()

        poll()

    def ok(self) -> None:
        u = self.url()
        if not u:
            self.say(False, "Επικολλήστε τον σύνδεσμο ICS.")
            return
        if not u.lower().startswith(("http://", "https://")):
            self.say(False, "Ο σύνδεσμος πρέπει να ξεκινά με https:// (ή http://).")
            return
        if u in self._existing:
            self.say(False, "Αυτό το ημερολόγιο υπάρχει ήδη στη λίστα.")
            return
        self.result = (u, self.v_name.get().strip(), bool(self.v_central.get()))
        self._close()

    def cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        try:
            self.top.grab_release()
        except Exception:
            pass
        self.top.destroy()


def run_settings_window(first_run: bool = False, on_ready=None) -> bool:
    """Παράθυρο ρυθμίσεων (tkinter). Επιστρέφει True αν αποθηκεύτηκε.

    on_ready(root, controls): μόνο για αυτόματα τεστ.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    raw_cfg = read_config_raw()
    existing = apply_defaults(raw_cfg)
    existing["store_name"] = raw_cfg.get("store_name", "")  # κενό στην πρώτη εκκίνηση
    saved = {"ok": False}
    cals: list[list] = calendars_from_config(existing)

    root = tk.Tk()
    root.withdraw()
    root.title(f"{APP_NAME} — Ρυθμίσεις")
    root.resizable(False, False)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    set_window_icon(root)
    apply_settings_style(root)
    f = lambda size, weight="normal": ui_font(root, size, weight)  # noqa: E731

    amber_header(root, "Ρυθμίσεις", APP_NAME)
    fr = footer(root)

    body = ttk.Frame(root, padding=(24, 14, 24, 8))
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)
    r = 0
    if first_run:
        ttk.Label(body, text="Καλώς ήρθατε! Συμπληρώστε τα στοιχεία του καταστήματος και "
                  "προσθέστε το κεντρικό ημερολόγιο για να ξεκινήσουν οι υπενθυμίσεις.",
                  style="Welcome.TLabel", wraplength=520, padding=(10, 8)).grid(
            row=r, column=0, columnspan=2, sticky="we", pady=(0, 12))
        r += 1

    ttk.Label(body, text="Κατάστημα", style="Section.TLabel").grid(row=r, column=0, columnspan=2, sticky="w")
    r += 1
    v_name = tk.StringVar(value=existing.get("store_name", ""))
    v_id = tk.StringVar(value=existing.get("store_id", ""))
    ttk.Label(body, text="Όνομα").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
    e_name = ttk.Entry(body, textvariable=v_name, width=40, font=f(11))
    e_name.grid(row=r, column=1, sticky="we", pady=4)
    add_edit_bindings(e_name)
    r += 1
    ttk.Label(body, text="ID").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
    idrow = ttk.Frame(body)
    idrow.grid(row=r, column=1, sticky="we")
    e_id = ttk.Entry(idrow, textvariable=v_id, width=18, font=f(11))
    e_id.pack(side="left")
    add_edit_bindings(e_id)
    ttk.Label(idrow, text="  λατινικά γράμματα ή/και αριθμοί, π.χ. peristeri ή 12", style="Muted.TLabel").pack(side="left")
    r += 1

    ttk.Label(body, text="Ημερολόγια", style="Section.TLabel").grid(
        row=r, column=0, columnspan=2, sticky="w", pady=(16, 4))
    r += 1
    tree = ttk.Treeview(body, columns=("name", "kind"), show="headings", height=4,
                        style="Cal.Treeview", selectmode="browse")
    tree.heading("name", text="Ημερολόγιο", anchor="w")
    tree.heading("kind", text="Τύπος", anchor="w")
    tree.column("name", width=400, anchor="w")
    tree.column("kind", width=130, anchor="w", stretch=False)
    tree.tag_configure("central", font=f(11, "bold"))
    tree.grid(row=r, column=0, columnspan=2, sticky="we")
    r += 1
    side = ttk.Frame(body)
    side.grid(row=r, column=0, columnspan=2, sticky="we", pady=(8, 0))
    r += 1

    def refresh(select: int | None = None):
        tree.delete(*tree.get_children())
        for i, (u, n, central) in enumerate(cals):
            tree.insert("", "end", iid=str(i),
                        values=(("★ " if central else "    ") + (n or short_url(u)),
                                "Κεντρικό" if central else "Καταστήματος"),
                        tags=("central",) if central else ())
        if select is not None and 0 <= select < len(cals):
            tree.selection_set(str(select))
            tree.see(str(select))

    def apply_calendar(res, idx=None):
        u, n, central = res
        if central:
            for c in cals:
                c[2] = False
        item = [u, n, central]
        if idx is None:
            cals.append(item)
        else:
            cals[idx] = item
        cals.sort(key=lambda c: not c[2])  # το κεντρικό πρώτο
        refresh(cals.index(item))
        status.config(text="")

    def selected() -> int | None:
        sel = tree.selection()
        return int(sel[0]) if sel else None

    def on_add():
        dlg = CalendarDialog(root, central=not any(c[2] for c in cals),
                             existing_urls=[c[0] for c in cals])
        root.wait_window(dlg.top)
        if dlg.result:
            apply_calendar(dlg.result)

    def on_edit():
        i = selected()
        if i is None:
            status.config(text="Επιλέξτε πρώτα ένα ημερολόγιο από τη λίστα.", fg=ERR_FG)
            return
        u, n, c = cals[i]
        dlg = CalendarDialog(root, u, n, c, title="Αλλαγή ημερολογίου",
                             existing_urls=[x[0] for x in cals])
        root.wait_window(dlg.top)
        if dlg.result:
            apply_calendar(dlg.result, i)

    def on_remove():
        i = selected()
        if i is None:
            status.config(text="Επιλέξτε πρώτα ένα ημερολόγιο από τη λίστα.", fg=ERR_FG)
            return
        u, n, c = cals[i]
        label = n or short_url(u)
        if not messagebox.askyesno(APP_NAME, f"Αφαίρεση του ημερολογίου «{label}»;", parent=root):
            return
        del cals[i]
        refresh()

    def on_test_all():
        if not cals:
            status.config(text="Δεν υπάρχουν ημερολόγια για έλεγχο.", fg=ERR_FG)
            return
        status.config(text="Έλεγχος ημερολογίων…", fg=MUTED)
        todo = [(c[1] or short_url(c[0]), c[0]) for c in cals]
        result: dict = {}

        def work():
            lines, bad = [], False
            for label, u in todo:
                ok, msg = check_ics(u)
                bad = bad or not ok
                lines.append(f"{'✓' if ok else '✗'} {label}: {msg}")
            result["text"], result["bad"] = "\n".join(lines), bad

        th = threading.Thread(target=work, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                root.after(200, poll)
                return
            status.config(text=result.get("text", ""), fg=ERR_FG if result.get("bad") else OK_FG)

        root.after(200, poll)

    ttk.Button(side, text="＋ Προσθήκη", command=on_add).pack(side="left")
    ttk.Button(side, text="Αλλαγή", command=on_edit).pack(side="left", padx=8)
    ttk.Button(side, text="Αφαίρεση", command=on_remove).pack(side="left")
    ttk.Button(side, text="Έλεγχος όλων", command=on_test_all).pack(side="right")
    tree.bind("<Double-1>", lambda e: on_edit())
    tree.bind("<Delete>", lambda e: on_remove())

    ttk.Label(body, text="Ήχος", style="Section.TLabel").grid(
        row=r, column=0, columnspan=2, sticky="w", pady=(16, 4))
    r += 1
    srow = ttk.Frame(body)
    srow.grid(row=r, column=0, columnspan=2, sticky="w")
    r += 1
    v_sound = tk.BooleanVar(value=bool(existing.get("sound", True)))
    ttk.Checkbutton(srow, text="Ήχος ειδοποίησης για", variable=v_sound).pack(side="left")
    v_sec = tk.StringVar(value=str(existing.get("sound_seconds", 10)))
    ttk.Spinbox(srow, from_=1, to=600, textvariable=v_sec, width=5, font=f(11)).pack(side="left", padx=6)
    ttk.Label(srow, text="δευτερόλεπτα").pack(side="left")

    status = tk.Label(body, text="", font=f(10, "semi"), fg=ERR_FG, bg="#FFFFFF",
                      wraplength=540, justify="left", anchor="w")
    status.grid(row=r, column=0, columnspan=2, sticky="we", pady=(10, 0))

    def collect():
        vals = {
            "store_name": v_name.get(),
            "store_id": v_id.get(),
            "sound": v_sound.get(),
            "sound_seconds": v_sec.get(),
        }
        vals.update(calendar_fields(cals))
        return vals

    def on_save():
        cfg, errors = build_config(collect(), read_config_raw())
        if errors:
            status.config(text="\n".join(errors), fg=ERR_FG)
            return
        try:
            save_config(cfg)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Δεν αποθηκεύτηκε το config.json:\n{e}", parent=root)
            return
        saved["ok"] = True
        root.destroy()

    ttk.Button(fr, text="Αποθήκευση", style="Primary.TButton", command=on_save).pack(side="right")
    ttk.Button(fr, text="Άκυρο", command=root.destroy).pack(side="right", padx=8)
    root.bind("<Return>", lambda e: on_save() if e.widget.winfo_toplevel() is root
              and e.widget.winfo_class() not in ("Text", "Treeview", "TButton") else None)
    root.bind("<Escape>", lambda e: root.destroy() if e.widget.winfo_toplevel() is root else None)
    refresh(0 if cals else None)

    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
    root.deiconify()
    root.lift()
    root.focus_force()
    if on_ready:
        controls = {
            "store_name": v_name, "store_id": v_id, "sound": v_sound, "sound_seconds": v_sec,
            "status": status, "save": on_save, "cancel": root.destroy, "tree": tree,
            "calendars": cals, "add_calendar": lambda u, n="", c=False: apply_calendar(
                (clean_ics_url(u), n, c)),
            "remove_selected": lambda: (cals.pop(selected()), refresh()) if selected() is not None else None,
        }
        root.after(100, lambda: on_ready(root, controls))
    root.mainloop()
    return saved["ok"]


def settings_command() -> list[str]:
    """Εντολή για να ανοίξει το παράθυρο ρυθμίσεων σε ξεχωριστή διεργασία."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--settings"]
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    if sys.platform.startswith("win") and w.exists():
        exe = w
    return [str(exe), str(Path(__file__).resolve()), "--settings"]


def open_settings_async(engine: ReminderEngine, on_done=None) -> None:
    """Ανοίγει τις ρυθμίσεις σε δική τους διεργασία (για να μη μπλέκει το tkinter με
    το tray/popup) και μετά ξαναφορτώνει το config χωρίς επανεκκίνηση."""
    if getattr(engine, "_settings_open", False):
        return
    engine._settings_open = True

    def run():
        try:
            subprocess.call(settings_command(), cwd=str(BASE))
        except Exception as e:
            log(f"settings: {e!r}")
        finally:
            engine._settings_open = False
        if engine.reload_config() and on_done:
            try:
                on_done()
            except Exception:
                pass

    threading.Thread(target=run, daemon=True).start()


_instance_handle = None


def acquire_single_instance() -> bool:
    """Στα Windows: μόνο ένα αντίγραφο της εφαρμογής ανά χρήστη."""
    global _instance_handle
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        _instance_handle = k32.CreateMutexW(None, False, "Local\\YpenthimiseisKatastimaton")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def resource_dirs() -> list[Path]:
    """Πού ψάχνουμε εικονίδια: μέσα στο .exe (_MEIPASS), δίπλα στο .exe/app.py, installer/."""
    here = Path(__file__).resolve().parent
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs += [Path(meipass), Path(meipass) / "icon-png"]
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
    dirs += [here, here / "installer", here / "installer" / "icon-png"]
    return dirs


def find_resource(name: str) -> Path | None:
    for d in resource_dirs():
        p = d / name
        if p.exists():
            return p
    return None


def _drawn_icon(size: int):
    """Εφεδρικό εικονίδιο (αν λείπουν τα αρχεία): κίτρινο τετράγωνο σε σκούρο φόντο."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "#1a1a1a")
    d = ImageDraw.Draw(img)
    m = size // 8
    d.rectangle((m, m, size - m, size - m), fill="#f5c84b")
    return img


TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)


def make_icon_image(size: int = 64):
    """Το εικονίδιο του tray: ίδιο artwork με το icon.ico (καμπανάκι).

    Φορτώνει τα PNG (icon_16.png … icon_64.png) ή το icon.ico. Όταν το pystray το
    γράψει ως ICO, βάζουμε τα έτοιμα καρέ ανά μέγεθος, ώστε τα 16x16 να είναι το
    καθαρό pixel-art και όχι σμίκρυνση. Αν λείπουν όλα, ζωγραφίζει το παλιό.
    """
    from PIL import Image

    frames = {}
    for s in TRAY_SIZES:
        p = find_resource(f"icon_{s}.png")
        if p:
            try:
                frames[s] = Image.open(p).convert("RGBA")
            except Exception:
                pass
    if not frames:
        ico = find_resource("icon.ico")
        if ico:
            try:
                im = Image.open(ico)
                for s in TRAY_SIZES:
                    if (s, s) in im.info.get("sizes", set()):
                        im.size = (s, s)
                        frames[s] = im.copy().convert("RGBA")
            except Exception:
                frames = {}
    if not frames:
        return _drawn_icon(size)

    best = frames.get(size) or frames[max(frames)]
    img = best.copy()
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    extra = [f for s, f in sorted(frames.items()) if s != size]
    orig_save = img.save

    def save(fp, format=None, **params):
        if str(format or "").upper() == "ICO":
            params.setdefault("sizes", [(s, s) for s in sorted(set(frames) | {size})])
            params.setdefault("append_images", extra)
        return orig_save(fp, format=format, **params)

    img.save = save  # pystray: image.save(f, format="ICO")
    return img


def setup_tray(engine: ReminderEngine):
    try:
        import pystray

        img = make_icon_image(64)
    except Exception:
        play_loop(engine)
        return

    def open_calendar(icon, item):
        webbrowser.open("https://calendar.google.com")

    def sync_now(icon, item):
        engine.wake.set()

    def settings(icon, item):
        def done():
            try:
                icon.update_menu()
            except Exception:
                pass

        open_settings_async(engine, done)

    def exit_app(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: engine.cfg.get("store_name", APP_NAME), None, enabled=False),
        pystray.MenuItem("Συγχρονισμός τώρα", sync_now),
        pystray.MenuItem("Ρυθμίσεις", settings),
        pystray.MenuItem("Άνοιγμα Google Calendar", open_calendar),
        pystray.MenuItem("Έξοδος", exit_app),
    )
    icon = pystray.Icon("store_reminders", img, APP_NAME, menu)

    t = threading.Thread(target=play_loop, args=(engine,), daemon=True)
    t.start()
    icon.run()


def main():
    install_crash_logging()
    if "--settings" in sys.argv[1:]:
        run_settings_window(first_run=not config_is_complete(read_config_raw()))
        return
    if not acquire_single_instance():
        return
    if not config_is_complete(read_config_raw()):
        # Πρώτη εκκίνηση ή χωρίς ICS: άνοιξε τις ρυθμίσεις αντί για σφάλμα.
        try:
            ok = run_settings_window(first_run=True)
        except Exception as e:
            log(f"first-run settings: {e!r}")
            ok = False
        # Τα αντικείμενα Tk του παραθύρου ρυθμίσεων μαζεύονται ΕΔΩ, στο νήμα τους,
        # πριν ξεκινήσει το νήμα των υπενθυμίσεων.
        import gc

        gc.collect()
        if not ok or not config_is_complete(read_config_raw()):
            return
    log(f"start (pid {os.getpid()}, data {BASE})")
    cfg = load_config()
    engine = ReminderEngine(cfg)
    setup_tray(engine)


if __name__ == "__main__":
    main()
