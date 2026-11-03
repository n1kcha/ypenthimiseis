"""Η έκδοση: «dev» από τον κώδικα, από το build στο exe, και στο tooltip.

Το τεστ του παραθύρου ρυθμίσεων είναι στο test_config.py (μαζί με τα άλλα του παραθύρου)."""
import sys
import types
from pathlib import Path

import pytest

import app

ROOT = Path(__file__).resolve().parents[1]


def test_version_dev_without_generated_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "_version", None)  # import -> ImportError
    assert app.app_version() == "dev"


@pytest.mark.parametrize("raw,expected", [("1.0.5", "1.0.5"), (" 1.0.5\n", "1.0.5"), ("", "dev")])
def test_version_from_generated_module(monkeypatch, raw, expected):
    monkeypatch.setitem(sys.modules, "_version", types.SimpleNamespace(VERSION=raw))
    assert app.app_version() == expected


def test_source_checkout_has_no_version_module():
    # Το _version.py παράγεται μόνο στο build και δεν μπαίνει στο git.
    assert "_version.py" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


def test_build_writes_version_into_exe():
    build = (ROOT / "installer" / "build.ps1").read_text(encoding="utf-8")
    assert 'Set-Content -Path _version.py -Value "VERSION = `"$Version`""' in build
    assert "--hidden-import _version" in build
    assert build.index("_version.py") < build.index("PyInstaller --noconfirm")


def test_tray_tooltip(monkeypatch):
    monkeypatch.setattr(app, "APP_VERSION", "1.0.5")
    t = app.tray_tooltip()
    assert t.startswith(app.APP_NAME) and t.endswith("έκδοση 1.0.5") and len(t) <= 127
