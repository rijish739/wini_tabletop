"""Device Capability Profile (§8.3, §1.18, review B7).

The planner and validator must know what the *real* device can execute — not a cloud
assumption that can drift from firmware (the disabled-ears defect on the Jetson robot is
the canonical example). At session start the device REPORTS a versioned profile; the
cloud caches it and every compiler drops primitives the report omits.

Phase 1+2 slice: the profile *schema* + a static ``WINIPI5_PROFILE`` default are here and
consumed by the planner/validator. The session-start handshake wire-up (device -> cloud)
is Phase 4; until then ``profile_from_report`` accepts a reported dict when one is present
and otherwise returns the winipi5 default, so the code path is already report-driven.

winipi5 facts (memory: winipi5-raspberry-pi5-device, wini-ui-rebuild; connection recipe):
    * Waveshare 7" DSI panel, PORTRAIT 600x1024, labwc/Wayland.
    * figure card 500x380 (wini_client/display_sinks.FIG_MAX_W/H) — the scene canvas default.
    * reSpeaker Lite audio out; GPIO22 + touchscreen touch in.
    * NO robot motors on the Pi (the robot body/ears belong to the Jetson build) ->
      robot_primitives is empty, so the validator drops ALL robot intents (§5.3 rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from .contracts import RobotPrimitive, _to_jsonable

PROFILE_SCHEMA_VERSION = 1


@dataclass
class DeviceCapabilityProfile:
    device_class: str = "raspberry_pi5"
    firmware_version: str = "unknown"
    profile_schema_version: int = PROFILE_SCHEMA_VERSION
    # display
    display_present: bool = True
    display_w: int = 600
    display_h: int = 1024
    orientation: str = "portrait"
    fig_max_w: int = 500                              # display_sinks.FIG_MAX_W
    fig_max_h: int = 380                              # display_sinks.FIG_MAX_H
    renderer: str = "pillow_lvgl"                     # RPi Pillow render -> LVGL card
    supports_authored_scene: bool = True
    supports_animation: bool = True
    supports_interactive_visual: bool = False         # Phase-3+ touch widgets
    # touch
    touch_present: bool = True
    # audio
    audio_out: bool = True
    audio_in: bool = True                             # mic (voice-first)
    tts: str = "cloud"                                # cloud TTS via the brain
    # robot embodiment — closed set; empty on the Pi (no motors)
    robot_primitives: list[RobotPrimitive] = field(default_factory=list)
    # capacity / transport limits (§24.3) — generous on RPi; tightened on ESP32
    max_beats_per_package: int = 0                    # 0 = unbounded (whole-turn package)
    max_visual_elements_per_beat: int = 0             # 0 = unbounded
    max_text_len_per_beat: int = 0                    # 0 = unbounded (never clamp answer)
    known_disabled_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _to_jsonable(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "DeviceCapabilityProfile":
        d = dict(d or {})
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in known and k != "robot_primitives"}
        prims = d.get("robot_primitives")
        if prims is not None:
            coerced = []
            for p in prims:
                try:
                    coerced.append(p if isinstance(p, RobotPrimitive) else RobotPrimitive(p))
                except ValueError:
                    continue                          # drop an unknown reported primitive
            kwargs["robot_primitives"] = coerced
        return cls(**kwargs)

    # convenience predicates the gate/validator read
    def can_render_visual(self) -> bool:
        return self.display_present and self.renderer not in ("", "none")

    def has_robot(self) -> bool:
        return bool(self.robot_primitives)

    def allows_primitive(self, prim: RobotPrimitive) -> bool:
        return prim in self.robot_primitives


#: The current live device. No robot primitives -> robot channel is dropped by the
#: validator on every turn. This is the profile the planner uses until the Phase-4
#: session-start handshake reports a real one.
WINIPI5_PROFILE = DeviceCapabilityProfile(
    device_class="raspberry_pi5",
    firmware_version="winipi5-labwc-wayland",
    robot_primitives=[],
    known_disabled_features=["robot_motors", "robot_ears"],
)


def profile_from_report(reported: dict | None) -> DeviceCapabilityProfile:
    """Return the device's capability profile. A reported dict (Phase-4 handshake) wins;
    absent/empty -> the winipi5 default. Never raises — a malformed report degrades to
    the default so a turn is never blocked on the handshake (§5.1 failure mode)."""
    if not reported:
        return WINIPI5_PROFILE
    try:
        return DeviceCapabilityProfile.from_dict(reported)
    except Exception:  # noqa: BLE001 — a bad report must never cost a turn
        return WINIPI5_PROFILE
