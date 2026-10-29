#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Εγκαταστάτης — φάκελος χρήστη, εκκίνηση Windows, config."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_FILES = ["app.py", "requirements.txt"]


def user_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Ypenthimiseis"
    return Path.home() / "ypenthimiseis"


def source_dir() -> Path:
    return Path(__file__).resolve().parent


def find_python() -> tuple[Path, Path]:
    """(python.exe, pythonw.exe) — οτι υπάρχει στο PATH."""
    candidates = []
    for args in (
        ["py", "-3", "-c", "import sys; print(sys.executable)"],
        ["python", "-c", "import sys; print(sys.executable)"],
    ):
        try:
            out = subprocess.check_output(args, text=True, timeout=20).strip()
            if out:
                candidates.append(Path(out))
        except Exception:
            pass
    candidates.append(Path(sys.executable))
    for p in candidates:
        if not p.exists():
            continue
        w = p.with_name("pythonw.exe")
        if not w.exists():
            w = p
        return p, w
    raise SystemExit("Δεν βρέθηκε Python στο PATH. Εγκατάστησέ την με Add python.exe to PATH.")


def startup_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("Δεν βρέθηκε APPDATA.")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "ypenthimiseis-katastimaton.bat"
    )


def write_startup(dest: Path, pythonw: Path) -> Path:
    bat = startup_path()
    bat.parent.mkdir(parents=True, exist_ok=True)
    bat.write_text(
        f'@echo off\r\ncd /d "{dest}"\r\nstart "" "{pythonw}" app.py\r\n',
        encoding="utf-8",
    )
    return bat


def install(values: dict) -> str:
    src = source_dir()
    dest = user_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for name in APP_FILES:
        s = src / name
        if not s.exists():
            raise SystemExit(f"Λείπει το {name} δίπλα στον εγκαταστάτη.")
        shutil.copy2(s, dest / name)

    extras = [u.strip() for u in values["ics_urls"].splitlines() if u.strip()]
    cfg = {
        "store_name": values["store_name"].strip() or "Κατάστημα",
        "store_id": values["store_id"].strip().lower(),
        "ics_url": values["ics_url"].strip(),
        "ics_urls": extras,
        "poll_seconds": 30,
        "minutes_before": 0,
        "show_missed_max_minutes": 15,
        "sound": True,
        "sound_seconds": int(values.get("sound_seconds") or 10),
    }
    (dest / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    py, pythonw = find_python()
    subprocess.check_call(
        [str(py), "-m", "pip", "install", "-r", str(dest / "requirements.txt")],
        cwd=str(dest),
    )
    bat = write_startup(dest, pythonw)
    # εκκίνηση τώρα
    subprocess.Popen([str(pythonw), str(dest / "app.py")], cwd=str(dest))
    return (
        f"Εγκατάσταση στον φάκελο:\n{dest}\n\n"
        f"Εκκίνηση Windows:\n{bat}\n\n"
        "Μπορείς να αλλάξεις όλα αργότερα στο config.json του ίδιου φακέλου.\n"
        "Η εφαρμογή άνοιξε τώρα στο tray."
    )



def ask(prompt, default=""):
    extra = f" [{default}]" if default != "" else ""
    val = input(f"{prompt}{extra}: ").strip()
    return val if val else default


def run_console():
    print()
    print("=== Egkatastasi ypenthimiseon ===")
    print("Fakelos:", user_dir())
    print()
    name = ask("Onoma katastimatos")
    sid = ask("ID katastimatos (latinika grammata i/kai arithmoi, px peristeri i 12)")
    ics = ask("Kentriko ICS URL")
    print("Alla ICS (ena ana grammi, kenh grammi gia telos):")
    extras = []
    while True:
        line = input("  ").strip()
        if not line:
            break
        extras.append(line)
    sec = ask("Deyterolepta ihou", "10")
    if not name or not sid or not ics:
        raise SystemExit("Prepei onoma, ID kai kentriko ICS.")
    if "http" not in ics.lower():
        raise SystemExit("To ICS prepei na einai http(s) syndesmos.")
    msg = install(
        {
            "store_name": name,
            "store_id": sid,
            "ics_url": ics,
            "ics_urls": "\n".join(extras),
            "sound_seconds": int(sec or "10"),
        }
    )
    print()
    print(msg)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        run_console()
    except Exception as e:
        print("Sfalma:", e)
        raise
