import json
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402

GOOD = {
    "store_name": "Κατάστημα Δοκιμή",
    "store_id": "dokimi",
    "ics_url": "https://example.com/central.ics",
}


@pytest.mark.parametrize("raw,expected", [
    ({}, "beep"),                                          # νέα εγκατάσταση
    ({"sound": True, "sound_seconds": 10}, "beep"),        # παλιά προεπιλογή -> μπιπ
    ({"sound": True, "sound_seconds": "10"}, "beep"),
    ({"sound_seconds": 10}, "beep"),
    ({"sound": True}, "beep"),
    ({"sound": False, "sound_seconds": 10}, "none"),       # ο χρήστης είχε κλείσει τον ήχο
    ({"sound": False, "sound_seconds": 30}, "none"),
    ({"sound": True, "sound_seconds": 30}, "repeat"),      # ρητή αλλαγή δευτερολέπτων
    ({"sound": True, "sound_seconds": 5}, "repeat"),
    ({"sound_mode": "repeat", "sound_seconds": 10}, "repeat"),  # ρητή νέα επιλογή μένει
    ({"sound_mode": "none", "sound": True}, "none"),
    ({"sound_mode": "beep", "sound_seconds": 45}, "beep"),
    ({"sound_mode": "bogus", "sound_seconds": 10}, "beep"),
    ({"sound_seconds": "abc"}, "beep"),
])
def test_sound_mode_migration(raw, expected):
    assert app.sound_mode(raw) == expected
    cfg = app.apply_defaults(raw)
    assert cfg["sound_mode"] == expected
    assert cfg["sound"] is (expected != "none")


def test_migration_keeps_custom_seconds(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(app, "CONFIG_PATH", p)
    p.write_text(json.dumps({"ics_url": "https://x/y.ics", "sound": True, "sound_seconds": 25}))
    cfg = app.load_config()
    assert cfg["sound_mode"] == "repeat" and cfg["sound_seconds"] == 25


def test_build_config_sound_modes():
    cfg, err = app.build_config(dict(GOOD, sound_mode="none", sound_seconds="abc"))
    assert not err and cfg["sound_mode"] == "none" and cfg["sound"] is False
    assert cfg["sound_seconds"] == 10  # άκυρα δευτ. αγνοούνται όταν δεν χρειάζονται
    cfg, err = app.build_config(dict(GOOD, sound_mode="beep", sound_seconds="0"),
                                {"sound_seconds": 40})
    assert not err and cfg["sound_mode"] == "beep" and cfg["sound_seconds"] == 40
    cfg, err = app.build_config(dict(GOOD, sound_mode="repeat", sound_seconds="20"))
    assert not err and cfg["sound_mode"] == "repeat" and cfg["sound_seconds"] == 20
    _, err = app.build_config(dict(GOOD, sound_mode="repeat", sound_seconds="0"))
    assert err


def test_build_config_keeps_existing_mode():
    cfg, err = app.build_config(dict(GOOD), {"sound_mode": "repeat", "sound_seconds": 15})
    assert not err and cfg["sound_mode"] == "repeat"
    cfg, err = app.build_config(dict(GOOD), {"sound": True, "sound_seconds": 10})
    assert not err and cfg["sound_mode"] == "beep"


def test_beep_wav_is_short_single(tmp_path):
    p = app.ensure_beep_wav(tmp_path / "beep.wav")
    with wave.open(str(p)) as w:
        dur = w.getnframes() / w.getframerate()
    assert 0.2 <= dur <= 0.5
    c = app.ensure_chime_wav(tmp_path / "chime.wav")
    with wave.open(str(c)) as w:
        assert w.getnframes() / w.getframerate() > 5


def test_player_dispatch(monkeypatch):
    calls = []
    pl = app.SoundPlayer()
    monkeypatch.setattr(pl, "beep", lambda: calls.append("beep"))
    monkeypatch.setattr(pl, "start", lambda s: calls.append(("repeat", s)))
    pl.play("beep", 10)
    pl.play("none", 10)
    pl.play("repeat", 12)
    assert calls == ["beep", ("repeat", 12)]
