# -*- coding: utf-8 -*-
"""Εναλλακτικοί δρόμοι σύνδεσης (HTTP/3, TLS σαν του Chrome) όταν το TCP/TLS κόβεται.
Με mocks· τα πραγματικά τεστ δικτύου τρέχουν μόνο με YPEN_NET_TESTS=1 (στο CI των Windows)."""
import os
import sys
from pathlib import Path

import pytest
import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402

TOKEN = "fedcba9876543210fedcba9876543210"
SECRET_PATH = f"/calendar/ical/kentriko%40group.calendar.google.com/private-{TOKEN}/basic.ics"
URL = "https://calendar.google.com" + SECRET_PATH
ICS = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
PUBLIC_ICS = ("https://calendar.google.com/calendar/ical/"
              "el.greek%23holiday%40group.v.calendar.google.com/public/basic.ics")


@pytest.fixture
def env(tmp_path, monkeypatch):
    p = tmp_path / "app.log"
    monkeypatch.setattr(app, "LOG_PATH", p)
    monkeypatch.setattr(app, "_direct_hosts", set())
    monkeypatch.setattr(app, "_host_transport", {})
    monkeypatch.setattr(app, "FALLBACK_TRANSPORTS", ("h3", "tls-chrome"))
    monkeypatch.setattr(app, "proxy_for", lambda u: "")
    calls = []

    class Env:
        log = p

        def text(self):
            return p.read_text(encoding="utf-8") if p.exists() else ""

    e = Env()
    e.calls = calls
    return e


class Resp:
    def __init__(self, status=200, content=ICS):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def reset_error():
    """Όπως στο PC του καταστήματος: WinError 10054 αμέσως μετά το ClientHello."""
    return requests.exceptions.ConnectionError(urllib3.exceptions.ProtocolError(
        "Connection aborted.", ConnectionResetError(10054, "An existing connection was "
                                                          "forcibly closed by the remote host")))


def ssl_eof_error():
    return requests.exceptions.SSLError(urllib3.exceptions.MaxRetryError(
        None, SECRET_PATH, reason=urllib3.exceptions.SSLError(
            "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")))


def dns_error():
    import socket

    return requests.exceptions.ConnectionError(urllib3.exceptions.MaxRetryError(
        None, SECRET_PATH, reason=urllib3.exceptions.NameResolutionError(
            "calendar.google.com", None, socket.gaierror(11001, "getaddrinfo failed"))))


def _tcp(env, exc=None, resp=None):
    def f(url, timeout=25):
        env.calls.append(("tcp", url))
        if exc is not None:
            raise exc
        return resp or Resp()
    return f


def _alt(env, results):
    """results: {transport: Resp ή Exception}"""
    def f(url, transport, timeout=15):
        env.calls.append((transport, url))
        assert timeout <= 15
        r = results.get(transport, RuntimeError("not mocked"))
        if isinstance(r, BaseException):
            raise r
        return r
    return f


@pytest.mark.parametrize("make", [reset_error, ssl_eof_error])
def test_reset_falls_back_to_h3_and_remembers_host(env, monkeypatch, make):
    monkeypatch.setattr(app, "_tcp_get", _tcp(env, make()))
    monkeypatch.setattr(app, "_alt_get", _alt(env, {"h3": Resp()}))
    ok, msg = app.check_ics(URL)
    assert ok, msg
    assert [c[0] for c in env.calls] == ["tcp", "h3"]
    assert app._host_transport == {"calendar.google.com": "h3"}
    # επόμενη φορά (και από το fetch) κατευθείαν HTTP/3
    env.calls.clear()
    eng = app.ReminderEngine(app.apply_defaults({"ics_url": URL, "store_id": "x"}))
    eng.fetch()
    assert eng.last_error == "" and [c[0] for c in env.calls] == ["h3"]
    log = env.text()
    assert "net: h3 fallback ok for calendar.google.com" in log
    assert TOKEN not in log and SECRET_PATH not in log


def test_h3_fails_later_goes_back_to_tcp(env, monkeypatch):
    app._host_transport["calendar.google.com"] = "h3"
    monkeypatch.setattr(app, "_tcp_get", _tcp(env))
    monkeypatch.setattr(app, "_alt_get", _alt(env, {"h3": RuntimeError("udp blocked")}))
    r = app.http_get(URL)
    assert r.status_code == 200
    assert [c[0] for c in env.calls] == ["h3", "tcp"]
    assert app._host_transport == {}
    assert "back to tcp" in env.text()


def test_h3_blocked_too_uses_chrome_tls(env, monkeypatch):
    monkeypatch.setattr(app, "_tcp_get", _tcp(env, reset_error()))
    monkeypatch.setattr(app, "_alt_get", _alt(env, {"h3": RuntimeError("ERR_HANDSHAKE_TIMEOUT"),
                                                    "tls-chrome": Resp()}))
    assert app.http_get(URL).status_code == 200
    assert [c[0] for c in env.calls] == ["tcp", "h3", "tls-chrome"]
    assert app._host_transport == {"calendar.google.com": "tls-chrome"}
    log = env.text()
    assert "h3 fallback failed" in log and "tls-chrome fallback ok" in log


def test_all_fail_raises_original_and_message(env, monkeypatch):
    monkeypatch.setattr(app, "_tcp_get", _tcp(env, reset_error()))
    monkeypatch.setattr(app, "_alt_get", _alt(env, {"h3": RuntimeError("x"),
                                                    "tls-chrome": RuntimeError("y")}))
    ok, msg = app.check_ics(URL)
    assert not ok and "(reset)" in msg and "10054" in msg
    assert app._host_transport == {}


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_http_errors_do_not_fall_back(env, monkeypatch, status):
    monkeypatch.setattr(app, "_tcp_get", _tcp(env, resp=Resp(status, b"")))
    monkeypatch.setattr(app, "_alt_get", _alt(env, {}))
    ok, msg = app.check_ics(URL)
    assert not ok and f"HTTP {status}" in msg
    assert [c[0] for c in env.calls] == ["tcp"]


def test_dns_error_does_not_fall_back(env, monkeypatch):
    monkeypatch.setattr(app, "_tcp_get", _tcp(env, dns_error()))
    monkeypatch.setattr(app, "_alt_get", _alt(env, {"h3": Resp()}))
    ok, msg = app.check_ics(URL)
    assert not ok and "(DNS)" in msg and [c[0] for c in env.calls] == ["tcp"]


def test_missing_curl_cffi_never_crashes(env, monkeypatch):
    monkeypatch.setattr(app, "_tcp_get", _tcp(env, reset_error()))
    monkeypatch.setitem(sys.modules, "curl_cffi", None)  # import -> ImportError
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", None)
    monkeypatch.setattr(app, "_curl_missing_logged", False)
    ok, msg = app.check_ics(URL)
    assert not ok and "(reset)" in msg
    assert "curl_cffi unavailable" in env.text()


def test_alt_get_options(monkeypatch):
    """HTTP/3 μόνο (v3only), redirects, έλεγχος πιστοποιητικού, timeout, χωρίς proxy."""
    pytest.importorskip("curl_cffi")
    from curl_cffi import requests as cr

    seen = {}

    class S:
        def __init__(self, **kw):
            seen["session"] = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            seen["get"] = kw
            return Resp()

    monkeypatch.setattr(cr, "Session", S)
    app._alt_get(URL, "h3", 15)
    assert seen["session"] == {"trust_env": False}
    g = seen["get"]
    assert g["http_version"] == "v3only" and g["verify"] is True
    assert g["allow_redirects"] is True and g["timeout"] == 15
    app._alt_get(URL, "tls-chrome", 10)
    assert seen["get"]["impersonate"] == "chrome" and "http_version" not in seen["get"]
    with pytest.raises(ValueError):
        app._alt_get(URL, "nope")


def test_net_selftest_logs_without_secret(env, monkeypatch):
    monkeypatch.setattr(app, "_alt_get", lambda u, t, timeout=15: Resp())
    assert app.net_selftest(URL, "h3") is True
    monkeypatch.setattr(app, "_alt_get", lambda u, t, timeout=15: (_ for _ in ()).throw(
        RuntimeError("blocked")))
    assert app.net_selftest(URL, "h3") is False
    log = env.text()
    assert "net-selftest: h3 https://calendar.google.com/…/basic.ics -> HTTP 200" in log
    assert TOKEN not in log


def test_curl_cffi_bundled_in_build():
    root = Path(__file__).resolve().parents[1]
    assert "curl_cffi" in (root / "requirements.txt").read_text(encoding="utf-8")
    build = (root / "installer" / "build.ps1").read_text(encoding="utf-8")
    assert "--additional-hooks-dir installer\\hooks" in build
    hook = (root / "installer" / "hooks" / "hook-curl_cffi.py").read_text(encoding="utf-8")
    assert "collect_delvewheel_libs_directory" in hook


# ------------------------------------------------------------------ πραγματικό δίκτυο

net = pytest.mark.skipif(os.environ.get("YPEN_NET_TESTS") != "1",
                         reason="πραγματικό δίκτυο μόνο με YPEN_NET_TESTS=1")


@net
@pytest.mark.parametrize("transport", ["h3", "tls-chrome"])
@pytest.mark.parametrize("url", ["https://www.google.com/", PUBLIC_ICS])
def test_real_alt_transport(transport, url):
    r = app._alt_get(url, transport, 20)
    assert r.status_code == 200 and r.content
    if url == PUBLIC_ICS:
        assert r.content.startswith(b"BEGIN:VCALENDAR")
    if transport == "h3":
        assert int(r.http_version) == 30  # CURL_HTTP_VERSION_3
