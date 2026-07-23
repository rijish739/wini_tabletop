#!/bin/bash
# test_switch.sh — self-healing live test of the hotspot<->wifi switch.
# Run as ROOT, DETACHED (raising the AP drops this machine's Wi-Fi):
#
#   scp jetson_platform/wifi_provisioning/test_switch.sh roavai@<board>:/home/roavai/
#   ssh roavai@<board> "echo '<sudo-pw>' | sudo -S -p '' bash -c \
#     'nohup setsid bash /home/roavai/test_switch.sh > ~/wini_test_logs/wifi_test.log 2>&1 </dev/null & disown; echo LAUNCHED'"
#   # wait ~40 s for the board to self-heal onto home Wi-Fi, then:
#   ssh roavai@<board> 'cat ~/wini_test_logs/wifi_test.log'
#
# It raises the Wini-Robot hotspot, checks the captive DNS + portal at 10.42.0.1,
# then rejoins HOME_SSID via the REAL wini-wifi-connect.sh helper. A 90 s safety
# net restores home Wi-Fi no matter what, so a dropped SSH can't lock you out.
# Set HOME_SSID to a network with a SAVED NM profile (no password needed).
set +e
IFACE="${WINI_WIFI_IFACE:-wlP1p1s0}"
HOME_SSID="${HOME_SSID:-ROAVAI Pvt Ltd}"
LOCK="/dev/shm/wifi_lock"

step(){ echo "[$(date '+%T')] $*"; }

sleep 3   # grace so the launching SSH call returns before we touch the radio

( sleep 90
  echo "[$(date '+%T')] SAFETY-NET firing: restoring $HOME_SSID"
  nmcli con down WiniHotspot >/dev/null 2>&1
  nmcli con up "$HOME_SSID"  >/dev/null 2>&1
  rm -f "$LOCK"
) &
SAFETY=$!

step "=== TEST START (pid $$) ==="
touch "$LOCK"; step "held watchdog lock ($LOCK)"

step "raise hotspot: nmcli con up WiniHotspot"
nmcli con up WiniHotspot 2>&1 | sed 's/^/  /'
sleep 9

step "iface addr (expect 10.42.0.1):"
ip -4 addr show "$IFACE" | grep inet | sed 's/^/  /'
step "dev status:"
nmcli -t -f DEVICE,STATE,CONNECTION dev status | grep "$IFACE" | sed 's/^/  /'
step "portal @ hotspot gateway (curl http://10.42.0.1/status):"
curl -s --max-time 6 http://10.42.0.1/status | sed 's/^/  /'; echo

step "=== restore home Wi-Fi via REAL helper: wini-wifi-connect.sh '$HOME_SSID' ==="
bash /usr/local/bin/wini-wifi-connect.sh "$HOME_SSID" 2>&1 | sed 's/^/  /'

sleep 4
step "back-online check:"
ip -4 addr show "$IFACE" | grep inet | sed 's/^/  /'
nmcli -t -f DEVICE,STATE,CONNECTION dev status | grep "$IFACE" | sed 's/^/  /'
step "helper status file:"; cat /dev/shm/wini_wifi_status 2>/dev/null | sed 's/^/  /'; echo

rm -f "$LOCK"
kill "$SAFETY" 2>/dev/null
step "=== TEST COMPLETE ==="
