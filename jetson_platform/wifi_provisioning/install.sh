#!/bin/bash
# Install the Wini Wi-Fi provisioning portal onto the Jetson.
# Run ON the device from this directory:  sudo bash install.sh   [--with-failover]
#
# Installs:
#   - /usr/local/bin/wini_provision_portal.py   (the captive portal web app)
#   - /usr/local/bin/wini-wifi-connect.sh        (nmcli switch helper)
#   - /etc/systemd/system/wini-provision.service (runs the portal, root, :80)
#   - /etc/NetworkManager/dnsmasq-shared.d/wini-captive.conf (auto-popup)
#   - enables avahi-daemon (mDNS: reach the board at <host>.local)
# With --with-failover it also (re)installs the hotspot failover watchdog
# (already present on the current board — only needed on a fresh flash).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "[install] from $HERE"

install -m 0755 "$HERE/wini_provision_portal.py" /usr/local/bin/wini_provision_portal.py
install -m 0755 "$HERE/wini-wifi-connect.sh"     /usr/local/bin/wini-wifi-connect.sh

install -d /etc/NetworkManager/dnsmasq-shared.d
install -m 0644 "$HERE/dnsmasq-shared.d/wini-captive.conf" \
        /etc/NetworkManager/dnsmasq-shared.d/wini-captive.conf

install -m 0644 "$HERE/wini-provision.service" /etc/systemd/system/wini-provision.service
systemctl daemon-reload
systemctl enable --now wini-provision.service

# mDNS: reachable as <host>.local on any network the board joins
systemctl enable --now avahi-daemon

if [ "${1:-}" = "--with-failover" ]; then
    echo "[install] (re)installing hotspot failover watchdog"
    install -m 0755 "$HERE/wifi-failover.sh"      /usr/local/bin/wifi-failover.sh
    install -m 0644 "$HERE/wifi-watchdog.service" /etc/systemd/system/wifi-watchdog.service
    systemctl daemon-reload
    systemctl enable --now wifi-watchdog.service
fi

echo "[install] done — Wini is reachable at $(hostname).local"
systemctl is-active wini-provision.service avahi-daemon wifi-watchdog.service 2>/dev/null || true
