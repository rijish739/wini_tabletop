#!/usr/bin/env python3
"""Wini Wi-Fi provisioning portal.

When the Jetson has no known Wi-Fi, the failover watchdog (wifi-failover.sh /
wifi-watchdog.service) raises the **Wini-Robot** hotspot. This portal is the page
a phone/laptop opens after joining that hotspot, to hand Wini the credentials of
a real network. On submit it shells out to /usr/local/bin/wini-wifi-connect.sh,
which coordinates with the watchdog (via its /dev/shm/wifi_lock override),
flips the single radio out of AP mode, and joins the chosen network. The hotspot
then disappears and Wini is reachable over the new network at  ssh roavai@<host>.local
(mDNS/avahi) — no need to know the DHCP-assigned IP.

Reach it at   http://10.42.0.1/   (the hotspot gateway)   or   http://<host>.local/
Binds 0.0.0.0:80 as root (needs root for nmcli). The /connect action is only
honoured while the hotspot is actually active, so on the real LAN the page is a
harmless read-only status view.

Pure stdlib — no Flask. Runs on the device's system python3.
"""
from __future__ import annotations

import html
import json
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

IFACE = "wlP1p1s0"          # Jetson Orin Nano onboard Wi-Fi
HOTSPOT = "WiniHotspot"     # NM connection name (SSID = "Wini-Robot")
HOTSPOT_SSID = "Wini-Robot"
CONNECT_SH = "/usr/local/bin/wini-wifi-connect.sh"
STATUS_FILE = "/dev/shm/wini_wifi_status"
PORT = 80

# captive-portal probe URLs — answering with a redirect nudges phones/laptops to
# auto-open the sign-in page (paired with the dnsmasq catch-all, see README).
CAPTIVE_PROBES = (
    "/generate_204", "/gen_204", "/hotspot-detect.html", "/library/test/success.html",
    "/ncsi.txt", "/connecttest.txt", "/redirect", "/canonical.html", "/success.txt",
)

_scan_lock = threading.Lock()


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:  # noqa: BLE001
        return ""


def _unescape(v: str) -> str:
    """nmcli -t/-g escapes ':' and '\\' with a backslash."""
    return v.replace("\\:", ":").replace("\\\\", "\\")


def scan_networks():
    """Best-effort list of (ssid, signal). Often empty while the radio is in AP
    mode (a single-radio card can't beacon and scan at once) — that is why the
    page always also offers a free-text SSID box."""
    with _scan_lock:
        out = _run(["nmcli", "-g", "SSID,SIGNAL", "dev", "wifi", "list"], timeout=12)
    nets: dict[str, int] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        ssid_raw, sig = (line.rsplit(":", 1) + ["0"])[:2] if ":" in line else (line, "0")
        ssid = _unescape(ssid_raw)
        if not ssid or ssid == HOTSPOT_SSID:
            continue
        try:
            sigv = int(sig)
        except ValueError:
            sigv = 0
        nets[ssid] = max(sigv, nets.get(ssid, 0))
    return sorted(nets.items(), key=lambda kv: -kv[1])


def hotspot_active() -> bool:
    out = _run(["nmcli", "-t", "-f", "NAME", "con", "show", "--active"])
    return any(l.strip() == HOTSPOT for l in out.splitlines())


def iface_ip() -> str:
    out = _run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", IFACE])
    for l in out.splitlines():
        if l.startswith("IP4.ADDRESS"):
            return l.split(":", 1)[1].split("/")[0]
    return ""


def last_status():
    """(state, ssid, ip) from the connect helper's status file."""
    try:
        with open(STATUS_FILE) as f:
            raw = f.read().strip()
    except OSError:
        return "", "", ""
    parts = (raw.split("|") + ["", "", ""])[:3]
    return parts[0], parts[1], parts[2]


CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif;
       background:#0e1020; color:#e8e8f0; padding:20px; }
.wrap { max-width:460px; margin:0 auto; }
h1 { font-size:1.5rem; margin:0 0 4px; }
.sub { color:#9aa; font-size:.9rem; margin:0 0 20px; }
.card { background:#191c30; border:1px solid #2a2e48; border-radius:14px;
        padding:18px; margin-bottom:16px; }
label { display:block; font-size:.85rem; color:#b9bce0; margin:12px 0 6px; }
input, select { width:100%; padding:12px; font-size:1rem; border-radius:10px;
        border:1px solid #3a3e60; background:#0e1020; color:#fff; }
button { width:100%; margin-top:18px; padding:14px; font-size:1.05rem; font-weight:600;
        border:0; border-radius:10px; background:#5b6cff; color:#fff; }
button:active { background:#4657e8; }
.banner { padding:12px 14px; border-radius:10px; font-size:.92rem; margin-bottom:16px; }
.ok { background:#12331e; border:1px solid #1e7a3e; }
.warn { background:#3a2a12; border:1px solid #7a5a1e; }
.err { background:#3a1420; border:1px solid #a02040; }
.mono { font-family:ui-monospace,Menlo,Consolas,monospace; }
.small { font-size:.8rem; color:#9aa; }
"""


def page(body: str, refresh: int = 0) -> bytes:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"{meta}<title>Wini Wi-Fi Setup</title><style>{CSS}</style></head>"
        f"<body><div class='wrap'>{body}</div></body></html>"
    )
    return doc.encode("utf-8")


def main_page() -> bytes:
    host = socket.gethostname()
    ap = hotspot_active()
    state, ssid, ip = last_status()

    banner = ""
    if state == "failed":
        banner = (f"<div class='banner err'>Last attempt to join "
                  f"<b>{html.escape(ssid)}</b> failed. Check the password and try again.</div>")
    elif state == "connecting":
        banner = (f"<div class='banner warn'>Connecting to <b>{html.escape(ssid)}</b>…</div>")
    elif state == "ok" and not ap:
        banner = (f"<div class='banner ok'>Connected to <b>{html.escape(ssid)}</b>"
                  f"{' (' + html.escape(ip) + ')' if ip else ''}.</div>")

    if ap:
        mode = ("<div class='banner warn'>Wini is in <b>hotspot mode</b> "
                "(no home Wi-Fi found). Pick your network below to put Wini online.</div>")
    else:
        mode = (f"<div class='banner ok'>Wini is online as "
                f"<b class='mono'>{html.escape(host)}.local</b>"
                f"{' (' + html.escape(ip) + ')' if ip else ''}. "
                "Provisioning only runs in hotspot mode.</div>")

    nets = scan_networks()
    options = "".join(
        f"<option value='{html.escape(s)}'>{html.escape(s)} · {sig}%</option>"
        for s, sig in nets)
    datalist = "".join(f"<option value='{html.escape(s)}'>" for s, _ in nets)
    scan_note = ("" if nets else
                 "<p class='small'>No networks scanned (normal in hotspot mode) — "
                 "just type your Wi-Fi name.</p>")

    disabled = "" if ap else "disabled"
    form = f"""
      <form method='POST' action='/connect'>
        <label for='ssid'>Wi-Fi network</label>
        <input list='nets' id='ssid' name='ssid' placeholder='Your Wi-Fi name (SSID)'
               autocomplete='off' autocapitalize='none' {disabled} required>
        <datalist id='nets'>{datalist}</datalist>
        {scan_note}
        <label for='password'>Password</label>
        <input type='password' id='password' name='password'
               placeholder='Wi-Fi password' autocomplete='off' {disabled}>
        <button type='submit' {disabled}>Connect Wini to this network</button>
      </form>"""
    if options and ap:
        form = (f"<p class='small'>Scanned networks (strongest first): "
                f"{html.escape(', '.join(s for s, _ in nets[:6]))}</p>" + form)

    body = (
        "<h1>Wini Wi-Fi Setup</h1>"
        "<p class='sub'>Connect your robot to a Wi-Fi network.</p>"
        f"{banner}{mode}"
        f"<div class='card'>{form}</div>"
        "<p class='small'>After Wini joins your network its hotspot turns off. "
        f"Reconnect your phone/laptop to that same Wi-Fi and reach Wini at "
        f"<span class='mono'>{html.escape(host)}.local</span>.</p>"
    )
    return page(body, refresh=25 if ap else 0)


def connecting_page(ssid: str) -> bytes:
    host = socket.gethostname()
    body = (
        "<h1>Connecting…</h1>"
        f"<div class='banner warn'>Wini is trying to join <b>{html.escape(ssid)}</b>. "
        "The <b>Wini-Robot</b> hotspot will switch off now, so this page can't update.</div>"
        "<div class='card'>"
        "<p><b>If it works:</b> reconnect your phone/laptop to "
        f"<b>{html.escape(ssid)}</b>, then reach Wini at "
        f"<span class='mono'>{html.escape(host)}.local</span> "
        f"(e.g. <span class='mono'>ssh roavai@{html.escape(host)}.local</span>).</p>"
        "<p><b>If it fails</b> (wrong password, network out of range): the "
        "<b>Wini-Robot</b> hotspot comes back in about 30 seconds — rejoin it and "
        "open this page again to retry.</p>"
        "</div>"
    )
    return page(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "WiniProvision/1.0"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, body: bytes, code=200, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:  # noqa: BLE001
            pass

    def _redirect_home(self):
        self._send(b"", code=302, extra={"Location": "http://10.42.0.1/"})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in CAPTIVE_PROBES:
            return self._redirect_home()
        if path == "/status":
            state, ssid, ip = last_status()
            body = json.dumps({
                "hotspot": hotspot_active(), "state": state, "ssid": ssid,
                "ip": ip or iface_ip(), "host": socket.gethostname(),
            }).encode()
            return self._send(body, ctype="application/json")
        if path in ("/", "/index.html"):
            return self._send(main_page())
        # anything else on the hotspot -> bounce to the portal
        return self._redirect_home()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/connect":
            return self._send(b"not found", code=404, ctype="text/plain")
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        form = parse_qs(raw)
        ssid = (form.get("ssid", [""])[0]).strip()
        password = form.get("password", [""])[0]

        if not hotspot_active():
            body = page("<h1>Already online</h1><div class='banner ok'>Wini is already "
                        "on a network. Wi-Fi provisioning only runs in hotspot mode.</div>")
            return self._send(body, code=403)
        if not ssid:
            return self._send(main_page(), code=400)

        # fire-and-forget: the helper drops the AP (killing this connection), so
        # respond FIRST, then let it switch the radio.
        subprocess.Popen(
            [CONNECT_SH, ssid, password],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return self._send(connecting_page(ssid))


def main():
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[wini-provision] portal on http://0.0.0.0:{PORT} "
          f"(host {socket.gethostname()}.local)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
