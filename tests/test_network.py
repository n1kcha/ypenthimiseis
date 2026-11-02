# -*- coding: utf-8 -*-
"""Τεστ για τα λάθη σύνδεσης, το proxy και τον καθαρισμό URL (χωρίς πραγματικό δίκτυο).
Τρέξιμο: python -m pytest -q tests"""
import socket
import sys
from pathlib import Path

import pytest
import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402

TOKEN = "0123456789abcdef0123456789abcdef"
SECRET_PATH = f"/calendar/ical/kentriko%40group.calendar.google.com/private-{TOKEN}/basic.ics"
URL = "https://calendar.google.com" + SECRET_PATH


@pytest.fixture
def logfile(tmp_path, monkeypatch):
    p = tmp_path / "app.log"
    monkeypatch.setattr(app, "LOG_PATH", p)
    monkeypatch.setattr(app, "_direct_hosts", set())
    return p


def _wrap(reason, cls=requests.exceptions.ConnectionError):
    """Όπως το requests: ConnectionError(MaxRetryError(..., url=<μυστική διαδρομή>, reason))."""
    return cls(urllib3.exceptions.MaxRetryError(None, SECRET_PATH, reason=reason))


def dns_error():
    return _wrap(urllib3.exceptions.NameResolutionError(
        "calendar.google.com", None, socket.gaierror(11001, "getaddrinfo failed")))


def ssl_error():
    return _wrap(urllib3.exceptions.SSLError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local "
        "issuer certificate (_ssl.c:1000)"), requests.exceptions.SSLError)


def proxy_error():
    return _wrap(urllib3.exceptions.ProxyError(
        "Unable to connect to proxy",
        urllib3.exceptions.NewConnectionError(None, "Failed to establish a new connection: "
                                                    "[WinError 10061] refused")),
        requests.exceptions.ProxyError)


def refused_error():
    return _wrap(urllib3.exceptions.NewConnectionError(
        None, "Failed to establish a new connection: [WinError 10060] timed out"))


def firewall_error():
    return _wrap(urllib3.exceptions.NewConnectionError(
        None, "Failed to establish a new connection: [WinError 10013] An attempt was made to "
              "access a socket in a way forbidden by its access permissions"))


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


# ------------------------------------------------------------------ clean_ics_url

@pytest.mark.parametrize("raw", [
    URL,
    f"  {URL}\n",
    f"\ufeff{URL}",
    f'"{URL}"',
    f"'{URL}',",
    f"«{URL}»",
    f"“{URL}”",
    f"<{URL}>",
    f"{URL[:40]}\r\n{URL[40:]}",
    f"{URL[:40]}\\n{URL[40:]}",          # \n γραμμένο ως κείμενο σε παλιό config
    f"\u200b{URL}\u200b",
    f"\u00a0{URL}\u00a0",
    "webcal://calendar.google.com" + SECRET_PATH,
    "WEBCAL://calendar.google.com" + SECRET_PATH,
    "webcals://calendar.google.com" + SECRET_PATH,
    f' "webcal://calendar.google.com{SECRET_PATH}" ',
])
def test_clean_ics_url_variants(raw):
    assert app.clean_ics_url(raw) == URL


def test_clean_ics_url_empty():
    assert app.clean_ics_url(None) == "" and app.clean_ics_url("  \n ") == ""


def test_old_config_urls_are_cleaned_for_fetch_and_settings():
    """Παλιό config.json από χειροκίνητη εγκατάσταση: webcal://, κενά, BOM, εισαγωγικά,
    ics_urls ως κείμενο με πολλές γραμμές."""
    old = {"ics_url": f"\ufeff webcal://calendar.google.com{SECRET_PATH} \n",
           "ics_urls": f'"{URL}"\r\n  https://example.com/b.ics \r\n\r\n',
           "ics_names": {f" {URL} ": "Κεντρικό"}}
    assert app.calendar_urls(old) == [URL, "https://example.com/b.ics"]
    assert app.config_is_complete(old)
    cals = app.calendars_from_config(old)
    assert [c[0] for c in cals] == [URL, "https://example.com/b.ics"]
    assert cals[0][1] == "Κεντρικό" and cals[0][2] is True
    cfg, errors = app.build_config({"store_name": "Κ", "store_id": "k", "ics_url": old["ics_url"],
                                    "ics_urls": old["ics_urls"], "ics_names": old["ics_names"]})
    assert not errors
    assert cfg["ics_url"] == URL and cfg["ics_urls"] == ["https://example.com/b.ics"]
    assert cfg["ics_names"] == {URL: "Κεντρικό"}


# ------------------------------------------------------------------ check_ics messages

@pytest.mark.parametrize("make,expected,cls", [
    (ssl_error, "ημερομηνία και η ώρα", "SSLError"),
    (proxy_error, "proxy", "ProxyError"),
    (dns_error, "(DNS)", "NameResolutionError"),
    (refused_error, "Δεν υπάρχει σύνδεση με τον διακομιστή", "NewConnectionError"),
    (firewall_error, "τείχος προστασίας", "10013"),
])
def test_check_ics_distinguishes_errors(make, expected, cls, logfile, monkeypatch):
    monkeypatch.setattr(app, "proxy_for", lambda u: "")
    monkeypatch.setattr(app.requests, "get", _raise(make()))
    ok, msg = app.check_ics(URL)
    assert not ok and expected in msg and cls in msg
    head, detail = msg.split("\n(Λεπτομέρειες: ")
    assert detail.endswith(")") and len(detail) <= 121
    log = logfile.read_text(encoding="utf-8")
    assert "check: https://calendar.google.com/…/basic.ics" in log and cls in log
    assert "net: tls=" in log
    for text in (msg, log):
        assert TOKEN not in text and SECRET_PATH not in text and "kentriko%40" not in text


def test_check_ics_bad_ca_bundle_oserror(logfile, monkeypatch):
    monkeypatch.setattr(app.requests, "get", _raise(OSError(
        "Could not find a suitable TLS CA certificate bundle, invalid path: C:\\x\\ca.pem")))
    ok, msg = app.check_ics(URL)
    assert not ok and "πιστοποιητικό" in msg and "OSError" in msg


def test_check_ics_timeout(logfile, monkeypatch):
    monkeypatch.setattr(app.requests, "get", _raise(requests.exceptions.ReadTimeout("read timed out")))
    ok, msg = app.check_ics(URL)
    assert not ok and "εγκαίρως" in msg and "ReadTimeout" in msg


def test_scrub_removes_secrets():
    s = (f"HTTPSConnectionPool(host='calendar.google.com', port=443): Max retries exceeded with "
         f"url: {SECRET_PATH} (Caused by X) proxy http://user:pass@10.0.0.1:8080 {URL}")
    out = app.scrub(s, [URL])
    assert TOKEN not in out and "pass@" not in out and "kentriko" not in out
    assert "calendar.google.com" in out
    assert app.redact_url(URL) == "https://calendar.google.com/…/basic.ics"


# ------------------------------------------------------------------ fetch()

def test_fetch_error_is_logged_without_secret(logfile, monkeypatch):
    monkeypatch.setattr(app, "proxy_for", lambda u: "")
    monkeypatch.setattr(app.requests, "get", _raise(ssl_error()))
    eng = app.ReminderEngine(app.apply_defaults({"ics_url": URL, "store_id": "x"}))
    eng.fetch()
    assert "SSLError" in eng.last_error and "calendar.google.com/…/basic.ics" in eng.last_error
    assert TOKEN not in eng.last_error and SECRET_PATH not in eng.last_error


def test_fetch_uses_cleaned_url(logfile, monkeypatch):
    seen = []

    class R:
        content = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(app, "http_get", lambda u, timeout=25: seen.append(u) or R())
    eng = app.ReminderEngine(app.apply_defaults(
        {"ics_url": f' "webcal://calendar.google.com{SECRET_PATH}"\n', "store_id": "x"}))
    eng.fetch()
    assert seen == [URL] and eng.last_error == ""


# ------------------------------------------------------------------ proxy fallback

class _Resp:
    status_code = 200
    content = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"


def test_broken_proxy_retries_once_without_proxy(logfile, monkeypatch):
    calls = {"proxy": 0, "direct": 0}

    def via_proxy(*a, **k):
        calls["proxy"] += 1
        raise proxy_error()

    def direct(self, url, **k):
        assert self.trust_env is False  # χωρίς proxy του συστήματος
        calls["direct"] += 1
        return _Resp()

    monkeypatch.setattr(app.requests, "get", via_proxy)
    monkeypatch.setattr(app.requests.Session, "get", direct)
    monkeypatch.setattr(app, "proxy_for", lambda u: "http://user:secret@10.1.2.3:3128")
    ok, msg = app.check_ics(URL)
    assert ok, msg
    assert calls == {"proxy": 1, "direct": 1}
    # επόμενη φορά κατευθείαν χωρίς proxy (χωρίς 20 δευτ. αναμονή)
    assert app.check_ics(URL)[0] and calls == {"proxy": 1, "direct": 2}
    log = logfile.read_text(encoding="utf-8")
    assert "δοκιμή χωρίς proxy" in log and "secret" not in log and TOKEN not in log


def test_broken_proxy_and_direct_fail_reports_proxy_error(logfile, monkeypatch):
    monkeypatch.setattr(app.requests, "get", _raise(proxy_error()))
    monkeypatch.setattr(app.requests.Session, "get", _raise(dns_error()))
    monkeypatch.setattr(app, "proxy_for", lambda u: "http://10.1.2.3:3128")
    ok, msg = app.check_ics(URL)
    assert not ok and "proxy" in msg and "ProxyError" in msg


def test_no_proxy_no_retry(logfile, monkeypatch):
    monkeypatch.setattr(app.requests, "get", _raise(dns_error()))
    monkeypatch.setattr(app.requests.Session, "get", _raise(AssertionError("no retry expected")))
    monkeypatch.setattr(app, "proxy_for", lambda u: "")
    with pytest.raises(requests.exceptions.ConnectionError):
        app.http_get(URL)


def test_proxy_for_reads_environment(monkeypatch):
    for v in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    assert app.proxy_for("https://calendar.google.com/x.ics") == "http://127.0.0.1:9"
    assert "HTTPS_PROXY" in app.network_diagnostics()


# ------------------------------------------------------------------ TLS / build

def test_setup_tls_never_crashes_and_falls_back(logfile, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "truststore", None)  # import -> ImportError
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "missing-ca.pem"))
    assert app.setup_tls() == "certifi"
    import os

    assert "REQUESTS_CA_BUNDLE" not in os.environ
    log = logfile.read_text(encoding="utf-8")
    assert "certifi" in log and "REQUESTS_CA_BUNDLE" in log


def test_setup_tls_uses_truststore(logfile, monkeypatch):
    truststore = pytest.importorskip("truststore")
    try:
        assert app.setup_tls().startswith("truststore")
    finally:
        truststore.extract_from_ssl()
        monkeypatch.setattr(app, "TLS_BACKEND", "certifi")


def test_truststore_in_requirements_and_pyinstaller():
    root = Path(__file__).resolve().parents[1]
    assert "truststore" in (root / "requirements.txt").read_text(encoding="utf-8")
    build = (root / "installer" / "build.ps1").read_text(encoding="utf-8")
    assert "--collect-submodules truststore" in build and "--hidden-import truststore" in build


def test_invalid_url_is_not_reported_as_connection_problem(logfile):
    ok, msg = app.check_ics("https://")
    assert not ok and "δεν είναι έγκυρος" in msg
