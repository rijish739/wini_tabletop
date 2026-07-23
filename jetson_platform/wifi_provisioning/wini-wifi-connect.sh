#!/bin/bash
# wini-wifi-connect.sh — join Wini to an external Wi-Fi, coordinating with the
# hotspot failover watchdog (/usr/local/bin/wifi-failover.sh).
#
#   Usage:  wini-wifi-connect.sh "<SSID>" ["<PASSWORD>"]
#           (empty / omitted password = open network, or reuse a saved profile)
#
# The watchdog re-raises the "Wini-Robot" hotspot whenever no real Wi-Fi is
# active. A single-radio card cannot be an AP and a station at once, so to switch
# networks we must (1) hold the watchdog off with its own override lock
# (/dev/shm/wifi_lock) while we drop the AP and associate, then (2) release the
# lock so it resumes: on success it keeps the hotspot down (real Wi-Fi is up); on
# failure it brings the hotspot back so the user can retry from the portal.
#
# Status for the portal is written to /dev/shm/wini_wifi_status as
# "<state>|<ssid>|<ip>"  where state is connecting|ok|failed.

set -u

SSID="${1:-}"
PSK="${2:-}"
IFACE="${WINI_WIFI_IFACE:-wlP1p1s0}"
HOTSPOT="WiniHotspot"
LOCK="/dev/shm/wifi_lock"
STATUS="/dev/shm/wini_wifi_status"

log() { echo "$(date '+%F %T') wini-wifi-connect: $*"; }

if [ -z "$SSID" ]; then
    echo "usage: $0 <SSID> [password]" >&2
    exit 2
fi

# 1) record intent and hold the watchdog off before we touch the radio
printf 'connecting|%s|\n' "$SSID" > "$STATUS"
touch "$LOCK"
log "locked watchdog; target SSID='$SSID' iface=$IFACE"

# let the portal's HTTP response flush to the phone before the AP disappears
sleep 2

# 2) leave AP mode so the single radio is free to associate as a station
nmcli con down "$HOTSPOT" >/dev/null 2>&1
sleep 2
nmcli dev wifi rescan ifname "$IFACE" >/dev/null 2>&1
sleep 3

# 2b) if a saved profile with this exact name already exists, refresh its
# password so a stale/incorrect saved key can't shadow the one just entered
if [ -n "$PSK" ] && nmcli -t -f NAME con show | grep -Fxq "$SSID"; then
    nmcli con modify "$SSID" 802-11-wireless-security.key-mgmt wpa-psk \
          802-11-wireless-security.psk "$PSK" >/dev/null 2>&1 && \
        log "refreshed saved password for existing profile '$SSID'"
fi

# 3) attempt the join (nmcli creates/updates a profile named after the SSID;
#    with no password it reuses a saved profile's credentials)
if [ -n "$PSK" ]; then
    nmcli -w 45 dev wifi connect "$SSID" password "$PSK" ifname "$IFACE"
else
    nmcli -w 45 dev wifi connect "$SSID" ifname "$IFACE"
fi
RC=$?

# 4) report + release the lock so the watchdog resumes normal control
if [ "$RC" -eq 0 ]; then
    sleep 3
    IP=$(nmcli -t -f IP4.ADDRESS dev show "$IFACE" 2>/dev/null | head -n1 | cut -d: -f2 | cut -d/ -f1)
    printf 'ok|%s|%s\n' "$SSID" "$IP" > "$STATUS"
    log "connected to '$SSID', ip=${IP:-unknown}"
    rm -f "$LOCK"
    exit 0
else
    printf 'failed|%s|\n' "$SSID" > "$STATUS"
    log "FAILED to join '$SSID' (rc=$RC); releasing lock — watchdog will restore the hotspot"
    rm -f "$LOCK"
    exit 1
fi
