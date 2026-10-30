# -*- coding: utf-8 -*-
"""Τεστ για τις ρυθμίσεις (χωρίς δίκτυο). Τρέξιμο: python -m pytest -q tests"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402

GOOD = {
    "store_name": "Κατάστημα Δοκιμή",
    "store_id": "dokimi",
    "ics_url": "https://example.com/central.ics",
    "ics_urls": "https://example.com/a.ics\n\n  https://example.com/b.ics  \n",
    "sound_seconds": "12",
}


@pytest.fixture
def tmpcfg(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(app, "CONFIG_PATH", p)
    monkeypatch.setattr(app, "STATE_PATH", tmp_path / "state.json")
    return p


def test_build_config_ok_and_defaults():
    cfg, errors = app.build_config(GOOD)
    assert errors == []
    assert cfg["store_id"] == "dokimi"
    assert cfg["ics_urls"] == ["https://example.com/a.ics", "https://example.com/b.ics"]
    assert cfg["sound_seconds"] == 12
    assert cfg["poll_seconds"] == 30
    assert cfg["minutes_before"] == 0
    assert cfg["show_missed_max_minutes"] == 15
    assert cfg["sound"] is True


def test_build_config_keeps_existing_fields():
    existing = {"poll_seconds": 60, "minutes_before": 5, "sound": False, "custom": 1}
    cfg, errors = app.build_config(GOOD, existing)
    assert not errors
    assert cfg["poll_seconds"] == 60 and cfg["minutes_before"] == 5
    assert cfg["sound"] is False and cfg["custom"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("store_name", ""),
        ("store_id", ""),
        ("store_id", "Περιστέρι"),
        ("store_id", "peri steri"),
        ("ics_url", ""),
        ("ics_url", "calendar.google.com/x.ics"),
        ("ics_urls", "ftp://bad"),
        ("sound_seconds", "abc"),
        ("sound_seconds", "0"),
    ],
)
def test_build_config_validation(field, value):
    vals = dict(GOOD, **{field: value})
    _, errors = app.build_config(vals)
    assert errors, (field, value)


@pytest.mark.parametrize("raw,expected", [
    ("12", "12"), ("007", "007"), ("peristeri", "peristeri"), ("Peristeri2", "peristeri2"),
    ("kat-3", "kat-3"), ("a_1", "a_1"), (" 15 ", "15"),
])
def test_store_id_letters_digits_or_mixed(raw, expected, tmpcfg):
    cfg, errors = app.build_config(dict(GOOD, store_id=raw))
    assert not errors and cfg["store_id"] == expected
    app.save_config(cfg)
    assert app.load_config()["store_id"] == expected  # μένει κείμενο, όχι αριθμός


@pytest.mark.parametrize("raw", ["περιστέρι", "12 3", "12!", "", "   "])
def test_store_id_invalid(raw):
    _, errors = app.build_config(dict(GOOD, store_id=raw))
    assert any("ID" in e for e in errors)


def test_numeric_store_id_targeting():
    eng = app.ReminderEngine(app.apply_defaults(dict(GOOD, store_id="12")))
    tags, clean = app.parse_target_tags("[12, peristeri] Ψυγείο 2", "")
    assert tags == ["12", "peristeri"] and clean == "Ψυγείο 2"
    assert eng._for_this_store({"tags": tags})
    assert not eng._for_this_store({"tags": ["13"]})
    assert app.ReminderEngine(app.apply_defaults(dict(GOOD, store_id=12)))._for_this_store({"tags": ["12"]})


def test_store_id_hint_same_in_installer_and_settings():
    hint = "λατινικά γράμματα ή/και αριθμοί, π.χ. peristeri ή 12"
    root = Path(__file__).resolve().parents[1]
    iss = (root / "installer" / "Ypenthimiseis.iss").read_text(encoding="utf-8-sig")
    src = (root / "app.py").read_text(encoding="utf-8")
    assert f"ID καταστήματος ({hint}):" in iss and hint in src
    assert "(C >= '0') and (C <= '9')" in iss  # ο έλεγχος του οδηγού δέχεται ψηφία
    err = "Το ID δέχεται μόνο λατινικά γράμματα, αριθμούς, - ή _ (π.χ. peristeri ή 12)."
    assert err in iss and err in src


def test_store_id_lowercased():
    cfg, errors = app.build_config(dict(GOOD, store_id="  Peristeri "))
    assert not errors and cfg["store_id"] == "peristeri"


def test_save_load_roundtrip_utf8(tmpcfg):
    cfg, _ = app.build_config(GOOD)
    app.save_config(cfg)
    text = tmpcfg.read_text(encoding="utf-8")
    assert "Κατάστημα Δοκιμή" in text  # όχι \\u escapes
    loaded = app.load_config()
    assert loaded["store_name"] == "Κατάστημα Δοκιμή"
    assert app.calendar_urls(loaded)[0] == "https://example.com/central.ics"


def test_load_config_with_bom(tmpcfg):
    # Inno Setup / Σημειωματάριο μπορεί να γράψουν BOM
    tmpcfg.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ics_url": "https://x/y.ics"}).encode())
    assert app.config_is_complete(app.read_config_raw())
    assert app.load_config()["sound_seconds"] == 10


def test_missing_config_is_incomplete(tmpcfg):
    assert not app.config_is_complete(app.read_config_raw())
    tmpcfg.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert app.read_config_raw() == {}


def test_engine_reload_config(tmpcfg):
    app.save_config(app.build_config(GOOD)[0])
    eng = app.ReminderEngine(app.load_config())
    assert eng.cfg["store_id"] == "dokimi"
    app.save_config(app.build_config(dict(GOOD, store_id="kalamata"))[0])
    assert eng.reload_config() is True
    assert eng.cfg["store_id"] == "kalamata"
    assert eng.wake.is_set()
    # σπασμένο config -> κρατά το παλιό
    tmpcfg.write_text("{}", encoding="utf-8")
    assert eng.reload_config() is False
    assert eng.cfg["store_id"] == "kalamata"


def test_settings_command_source():
    cmd = app.settings_command()
    assert cmd[-1] == "--settings"
    assert cmd[1].endswith("app.py")


def _has_display():
    try:
        import tkinter

        r = tkinter.Tk()
        r.destroy()
        return True
    except Exception:
        return False


def _run_window(**kw):
    import tkinter

    try:
        return app.run_settings_window(**kw)
    except tkinter.TclError as e:  # π.χ. σπασμένη εγκατάσταση Tcl στον CI runner
        pytest.skip(f"Tk μη διαθέσιμο: {str(e)[:80]}")


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_settings_window_saves(tmpcfg):
    def fill(root, c):
        c["store_name"].set("Κατάστημα Παράθυρο")
        c["store_id"].set("bad id")
        c["save"]()  # χωρίς ημερολόγια + λάθος ID -> δεν κλείνει
        assert "ID" in c["status"].cget("text")
        assert "κεντρικό" in c["status"].cget("text").lower()
        c["add_calendar"]("  https://example.com/extra.ics\n", "Παραλαβές", False)
        c["add_calendar"]("https://example.com/c.ics", "Κεντρικό πρόγραμμα", True)
        assert c["calendars"][0][0] == "https://example.com/c.ics"  # το κεντρικό πρώτο
        assert len(c["tree"].get_children()) == 2
        c["sound_seconds"].set("7")
        c["store_id"].set(" 12 ")  # μόνο αριθμοί
        c["save"]()

    assert _run_window(first_run=True, on_ready=fill) is True
    cfg = app.load_config()
    assert cfg["store_id"] == "12"
    assert cfg["ics_url"] == "https://example.com/c.ics"
    assert cfg["ics_urls"] == ["https://example.com/extra.ics"]
    assert cfg["ics_names"] == {"https://example.com/c.ics": "Κεντρικό πρόγραμμα",
                                "https://example.com/extra.ics": "Παραλαβές"}
    assert cfg["sound_seconds"] == 7


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_settings_window_old_config_and_change_central(tmpcfg):
    """Παλιό config (χωρίς ics_names, ics_urls ως κείμενο) ανοίγει σωστά."""
    tmpcfg.write_text(json.dumps({
        "store_name": "Παλιό", "store_id": "palio", "ics_url": "https://example.com/old.ics",
        "ics_urls": "https://example.com/x.ics", "poll_seconds": 45}), encoding="utf-8")

    def go(root, c):
        assert [x[0] for x in c["calendars"]] == ["https://example.com/old.ics",
                                                  "https://example.com/x.ics"]
        assert c["calendars"][0][2] is True
        c["add_calendar"]("webcal://example.com/new.ics", "", True)  # νέο κεντρικό
        c["save"]()

    assert _run_window(on_ready=go) is True
    cfg = app.load_config()
    assert cfg["ics_url"] == "https://example.com/new.ics"
    assert set(cfg["ics_urls"]) == {"https://example.com/old.ics", "https://example.com/x.ics"}
    assert "ics_names" not in cfg and cfg["poll_seconds"] == 45


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_settings_window_cancel_keeps_config(tmpcfg):
    app.save_config(app.build_config(GOOD)[0])
    before = tmpcfg.read_text(encoding="utf-8")

    def cancel(root, c):
        assert c["store_id"].get() == "dokimi"  # προσυμπληρωμένο
        c["store_id"].set("allagi")
        c["cancel"]()

    assert _run_window(on_ready=cancel) is False
    assert tmpcfg.read_text(encoding="utf-8") == before


def test_open_settings_async_reloads(tmpcfg, monkeypatch):
    """Η διεργασία ρυθμίσεων γράφει νέο config -> η μηχανή το φορτώνει χωρίς restart."""
    import threading

    app.save_config(app.build_config(GOOD)[0])
    eng = app.ReminderEngine(app.load_config())
    new_cfg = app.build_config(dict(GOOD, store_id="neo"))[0]
    script = (
        "import json,sys; json.dump(json.loads(sys.argv[2]), "
        "open(sys.argv[1],'w',encoding='utf-8'), ensure_ascii=False)"
    )
    monkeypatch.setattr(
        app, "settings_command",
        lambda: [sys.executable, "-c", script, str(tmpcfg), json.dumps(new_cfg)],
    )
    done = threading.Event()
    app.open_settings_async(eng, done.set)
    assert done.wait(20)
    assert eng.cfg["store_id"] == "neo"
    assert eng._settings_open is False


def test_tray_icon_uses_artwork_and_crisp_16(tmp_path):
    """Το εικονίδιο του tray φορτώνει το artwork· στο ICO του pystray τα 16x16 είναι το pixel-art."""
    from PIL import Image, ImageChops

    img = app.make_icon_image(64)
    assert img.size == (64, 64)
    out = tmp_path / "tray.ico"
    with out.open("wb") as f:
        img.save(f, format="ICO")  # όπως το κάνει το pystray
    ico = Image.open(out)
    assert (16, 16) in ico.info["sizes"]
    ico.size = (16, 16)
    frame = ico.copy().convert("RGBA")
    ref = Image.open(Path(app.__file__).parent / "installer" / "icon-png" / "icon_16.png").convert("RGBA")
    assert ImageChops.difference(frame, ref).getbbox() is None


def test_tray_icon_fallback(monkeypatch):
    monkeypatch.setattr(app, "find_resource", lambda name: None)
    img = app.make_icon_image(64)
    assert img.size == (64, 64)


# ---------------------------------------------------------------- ημερολόγια / διάλογος

def test_calendars_roundtrip_and_old_configs():
    cfg = {"ics_url": "https://a/c.ics", "ics_urls": ["https://a/1.ics", "https://a/c.ics", " "],
           "ics_names": {"https://a/1.ics": "Ένα", "https://gone/x.ics": "παλιό"}}
    cals = app.calendars_from_config(cfg)
    assert cals == [["https://a/c.ics", "", True], ["https://a/1.ics", "Ένα", False]]
    assert app.calendar_fields(cals) == {"ics_url": "https://a/c.ics", "ics_urls": ["https://a/1.ics"],
                                        "ics_names": {"https://a/1.ics": "Ένα"}}
    # placeholder του config.example.json και ics_names σε λάθος μορφή αγνοούνται
    assert app.calendars_from_config({"ics_url": "https://XXXX", "ics_names": ["x"]}) == []


def test_build_config_ics_names():
    vals = dict(GOOD, ics_names={"https://example.com/a.ics": " Α ", "https://other/z.ics": "Ζ",
                                 "https://example.com/b.ics": "  "})
    cfg, errors = app.build_config(vals)
    assert not errors
    assert cfg["ics_names"] == {"https://example.com/a.ics": "Α"}
    # χωρίς ics_names στη φόρμα: κρατά τα υπάρχοντα (για όσα URL μένουν)
    cfg2, _ = app.build_config(GOOD, {"ics_names": {"https://example.com/b.ics": "Β", "https://x/y": "Υ"}})
    assert cfg2["ics_names"] == {"https://example.com/b.ics": "Β"}


def test_clean_and_short_url():
    assert app.clean_ics_url("  https://cal.example.com/a b\n/basic.ics \n") == "https://cal.example.com/ab/basic.ics"
    assert app.clean_ics_url("webcal://x.com/c.ics") == "https://x.com/c.ics"
    s = app.short_url("https://calendar.google.com/calendar/ical/abc%40group/private-SECRET/basic.ics")
    assert s == "calendar.google.com/…/basic.ics" and "SECRET" not in s


def test_ctrl_keys_work_with_greek_layout():
    assert app.ctrl_key_action(86, "Greek_omega") == "<<Paste>>"
    assert app.ctrl_key_action(67, "Greek_psi") == "<<Copy>>"
    assert app.ctrl_key_action(88, "Greek_chi") == "<<Cut>>"
    assert app.ctrl_key_action(86, "v") is None  # λατινικά: το χειρίζεται ήδη το Tk
    assert app.ctrl_key_action(65, "Greek_alpha") == "select-all"
    assert app.ctrl_key_action(81, "q") is None


class _Resp:
    def __init__(self, code, body=b""):
        self.status_code, self.content = code, body


def test_check_ics_messages(monkeypatch):
    ics = (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\nBEGIN:VEVENT\r\nUID:1\r\n"
           b"DTSTART:20260101T100000Z\r\nSUMMARY:a\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    monkeypatch.setattr(app.requests, "get", lambda u, timeout: _Resp(200, ics))
    assert app.check_ics(" https://x/y.ics\n") == (True, "Εντάξει — βρέθηκαν 1 γεγονότα.")
    monkeypatch.setattr(app.requests, "get", lambda u, timeout: _Resp(404))
    ok, msg = app.check_ics("https://x/y.ics")
    assert not ok and "404" in msg
    monkeypatch.setattr(app.requests, "get", lambda u, timeout: _Resp(200, b"<html>login</html>"))
    ok, msg = app.check_ics("https://x/y.ics")
    assert not ok and "iCal" in msg

    def boom(u, timeout):
        raise app.requests.exceptions.ConnectionError("x")
    monkeypatch.setattr(app.requests, "get", boom)
    ok, msg = app.check_ics("https://x/y.ics")
    assert not ok and "σύνδεση" in msg
    assert app.check_ics("ftp://x")[0] is False
    assert app.check_ics("")[0] is False


def _tk_root():
    import tkinter

    try:
        return tkinter.Tk()
    except tkinter.TclError as e:
        pytest.skip(f"Tk μη διαθέσιμο: {str(e)[:80]}")


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_calendar_dialog_trim_paste_check_ok():
    root = _tk_root()
    try:
        dlg = app.CalendarDialog(root, existing_urls=["https://dup/x.ics"],
                                 check=lambda u: (True, f"Εντάξει — {u}"))
        root.clipboard_clear()
        root.clipboard_append("  https://cal.example.com/very/long\n/basic.ics  \n")
        dlg.paste()
        assert dlg.url() == "https://cal.example.com/very/long/basic.ics"
        done = []
        dlg.check(done=lambda: done.append(1))
        for _ in range(100):
            root.update()
            if done:
                break
            time.sleep(0.02)
        assert done and dlg.status.cget("text").startswith("✓ Εντάξει")
        dlg.v_name.set("  Παραλαβές ")
        dlg.v_central.set(True)
        dlg.ok()
        assert dlg.result == ("https://cal.example.com/very/long/basic.ics", "Παραλαβές", True)

        dup = app.CalendarDialog(root, existing_urls=["https://dup/x.ics"])
        dup.t_url.insert("1.0", "https://dup/x.ics")
        dup.ok()
        assert dup.result is None and "υπάρχει ήδη" in dup.status.cget("text")
        dup.t_url.delete("1.0", "end")
        dup.t_url.insert("1.0", "calendar.google.com/x.ics")
        dup.ok()
        assert dup.result is None and "https://" in dup.status.cget("text")
        dup.cancel()
        assert dup.result is None
    finally:
        root.destroy()


# ---------------------------------------------------------------- popup

class _Eng:
    def __init__(self):
        self.cfg = {"store_name": "Κατάστημα Περιστέρι", "sound": False}
        self.calls = []

    def dismiss(self, k):
        self.calls.append(("dismiss", k))

    def snooze(self, k, m):
        self.calls.append(("snooze", k, m))


def _ev(title="Παραλαβή κρέατος", desc="Περιγραφή.", key="k1"):
    from datetime import datetime
    return {"key": key, "title": title, "description": desc, "start": datetime(2026, 10, 29, 12, 0)}


def _settle(root, seconds=0.4):
    """Αφήνει το Tk να ολοκληρώσει τη διόρθωση ύψους που γίνεται μετά την εμφάνιση."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.02)


def _build(ov, ev, pos=None):
    import tkinter

    try:
        return ov.build(ev, pos)
    except tkinter.TclError as e:
        pytest.skip(f"Tk μη διαθέσιμο: {str(e)[:80]}")


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_popup_long_title_shrinks_and_fits():
    eng = _Eng()
    ov = app.Overlay(eng)
    root = _build(ov, _ev())
    short = dict(ov.layout)
    root.destroy()
    long_title = "Απογραφή ψυγείων και καταγραφή θερμοκρασιών " * 6
    root = _build(ov, _ev(long_title, "Πολύ μεγάλη περιγραφή. " * 200), (2, 3))
    try:
        assert short["title_size"] == 32 and short["title"] == "Παραλαβή κρέατος"
        assert ov.layout["title_size"] < 32
        assert ov.layout["title"].endswith("…")
        assert ov.layout["height"] <= max(420, root.winfo_screenheight() - 80)
        if sys.platform == "win32":  # στο X11 χωρίς window manager δεν αναφέρεται
            assert root.attributes("-topmost")
    finally:
        root.destroy()


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_popup_keys_enter_dismiss_esc_snooze(monkeypatch):
    eng = _Eng()
    ov = app.Overlay(eng)
    _build(ov, _ev(key="a"))
    ov._key(ov._dismiss)  # μέσα στο διάστημα προστασίας: αγνοείται
    assert eng.calls == [] and ov.root is not None
    ov._keys_after = 0
    ov.root.event_generate("<Return>", when="now")
    if ov.root is not None:
        ov.root.update()
    assert eng.calls == [("dismiss", "a")] and ov.root is None

    _build(ov, _ev(key="b"))
    ov._keys_after = 0
    ov.root.event_generate("<Escape>", when="now")
    if ov.root is not None:
        ov.root.update()
    assert eng.calls[-1] == ("snooze", "b", 5) and ov.root is None


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_popup_close_does_not_crash_process():
    """Παλινδρόμηση: «Το είδα» έκλεινε ΟΛΗ την εφαρμογή (Tcl_Panic στο tcl86t.dll).
    Πολλές υπενθυμίσεις στη σειρά (κλικ «Το είδα», κλικ «Σε 5 λεπτά», Enter, Esc) σε νήμα,
    με GC από άλλο νήμα: η διεργασία πρέπει να ζει και κάθε κλείσιμο να καταγράφεται."""
    import subprocess

    script = Path(__file__).with_name("popup_stress.py")
    r = subprocess.run([sys.executable, str(script), "16"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240)
    assert r.returncode == 0, (r.returncode, r.stdout[-2000:], r.stderr[-2000:])
    assert "ALIVE" in r.stdout and "calls=16" in r.stdout, r.stdout
    assert "click_fallbacks=0" in r.stdout, r.stdout  # κάθε κουμπί κλείνει με το δικό του κλικ
    assert "('dismiss', 'k0')" in r.stdout and "('snooze', 'k1', 5)" in r.stdout


def test_crash_logging_writes_to_app_log(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr(app, "LOG_PATH", tmp_path / "app.log")
    old = sys.excepthook, threading.excepthook, sys.stderr, sys.stdout
    import gc

    gc.collect()  # αντικείμενα Tk από προηγούμενα τεστ: να μη μαζευτούν στο νήμα «boom»
    try:
        app.install_crash_logging()
        th = threading.Thread(target=lambda: 1 / 0, name="boom")
        th.start()
        th.join()
        app.tk_report_exception(ValueError, ValueError("tk-err"), None)
    finally:
        import faulthandler

        faulthandler.disable()
        sys.excepthook, threading.excepthook, sys.stderr, sys.stdout = old
        if app._crash_file:
            app._crash_file.close()
            app._crash_file = None
    text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "unhandled in thread boom" in text and "ZeroDivisionError" in text
    assert "tk callback" in text and "tk-err" in text


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
@pytest.mark.parametrize("work", [(0, 0, 1366, 728), (0, 0, 1093, 582), (0, 0, 911, 485)],
                         ids=["1366x768", "125%", "150%"])
def test_popup_long_text_grows_then_scrolls_never_cut(work):
    """Μικρό κείμενο: χωρά ολόκληρο. Μεγάλο: το παράθυρο μεγαλώνει έως ~80% του ύψους
    εργασίας και μετά η περιγραφή κυλά — ολόκληρη, χωρίς «…» — και τα κουμπιά μένουν
    πάντα μέσα στην οθόνη (και στο 125%/150%)."""
    eng = _Eng()
    ov = app.Overlay(eng)
    ov.work_area = work
    wx, wy, ww, wh = work

    def inside(root):
        _settle(root)
        g = root.winfo_geometry()  # π.χ. 720x553+323+87
        size, y = g.split("+")[0], int(g.split("+")[2])
        w, h = map(int, size.split("x"))
        assert wy <= y and y + h <= wy + wh and h <= wh - 16, (g, work)
        return h

    medium = "Ελέγξτε θερμοκρασία ψυγείου και τιμολόγιο. " * 6
    root = _build(ov, _ev("Παραλαβή γαλακτοκομικών", medium))
    h1 = inside(root)
    assert ov._desc.get("1.0", "end-1c") == medium.strip() and "…" not in ov._desc.get("1.0", "end")
    if wh >= 700:
        assert not ov.layout["scroll"] and not ov.layout["scrollable"], ov.layout
    ov._close()
    ov.pump()

    long_desc = "\n\n".join(f"{i}. Μετρήστε τη θερμοκρασία στο ψυγείο {i} και γράψτε την." for i in range(1, 40))
    root = _build(ov, _ev("Απογραφή ψυγείων " * 12, long_desc, key="L"), (2, 3))
    h2 = inside(root)
    root.update()
    assert h2 >= h1 and ov.layout["compact"] and ov.layout["scroll"]
    assert h2 <= max(ov.layout["max_h"], wh - 16)
    text = ov._desc.get("1.0", "end-1c")
    assert long_desc in text and text.startswith(" ".join(("Απογραφή ψυγείων " * 12).split()))
    assert ov.layout["scrollable"]  # η μπάρα κύλισης εμφανίστηκε
    ov._desc.yview_moveto(0.0)
    root.update()
    top = ov._desc.index("@0,0")
    root.event_generate("<Next>", when="now")
    root.update()
    assert float(ov._desc.index("@0,0")) > float(top)  # PgDn κυλά
    ov._desc.yview_moveto(1.0)
    root.update()
    assert ov._desc.yview()[1] == pytest.approx(1.0)
    ov._dismiss()
    ov.pump()
    assert eng.calls == [("dismiss", "L")] and ov.root is None


@pytest.mark.skipif(not _has_display(), reason="χωρίς tkinter/οθόνη")
def test_popup_desc_fixup_when_real_text_taller(monkeypatch):
    """Τα Windows αναδιπλώνουν λίγο διαφορετικά από τη μέτρηση στον καμβά: αν το
    πραγματικό κείμενο βγει ψηλότερο, το πλαίσιο μεγαλώνει (ή κυλά) — ποτέ κρυφό κείμενο."""
    import tkinter as tk

    class TallText(tk.Text):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.configure(spacing1=6)  # κάθε γραμμή ψηλότερη από ό,τι μέτρησε ο καμβάς

    monkeypatch.setattr(tk, "Text", TallText)
    eng = _Eng()
    ov = app.Overlay(eng)
    ov.work_area = (0, 0, 1366, 728)
    for desc in ("Ελέγξτε θερμοκρασία ψυγείου και τιμολόγιο. " * 6,
                 "\n\n".join(f"{i}. Μετρήστε το ψυγείο {i}." for i in range(1, 30))):
        root = _build(ov, _ev("Παραλαβή γαλακτοκομικών", desc))
        _settle(root)
        g = root.winfo_geometry()
        h, y = int(g.split("+")[0].split("x")[1]), int(g.split("+")[2])
        assert 0 <= y and y + h <= 728
        if not ov.layout["scroll"]:
            assert not ov.layout["scrollable"], ov.layout
        else:
            assert ov.layout["scrollable"], ov.layout
        ov._close()
        ov.pump()



def test_calendar_help_uses_current_google_path():
    """Οδηγίες για το σημερινό Google Calendar: γρανάζι → Ρυθμίσεις → όνομα ημερολογίου →
    Ενσωμάτωση ημερολογίου. Όχι «τρεις τελείες» / «Ρυθμίσεις και κοινή χρήση»."""
    h = app.CALENDAR_HELP
    for part in ("⚙", "«Ρυθμίσεις»", "όνομα του ημερολογίου", "«Ενσωμάτωση ημερολογίου»",
                 "«Μυστική διεύθυνση σε μορφή iCal»", ".ics"):
        assert part in h
    src = open(app.__file__, encoding="utf-8").read()
    assert "τρεις τελείες" not in src and "Ρυθμίσεις και κοινή χρήση" not in src
