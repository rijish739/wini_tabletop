# Wini Wi-Fi provisioning (hotspot → real network, headless)

Lets you move the Jetson to a **new Wi-Fi network with no screen/keyboard and
without knowing its IP** — the exact problem when the board falls back to its
`Wini-Robot` hotspot (no internet, unknown address).

## The problem

The board has a failover watchdog (`wifi-watchdog.service` → `wifi-failover.sh`):
when no known Wi-Fi is in range it raises a WPA2 hotspot **`Wini-Robot`**
(`WiniHotspot` NM profile, `ipv4.method=shared`). In that state it has **no
internet** and you don't know its LAN IP — so you can't SSH in to fix its Wi-Fi.
Chicken-and-egg.

## The solution (two layers)

1. **A captive provisioning portal** on the hotspot. Join `Wini-Robot`, open the
   page, pick your Wi-Fi + password → the board switches itself onto that network.
2. **mDNS (`avahi`)** so afterwards you reach the board by name, no IP needed:
   `ssh roavai@<hostname>.local` (today `ubuntu.local`). Works on the hotspot too
   (`ubuntu.local` → `10.42.0.1`).

## End-user flow

1. Power on somewhere new → after ~30 s with no known Wi-Fi the **`Wini-Robot`**
   hotspot appears. Join it (WPA2 password = the hotspot key).
2. A **"Sign in to network"** page pops up automatically (captive portal). If not,
   open a browser to **`http://10.42.0.1`** (or `http://ubuntu.local`).
3. Type your Wi-Fi **name + password** → **Connect**. The hotspot switches off.
4. Reconnect your phone/laptop to that same Wi-Fi and reach Wini at
   **`ssh roavai@ubuntu.local`** — no IP hunting.
   - Wrong password / out of range → the `Wini-Robot` hotspot returns in ~30 s;
     rejoin and retry.

## How it works

```
phone ──join── Wini-Robot (10.42.0.1) ──http──► wini-provision.service (portal, :80, root)
                                                    │ POST /connect  ssid+password
                                                    ▼
                                         wini-wifi-connect.sh
                             touch /dev/shm/wifi_lock   (pause the failover watchdog)
                             nmcli con down WiniHotspot  (free the single radio)
                             nmcli dev wifi connect <ssid> password <psk>
                             write /dev/shm/wini_wifi_status = ok|failed
                             rm /dev/shm/wifi_lock        (watchdog resumes control)
```

The watchdog already skips its check while `/dev/shm/wifi_lock` exists, so the
helper flips the radio without a fight. On success the watchdog sees a real
network and leaves the hotspot down; on failure it re-raises the hotspot.

## Files

| Repo file | Installs to | Role |
|---|---|---|
| `wini_provision_portal.py` | `/usr/local/bin/` | stdlib HTTP captive portal (`:80`, root) |
| `wini-wifi-connect.sh` | `/usr/local/bin/` | nmcli switch helper (lock-aware) |
| `wini-provision.service` | `/etc/systemd/system/` | runs the portal at boot |
| `dnsmasq-shared.d/wini-captive.conf` | `/etc/NetworkManager/dnsmasq-shared.d/` | DNS catch-all → auto-popup |
| `wifi-failover.sh`, `wifi-watchdog.service` | (already on board) | snapshots for provenance |
| `install.sh` | — | copies the above, enables `wini-provision` + `avahi-daemon` |

## Install (on the board)

```bash
scp -r jetson_platform/wifi_provisioning roavai@<board>:/home/roavai/
ssh roavai@<board> 'cd ~/wifi_provisioning && sudo bash install.sh'   # --with-failover on a fresh flash
```

Verify:

```bash
systemctl is-active wini-provision avahi-daemon wifi-watchdog     # all "active"
curl -s http://<board-ip>/status                                  # JSON: hotspot/state/ip/host
ping <hostname>.local                                             # mDNS from another machine
```

## Notes / limits

- **Single radio** can't scan well while beaconing as an AP, so the network list
  is often empty in hotspot mode — the SSID box is free-text on purpose.
- The portal binds `0.0.0.0:80` but **`/connect` only acts in hotspot mode**; on
  the real LAN it's a read-only status page (mild: anyone on your LAN can view it).
- `wini-wifi-connect.sh "<SSID>"` with **no password** reuses a saved profile —
  handy for a CLI reconnect over SSH.
- Optional nicety: rename the host for a friendlier name —
  `sudo hostnamectl set-hostname wini` and update `/etc/hosts` (`127.0.1.1 wini`)
  → then `ssh roavai@wini.local`. Left as `ubuntu` by default to match the runbook.
- Fallbacks if mDNS is blocked: check your router's DHCP client list, or (when
  up) Tailscale.
