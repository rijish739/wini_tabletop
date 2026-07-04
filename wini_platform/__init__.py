"""Wini ROS-less platform — one process replacing the five ROS platform nodes.

Blueprint: WINI_ROSLESS_PLATFORM_PLAN.md. Naming note: the plan drafted this
package as `platform/`, but a top-level package named `platform` shadows the
stdlib `platform` module (imported by requests, torch, sounddevice, ...), so
the package is `wini_platform` and lives inside the study-core checkout.

Entry points:
    python3 -m wini_platform                # the full platform (section 4)
    python3 -m wini_platform.display.demo   # Stage 1 acceptance demo
    python3 -m wini_platform.touch.demo     # Stage 2 acceptance demo
"""
