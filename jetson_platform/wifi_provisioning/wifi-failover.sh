#!/bin/bash
# SNAPSHOT (2026-07-09) of the on-device /usr/local/bin/wifi-failover.sh.
# Unchanged, pre-existing hotspot failover watchdog. Raises the "Wini-Robot"
# hotspot whenever no real Wi-Fi is active, and drops it once a real network
# reconnects. It already honours an override lock at /dev/shm/wifi_lock, which
# wini-wifi-connect.sh uses to switch networks without the watchdog fighting the
# radio. Kept here for provenance / re-provisioning a fresh board.
nmcli radio wifi on
sleep 30

LOCK_FILE="/dev/shm/wifi_lock"

while true; do
    # 1. Check for Override Lock
    if [ -f "$LOCK_FILE" ]; then
        echo "WATCHDOG: Manual override detected at $LOCK_FILE. Skipping check..."
        sleep 5
        continue
    fi

    # 2. Identify current active Wi-Fi (excluding our hotspot)
    # This specifically looks for activated wifi connections that aren't 'WiniHotspot'
    REAL_WIFI=$(nmcli -t -f NAME,TYPE,STATE connection show --active | grep "802-11-wireless:activated" | grep -v "WiniHotspot" | cut -d: -f1)

    if [ -z "$REAL_WIFI" ]; then
        # 3. No Real Wi-Fi - Should we start hotspot?
        if ! nmcli con show --active | grep -q "WiniHotspot"; then
            echo "WATCHDOG: No real Wi-Fi found. Attempting to start WiniHotspot..."
            nmcli con up WiniHotspot > /dev/null 2>&1
        fi
    else
        # 4. Real Wi-Fi found - Kill hotspot if it's up
        if nmcli con show --active | grep -q "WiniHotspot"; then
             echo "WATCHDOG: Real network '$REAL_WIFI' found. Killing Hotspot."
             nmcli con down WiniHotspot > /dev/null 2>&1
        fi
    fi
    sleep 5 # Faster check during testing
done
