#!/usr/bin/env python3
"""Check GPIO22 touch sensor on Raspberry Pi 5."""
import sys
import time

# Try lgpio first (Pi 5 native)
try:
    import lgpio
    h = lgpio.gpiochip_open(4)  # Pi 5 uses gpiochip4
    lgpio.gpio_claim_input(h, 22)
    val = lgpio.gpio_read(h, 22)
    print(f"lgpio: GPIO22 = {val}")
    print("Monitoring for 5 seconds (touch the sensor)...")
    for i in range(50):
        v = lgpio.gpio_read(h, 22)
        if v != val:
            print(f"  CHANGE at {i*0.1:.1f}s: GPIO22 = {v}")
            val = v
        time.sleep(0.1)
    lgpio.gpiochip_close(h)
    print("lgpio works!")
    sys.exit(0)
except ImportError:
    print("lgpio not available")
except Exception as e:
    print(f"lgpio failed: {e}")

# Try RPi.GPIO
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(22, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    val = GPIO.input(22)
    print(f"RPi.GPIO: GPIO22 = {val}")
    print("Monitoring for 5 seconds (touch the sensor)...")
    for i in range(50):
        v = GPIO.input(22)
        if v != val:
            print(f"  CHANGE at {i*0.1:.1f}s: GPIO22 = {v}")
            val = v
        time.sleep(0.1)
    GPIO.cleanup()
    print("RPi.GPIO works!")
    sys.exit(0)
except ImportError:
    print("RPi.GPIO not available")
except Exception as e:
    print(f"RPi.GPIO failed: {e}")

# Try gpiod
try:
    import gpiod
    chip = gpiod.Chip("/dev/gpiochip4")
    line = chip.get_line(22)
    line.request(consumer="touch_check", type=gpiod.LINE_REQ_DIR_IN)
    val = line.get_value()
    print(f"gpiod: GPIO22 = {val}")
    print("Monitoring for 5 seconds (touch the sensor)...")
    for i in range(50):
        v = line.get_value()
        if v != val:
            print(f"  CHANGE at {i*0.1:.1f}s: GPIO22 = {v}")
            val = v
        time.sleep(0.1)
    line.release()
    print("gpiod works!")
    sys.exit(0)
except ImportError:
    print("gpiod not available")
except Exception as e:
    print(f"gpiod failed: {e}")

print("No GPIO library available! Install lgpio or RPi.GPIO or gpiod")
