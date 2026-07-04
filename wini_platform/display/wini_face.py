"""Wini face renderer.

Renders to a plain RGB uint8 numpy array (landscape orientation).
All color tuples in this module are RGB. cv2 drawing primitives are
channel-blind — they copy bytes literally — so RGB tuples pass through
unchanged to the RGB-native display driver.
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Tuple
import math
import random
import time

WIDTH  = 480   # landscape render width
HEIGHT = 320   # landscape render height

# RGB colors used in render-time overlays.
BG_COLOR      = (0,   0,   0  )    # black background
TEAR_COLOR    = (130, 220, 255)    # light blue
SWEAT_COLOR   = (130, 220, 255)    # light blue
BLUSH_COLOR   = (200, 50,  150)    # pink
SPARKLE_COLOR = (255, 255, 255)    # white
TONGUE_COLOR  = (150, 255, 255)    # pale cyan
PUPIL_COLOR   = (0,   0,   0  )    # black
HIGHLIGHT_COLOR = (255, 255, 255)  # specular catchlight


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b by fraction t."""
    return a + (b - a) * t


def _build_heart_unit_points(steps: int = 50) -> np.ndarray:
    """Heart curve as (steps, 2) float32 array, centered to fit a 32×34 box."""
    ts = np.linspace(0.0, 2.0 * np.pi, steps, endpoint=False, dtype=np.float32)
    px = 16.0 * np.sin(ts) ** 3
    py = -(13.0*np.cos(ts) - 5.0*np.cos(2*ts) - 2.0*np.cos(3*ts) - np.cos(4*ts))
    py -= 5.0   # vertical centering offset (matches original adjustment)
    return np.stack([px, py], axis=1)


_HEART_UNIT_POINTS = _build_heart_unit_points()


@dataclass
class EyeParams:
    """Parameters defining eye appearance for a specific emotion."""
    eyelid_top: float = 0.0
    eyelid_bottom: float = 0.0
    brow_angle: float = 0.0
    eye_width_scale: float = 1.0
    eye_height_scale: float = 1.0
    color:  Tuple[int, int, int] = (255, 255, 255)
    color2: Tuple[int, int, int] = None

    def __post_init__(self):
        if self.color2 is None:
            self.color2 = self.color

    shape_type: str = 'oval'
    lid_asymmetry: float = 0.0
    is_crying:     bool = False
    is_tongue_out: bool = False
    is_sweating:   bool = False
    is_blushing:   bool = False
    is_excited:    bool = False
    is_dizzy:      bool = False
    is_xeyed:      bool = False
    is_smirking:   bool = False
    is_smiling:    bool = False
    iris_color_override:  Tuple[int, int, int] = None   # overrides set_style iris color
    iris_color2_override: Tuple[int, int, int] = None   # inner iris color for radial
    pupil_factor:  float = 1.0                          # multiplier on base pupil size


@dataclass
class _RenderContext:
    """Per-frame state passed to internal render helpers."""
    center_x:   int
    center_y:   int
    cur_w:      float
    cur_h:      float
    gaze_dx:    float
    gaze_dy:    float
    pupil_size: float
    eye_color:  Tuple[int, int, int]


class EmotionPresets:
    """Pre-defined emotion parameters. Intensity modulates interpolation toward these."""

    # All `color` / `color2` tuples below are RGB. Default eye fill is white;
    # only ANGRY and LOVE override.
    NEUTRAL = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=0.0,
        eye_width_scale=1.0, eye_height_scale=1.0,
        color=(255, 255, 255),
        color2=(255, 255, 255),
    )
    HAPPY = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.55,
        brow_angle=-5.0,
        eye_width_scale=1.0, eye_height_scale=0.75,
        color=(255, 255, 255),
        is_smiling=True,
    )
    SAD = EyeParams(
        eyelid_top=0.35, eyelid_bottom=0.0,
        brow_angle=-20.0,
        eye_width_scale=1.0, eye_height_scale=0.9,
        color=(255, 255, 255),
    )
    ANGRY = EyeParams(
        eyelid_top=0.25, eyelid_bottom=0.1,
        brow_angle=30.0,
        eye_width_scale=1.05, eye_height_scale=0.85,
        color=(255, 255, 255),
        iris_color_override=(255, 0, 0),     # bright red iris (outer)
        iris_color2_override=(90, 0, 0),     # dark red center (inner, for radial)
    )
    SURPRISED = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=-15.0,
        eye_width_scale=1.2, eye_height_scale=1.3,
        color=(255, 255, 255),
        pupil_factor=1.4,
    )
    CONFUSED = EyeParams(
        eyelid_top=0.15, eyelid_bottom=0.0,
        brow_angle=-10.0,
        eye_width_scale=1.0, eye_height_scale=0.9,
        color=(255, 255, 255),
        lid_asymmetry=0.6,
    )
    TIRED = EyeParams(
        eyelid_top=0.55, eyelid_bottom=0.1,
        brow_angle=0.0,
        eye_width_scale=1.0, eye_height_scale=0.85,
        color=(255, 255, 255),
    )
    BLUSH = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.55,
        brow_angle=-5.0,
        eye_width_scale=1.0, eye_height_scale=0.75,
        color=(255, 255, 255),
        is_blushing=True,
    )
    LOVE = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=0.0,
        eye_width_scale=0.85, eye_height_scale=0.85,
        color=(255, 0, 0),   # red hearts
        shape_type='heart',
    )
    EXCITEMENT = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=-18.0,
        eye_width_scale=1.15, eye_height_scale=1.2,
        color=(255, 255, 255),
        is_excited=True,
    )
    SMIRK = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=7.0,
        eye_width_scale=1.0, eye_height_scale=0.9,
        color=(255, 255, 255),
        lid_asymmetry=0.4,
        is_smirking=True
    )
    DIZZY = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=0.0,
        eye_width_scale=1.05, eye_height_scale=1.05,
        color=(255, 255, 255),
        shape_type='spiral',
        is_dizzy=True
    )
    XEYES = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=-5.0,
        eye_width_scale=1.05, eye_height_scale=1.05,
        color=(255, 255, 255),
        shape_type='xeye',
        is_xeyed=True
    )
    SLEEPY = EyeParams(
        eyelid_top=0.75, eyelid_bottom=0.25,
        brow_angle=-3.0,
        eye_width_scale=1.0, eye_height_scale=1.0,
        color=(255, 255, 255),
    )
    WINK = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=0.0,
        eye_width_scale=1.0, eye_height_scale=1.0,
        color=(255, 255, 255),
        lid_asymmetry=1.0,        # right eye fully closed
    )
    EVIL = EyeParams(
        eyelid_top=0.45, eyelid_bottom=0.3,
        brow_angle=22.0,
        eye_width_scale=1.0, eye_height_scale=1.0,
        color=(255, 255, 255),
        iris_color_override=(180, 220, 0),     # toxic yellow-green
        iris_color2_override=(35, 60, 0),
    )
    SCARED = EyeParams(
        eyelid_top=0.05, eyelid_bottom=0.05,
        brow_angle=-25.0,
        eye_width_scale=1.0, eye_height_scale=1.1,
        color=(255, 255, 255),
        pupil_factor=1.6,                       # dilated pupils
    )


class WiniFace:
    def __init__(self, width=WIDTH, height=HEIGHT):
        self.width  = width
        self.height = height

        self.current_params    = EyeParams()
        self.target_params     = EmotionPresets.NEUTRAL
        self.current_intensity = 0.5
        self.target_intensity  = 0.5

        self.current_gaze_x = 0.0
        self.current_gaze_y = 0.0
        self.current_gaze_z = 0.4
        self.target_gaze_x  = 0.0
        self.target_gaze_y  = 0.0
        self.target_gaze_z  = 0.4
        self.gaze_bias_x    = 0.0
        self.gaze_bias_y    = 0.0

        self._last_update_time = time.time()
        self.gaze_duration     = 0.20
        self.emotion_duration  = 0.30

        self.current_smile     = 0.0     # smoothly lerped 0..1 smile amount
        self.is_blinking       = False
        self.blink_start_time  = 0
        self.blink_duration    = 0.25
        self.blink_rate        = 1.0     # 0 = disabled; >1 faster average
        self._next_blink_time  = None    # absolute time; lazily scheduled

        self.heartbeat_start    = 0
        self.current_beat_scale = 1.0
        self.tear_drop_start    = 0
        self.current_tear_time  = 0.0
        self.tongue_start        = 0
        self.current_tongue_time = 0.0
        self.sweat_drop_start   = 0
        self.current_sweat_time = 0.0
        self.sparkle_start      = 0
        self.current_sparkle_time = 0.0
        self.dizzy_start        = 0
        self.current_dizzy_time = 0.0

        self.eye_style     = 'linear'
        self.custom_color1 = None
        self.custom_color2 = None

        self.base_eye_w      = 140
        self.base_eye_h      = 160
        self.eye_spacing     = 50
        self.eye_y_offset    = -60
        self.base_pupil_size = 0.35
        self.iris_size       = 0.55
        self.iris_style      = 'solid'         # 'solid' or 'radial'
        self.current_pupil_factor = 1.0        # lerps toward target_params.pupil_factor
        self.custom_iris_color  = (0, 0, 255)  # RGB; outer ring (iris edge) when radial
        self.custom_iris_color2 = None         # RGB; inner ring (pupil edge) when radial

        self._frame          = np.zeros((height, width, 3), dtype=np.uint8)
        self._grad_cache_key = None
        self._grad_mask      = None
        self._grad_img       = None

    # ── Public API ────────────────────────────────────────────────────────────

    def set_emotion(self, emotion_name: str, intensity: int):
        """Set emotion. intensity: 0-15 (4-bit)."""
        self.target_intensity = max(0, min(15, intensity)) / 15.0
        name = emotion_name.upper()
        if hasattr(EmotionPresets, name):
            self.target_params = getattr(EmotionPresets, name)
        else:
            self.target_params = EmotionPresets.NEUTRAL

    def set_style(self, style_name: str = None,
                  color1: Tuple[int, int, int] = None,
                  color2: Tuple[int, int, int] = None,
                  size_x: int = None, size_y: int = None,
                  separation: int = None, pos_y: int = None,
                  pupil_size: float = None, iris_size: float = None,
                  iris_color: Tuple[int, int, int] = None,
                  iris_color2: Tuple[int, int, int] = None,
                  iris_style: str = None,
                  gaze_offset_x: float = None, gaze_offset_y: float = None,
                  blink_rate: float = None):
        """Set eye styling.

        Eye background style (`style_name`): 'solid', 'linear', 'radial'.
        Iris style (`iris_style`): 'solid' (default) or 'radial'.
            'radial' produces a circular gradient between iris_color (outer,
            at the iris edge) and iris_color2 (inner, at the pupil edge).
        blink_rate: 0 disables blinking; 1.0 is the default cadence; higher
            values shorten the random delay between blinks proportionally.
        """
        if style_name in ('solid', 'linear', 'radial'):
            self.eye_style = style_name
        if color1 is not None:
            self.custom_color1 = color1
        if color2 is not None:
            self.custom_color2 = color2
        if size_x     is not None: self.base_eye_w      = size_x
        if size_y     is not None: self.base_eye_h      = size_y
        if separation is not None: self.eye_spacing     = separation
        if pos_y      is not None: self.eye_y_offset    = pos_y
        if pupil_size is not None: self.base_pupil_size = max(0.0, min(1.0, pupil_size))
        if iris_size  is not None: self.iris_size       = max(0.0, min(1.0, iris_size))
        if iris_color is not None:
            self.custom_iris_color = (iris_color[0], iris_color[1], iris_color[2])
        if iris_color2 is not None:
            self.custom_iris_color2 = (iris_color2[0], iris_color2[1], iris_color2[2])
        if iris_style in ('solid', 'radial'):
            self.iris_style = iris_style
        if gaze_offset_x is not None: self.gaze_bias_x = gaze_offset_x
        if gaze_offset_y is not None: self.gaze_bias_y = gaze_offset_y
        if blink_rate is not None:
            self.blink_rate = max(0.0, float(blink_rate))
            self._next_blink_time = None   # reschedule on next update()

    def set_gaze(self, x: float, y: float, z: float,
                 bias_x: float = None, bias_y: float = None):
        if bias_x is not None: self.gaze_bias_x = bias_x
        if bias_y is not None: self.gaze_bias_y = bias_y
        self.target_gaze_x = max(-1.0, min(1.0, x + self.gaze_bias_x))
        self.target_gaze_y = max(-1.0, min(1.0, y + self.gaze_bias_y))
        self.target_gaze_z = max(0.0,  min(1.0, z))

    def trigger_blink(self):
        if not self.is_blinking:
            self.is_blinking      = True
            self.blink_start_time = time.time()
            self.blink_duration   = 0.25

    def _schedule_next_blink(self, now: float):
        # 80% normal pause (2-6 s), 20% quick double-blink (0.2-0.4 s).
        if random.random() < 0.2:
            base_delay = random.uniform(0.2, 0.4)
        else:
            base_delay = random.uniform(2.0, 6.0)
        self._next_blink_time = now + base_delay / self.blink_rate

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self):
        """Interpolate all parameters toward targets using time-based smoothing."""
        now = time.time()
        dt  = min(now - self._last_update_time, 0.1)
        self._last_update_time = now

        # Auto-blink scheduler.
        if self.blink_rate > 0:
            if self._next_blink_time is None:
                self._schedule_next_blink(now)
            elif now >= self._next_blink_time:
                self.trigger_blink()
                self._schedule_next_blink(now)

        gaze_decay    = 1.0 - math.exp(-3.0 * dt / self.gaze_duration)
        emotion_decay = 1.0 - math.exp(-3.0 * dt / self.emotion_duration)
        s = emotion_decay

        self.current_intensity = lerp(self.current_intensity, self.target_intensity, s)
        self.current_gaze_x = lerp(self.current_gaze_x, self.target_gaze_x, gaze_decay)
        self.current_gaze_y = lerp(self.current_gaze_y, self.target_gaze_y, gaze_decay)
        self.current_gaze_z = lerp(self.current_gaze_z, self.target_gaze_z, gaze_decay)

        t         = self.target_params
        intensity = self.current_intensity
        is_neutral = (t is EmotionPresets.NEUTRAL)
        p = self.current_params

        if is_neutral:
            p.eyelid_top    = lerp(p.eyelid_top,    (1.0 - intensity) * 0.5,  s)
            p.eyelid_bottom = lerp(p.eyelid_bottom,  (1.0 - intensity) * 0.25, s)
        else:
            p.eyelid_top    = lerp(p.eyelid_top,    t.eyelid_top    * intensity, s)
            p.eyelid_bottom = lerp(p.eyelid_bottom, t.eyelid_bottom * intensity, s)

        p.brow_angle       = lerp(p.brow_angle,       t.brow_angle * intensity, s)
        p.eye_width_scale  = lerp(p.eye_width_scale,  lerp(1.0, t.eye_width_scale,  intensity), s)
        p.eye_height_scale = lerp(p.eye_height_scale, lerp(1.0, t.eye_height_scale, intensity), s)
        p.lid_asymmetry    = lerp(p.lid_asymmetry,    t.lid_asymmetry * intensity, s)
        # Pupil dilation factor — lerp from 1.0 toward t.pupil_factor.
        target_pupil_factor    = lerp(1.0, t.pupil_factor, intensity)
        self.current_pupil_factor = lerp(self.current_pupil_factor, target_pupil_factor, s)

        base_color  = self.custom_color1 if self.custom_color1 else (255, 255, 255)
        base_color2 = self.custom_color2 if self.custom_color2 else (255, 255, 255)
        t_color  = base_color  if is_neutral else t.color
        t_color2 = base_color2 if is_neutral else t.color2

        p.color = (
            int(lerp(p.color[0], lerp(base_color[0], t_color[0],  intensity), s)),
            int(lerp(p.color[1], lerp(base_color[1], t_color[1],  intensity), s)),
            int(lerp(p.color[2], lerp(base_color[2], t_color[2],  intensity), s)),
        )
        p.color2 = (
            int(lerp(p.color2[0], lerp(base_color2[0], t_color2[0], intensity), s)),
            int(lerp(p.color2[1], lerp(base_color2[1], t_color2[1], intensity), s)),
            int(lerp(p.color2[2], lerp(base_color2[2], t_color2[2], intensity), s)),
        )

        is_shape_transitioning = p.shape_type != t.shape_type
        if is_shape_transitioning:
            sqsh = 0.5
            p.eye_width_scale  = lerp(p.eye_width_scale,  sqsh, s * 1.5)
            p.eye_height_scale = lerp(p.eye_height_scale, sqsh, s * 1.5)
            if abs(p.eye_height_scale - sqsh) < 0.2 or intensity > 0.6:
                p.shape_type = t.shape_type
        else:
            p.shape_type = t.shape_type

        # Pulse modulation: LOVE heartbeat or EXCITEMENT pulse.
        now = time.time()
        if t.shape_type == 'heart' and intensity > 0.3:
            if self.heartbeat_start == 0: self.heartbeat_start = now
            e = (now - self.heartbeat_start) % 1.0
            if   e < 0.1: self.current_beat_scale = 1.0  + 0.15 * (e / 0.1)
            elif e < 0.2: self.current_beat_scale = 1.15 - 0.15 * ((e - 0.1) / 0.1)
            elif e < 0.3: self.current_beat_scale = 1.0  + 0.10 * ((e - 0.2) / 0.1)
            elif e < 0.4: self.current_beat_scale = 1.10 - 0.10 * ((e - 0.3) / 0.1)
            else:         self.current_beat_scale = 1.0
        elif t is EmotionPresets.EXCITEMENT and intensity > 0.3:
            if self.heartbeat_start == 0: self.heartbeat_start = now
            e = now - self.heartbeat_start
            # Smooth ~3 Hz sine pulse, ±6% scale.
            self.current_beat_scale = 1.0 + 0.06 * math.sin(2 * math.pi * e * 3.0)
        else:
            self.heartbeat_start    = 0
            self.current_beat_scale = lerp(self.current_beat_scale, 1.0, 0.3)

        # Crying (SAD moderate+)
        if t is EmotionPresets.SAD and intensity > (5/15.0):
            p.is_crying = True
            if self.tear_drop_start == 0: self.tear_drop_start = now
            self.current_tear_time = now - self.tear_drop_start
        else:
            p.is_crying = False; self.tear_drop_start = 0; self.current_tear_time = 0.0

        # Tongue (CONFUSED moderate+)
        if t is EmotionPresets.CONFUSED and intensity > (5/15.0):
            p.is_tongue_out = True
            if self.tongue_start == 0: self.tongue_start = now
            self.current_tongue_time = now - self.tongue_start
        else:
            p.is_tongue_out = False; self.tongue_start = 0; self.current_tongue_time = 0.0

        # Sweat (TIRED moderate+)
        if t is EmotionPresets.TIRED and intensity > (5/15.0):
            p.is_sweating = True
            if self.sweat_drop_start == 0: self.sweat_drop_start = now
            self.current_sweat_time = now - self.sweat_drop_start
        else:
            p.is_sweating = False; self.sweat_drop_start = 0; self.current_sweat_time = 0.0

        p.is_blushing = (t is EmotionPresets.BLUSH and intensity > 0.3)

        if t is EmotionPresets.EXCITEMENT and intensity > 0.3:
            p.is_excited = True
            if self.sparkle_start == 0: self.sparkle_start = now
            self.current_sparkle_time = now - self.sparkle_start
        else:
            p.is_excited = False; self.sparkle_start = 0; self.current_sparkle_time = 0.0

        if t is EmotionPresets.DIZZY and intensity > 0.1:
            p.is_dizzy = True
            if self.dizzy_start == 0: self.dizzy_start = now
            self.current_dizzy_time = now - self.dizzy_start
        else:
            p.is_dizzy = False; self.dizzy_start = 0; self.current_dizzy_time = 0.0

        p.is_xeyed    = (t is EmotionPresets.XEYES and intensity > 0.1)
        p.is_smirking = (t is EmotionPresets.SMIRK and intensity > 0.1)
        p.is_smiling  = bool(t.is_smiling) and intensity > 0.1
        smile_target  = (intensity if bool(t.is_smiling) else 0.0)
        self.current_smile = lerp(self.current_smile, smile_target, s)

        # Blink override
        if self.is_blinking:
            elapsed = now - self.blink_start_time
            if elapsed >= self.blink_duration:
                self.is_blinking = False
            else:
                prog = elapsed / self.blink_duration
                if   prog < 0.25: bv = 0.5 - 0.5 * math.cos(prog / 0.25 * math.pi)
                elif prog < 0.60: bv = 1.0
                else:             bv = 0.5 + 0.5 * math.cos((prog - 0.6) / 0.4 * math.pi)
                bv = max(0.0, min(1.0, bv))
                p.eyelid_top    = max(p.eyelid_top,    bv)
                p.eyelid_bottom = max(p.eyelid_bottom, bv * 0.3)

    # ── Render ────────────────────────────────────────────────────────────────

    def _draw_radial_iris(self, eye_img: np.ndarray, cx: int, cy: int,
                          i_w: int, i_h: int, p_w: int,
                          outer: Tuple[int, int, int],
                          inner: Tuple[int, int, int]) -> None:
        """Draw an iris with a circular gradient from `inner` (at the pupil
        edge) to `outer` (at the iris edge). If `inner` is None, a darkened
        version of `outer` is used.
        """
        if inner is None:
            inner = tuple(int(v * 0.4) for v in outer)

        # Normalized elliptical distance in iris-local coords.
        yi, xi = np.mgrid[-i_h:i_h + 1, -i_w:i_w + 1].astype(np.float32)
        d = np.sqrt((xi / i_w) ** 2 + (yi / i_h) ** 2)

        pupil_ratio = (p_w / i_w) if i_w > 0 else 0.0
        denom = max(0.001, 1.0 - pupil_ratio)
        t = np.clip((d - pupil_ratio) / denom, 0.0, 1.0)[..., None]

        c_in  = np.array(inner, dtype=np.float32)
        c_out = np.array(outer, dtype=np.float32)
        gradient = (c_in + (c_out - c_in) * t).astype(np.uint8)
        iris_mask = d <= 1.0

        # Paste with bounds clipping.
        h_g, w_g = gradient.shape[:2]
        y1 = cy - i_h; y2 = cy + i_h + 1
        x1 = cx - i_w; x2 = cx + i_w + 1
        dy1 = 0; dy2 = h_g
        dx1 = 0; dx2 = w_g
        if y1 < 0:
            dy1 = -y1; y1 = 0
        if y2 > eye_img.shape[0]:
            dy2 = h_g - (y2 - eye_img.shape[0]); y2 = eye_img.shape[0]
        if x1 < 0:
            dx1 = -x1; x1 = 0
        if x2 > eye_img.shape[1]:
            dx2 = w_g - (x2 - eye_img.shape[1]); x2 = eye_img.shape[1]
        if y2 > y1 and x2 > x1 and dy2 > dy1 and dx2 > dx1:
            m = iris_mask[dy1:dy2, dx1:dx2]
            eye_img[y1:y2, x1:x2][m] = gradient[dy1:dy2, dx1:dx2][m]

    def _draw_star(self, img: np.ndarray, cx: int, cy: int,
                   outer_r: int, inner_r: int,
                   color: Tuple[int, int, int]) -> None:
        pts = []
        for k in range(8):
            angle_rad = math.pi / 4 * k - math.pi / 4
            r = outer_r if k % 2 == 0 else inner_r
            pts.append([int(cx + r * math.cos(angle_rad)),
                        int(cy + r * math.sin(angle_rad))])
        cv2.fillPoly(img, [np.array(pts, np.int32).reshape((-1, 1, 2))], color)

    def _draw_eye(self, img: np.ndarray, ctx: _RenderContext,
                  offset_x: float, is_right_eye: bool) -> None:
        p     = self.current_params
        cur_w = ctx.cur_w
        cur_h = ctx.cur_h
        ex    = int(ctx.center_x + offset_x)
        ey    = int(ctx.center_y)
        eye_color = ctx.eye_color

        asym    = p.lid_asymmetry if is_right_eye else 0.0
        lid_top = min(1.0, p.eyelid_top + asym)
        lid_bot = min(1.0, p.eyelid_bottom + asym * 0.3)

        # === Draw eye shape ===
        if p.shape_type == 'heart':
            sx = ex + _HEART_UNIT_POINTS[:, 0] * (cur_w / 32.0)
            sy = ey + _HEART_UNIT_POINTS[:, 1] * (cur_h / 34.0)
            pts = np.stack([sx, sy], axis=1).astype(np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(img, [pts], eye_color)

        elif p.shape_type == 'xeye':
            arm_w = int(cur_w * 0.22)
            arm_h = int(cur_h * 0.22)
            thick = max(5, int(min(cur_w, cur_h) * 0.10))
            cv2.line(img, (ex-arm_w, ey-arm_h), (ex+arm_w, ey+arm_h), eye_color, thick, cv2.LINE_AA)
            cv2.line(img, (ex+arm_w, ey-arm_h), (ex-arm_w, ey+arm_h), eye_color, thick, cv2.LINE_AA)
            tip_r = thick // 2
            for tip in [(ex-arm_w, ey-arm_h), (ex+arm_w, ey+arm_h),
                        (ex+arm_w, ey-arm_h), (ex-arm_w, ey+arm_h)]:
                cv2.circle(img, tip, tip_r, eye_color, -1)

        elif p.shape_type == 'spiral':
            rot_rad      = math.radians((self.current_dizzy_time * 60) % 360)
            thick        = max(3, int(min(cur_w, cur_h) * 0.06))
            max_radius_x = cur_w / 2 * 0.85
            max_radius_y = cur_h / 2 * 0.85
            steps        = 120
            total_angle  = 3.0 * 2 * np.pi    # 3 turns

            fracs  = np.linspace(0.0, 1.0, steps + 1, dtype=np.float32)
            angles = fracs * total_angle + rot_rad
            xs = ex + (max_radius_x * fracs) * np.cos(angles)
            ys = ey + (max_radius_y * fracs) * np.sin(angles)
            pts_arr = np.stack([xs, ys], axis=1).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(img, [pts_arr], False, eye_color, thick, cv2.LINE_AA)

        else:
            ax_w = int(cur_w / 2)
            ax_h = int(cur_h / 2)
            if ax_w > 0 and ax_h > 0:
                eye_color2 = p.color2
                current_style  = self.eye_style
                if current_style == 'linear' and eye_color == eye_color2:
                    current_style = 'solid'

                w_bb = 2 * ax_w
                h_bb = 2 * ax_h

                if current_style == 'linear':
                    cache_key = (ax_w, ax_h, eye_color, eye_color2, 'linear')
                    if self._grad_cache_key != cache_key:
                        self._grad_cache_key = cache_key
                        self._grad_mask = np.zeros((h_bb, w_bb), dtype=np.uint8)
                        cv2.ellipse(self._grad_mask, (ax_w, ax_h), (ax_w, ax_h), 0, 0, 360, 255, -1)
                        resf  = np.linspace(eye_color, eye_color2, h_bb, dtype=np.float32)
                        noise = np.random.uniform(-2.5, 2.5, (h_bb, w_bb, 3)).astype(np.float32)
                        self._grad_img = np.clip(resf.reshape(h_bb, 1, 3) + noise, 0, 255).astype(np.uint8)
                    mask    = self._grad_mask
                    eye_img = self._grad_img.copy()

                elif current_style == 'radial':
                    mask = np.zeros((h_bb, w_bb), dtype=np.uint8)
                    cv2.ellipse(mask, (ax_w, ax_h), (ax_w, ax_h), 0, 0, 360, 255, -1)
                    px_c = ax_w + ctx.gaze_dx
                    py_c = ax_h + ctx.gaze_dy
                    y_grid, x_grid = np.mgrid[0:h_bb, 0:w_bb]
                    d = np.clip(np.hypot((x_grid-px_c)/ax_w, (y_grid-py_c)/ax_h),
                                0, 1).astype(np.float32)[:, :, None]
                    c_in  = np.array(eye_color2, dtype=np.float32)
                    c_out = np.array(eye_color,  dtype=np.float32)
                    gradient = c_in + (c_out - c_in) * d   # broadcast over RGB
                    noise    = np.random.uniform(-2.5, 2.5, gradient.shape).astype(np.float32)
                    eye_img  = np.clip(gradient + noise, 0, 255).astype(np.uint8)

                else:  # solid
                    mask    = np.zeros((h_bb, w_bb), dtype=np.uint8)
                    cv2.ellipse(mask, (ax_w, ax_h), (ax_w, ax_h), 0, 0, 360, 255, -1)
                    eye_img = np.zeros((h_bb, w_bb, 3), dtype=np.uint8)
                    eye_img[:] = eye_color

                # === Draw Iris and Pupil ===
                if ctx.pupil_size > 0.01 and p.shape_type != 'heart':
                    i_w = int(cur_w * self.iris_size / 2)
                    i_h = int(cur_h * self.iris_size / 2)
                    p_w = int(cur_w * ctx.pupil_size / 2)
                    p_h = int(cur_h * ctx.pupil_size / 2)
                    px_local = int(ax_w + ctx.gaze_dx)
                    py_local = int(ax_h + ctx.gaze_dy)

                    if i_w > 0 and i_h > 0:
                        # Per-emotion iris color override (e.g. ANGRY → red).
                        target = self.target_params
                        iris_outer = (target.iris_color_override
                                      if target.iris_color_override is not None
                                      else self.custom_iris_color)
                        iris_inner = (target.iris_color2_override
                                      if target.iris_color2_override is not None
                                      else self.custom_iris_color2)

                        # Slightly darker border around the iris.
                        border_rgb = tuple(int(v * 0.98) for v in iris_outer)
                        border_th = max(2, int(min(i_w, i_h) * 0.08))
                        cv2.ellipse(eye_img, (px_local, py_local),
                                    (i_w + border_th, i_h + border_th),
                                    0, 0, 360, border_rgb, -1)

                        if self.iris_style == 'radial':
                            self._draw_radial_iris(eye_img, px_local, py_local,
                                                   i_w, i_h, p_w,
                                                   iris_outer, iris_inner)
                        else:
                            cv2.ellipse(eye_img, (px_local, py_local), (i_w, i_h),
                                        0, 0, 360, iris_outer, -1)

                    if p_w > 0 and p_h > 0:
                        cv2.ellipse(eye_img, (px_local, py_local), (p_w, p_h),
                                    0, 0, 360, PUPIL_COLOR, -1)
                        # Specular highlight (catchlight)
                        h_x = int(px_local + p_w * 0.35)
                        h_y = int(py_local - p_h * 0.45)
                        h_w = max(1, int(p_w * 0.25))
                        h_h = max(1, int(p_h * 0.35))
                        cv2.ellipse(eye_img, (h_x, h_y), (h_w, h_h),
                                    25, 0, 360, HIGHLIGHT_COLOR, -1)

                # Paste masked eye onto main image
                y1 = int(ey - ax_h); y2 = int(ey + ax_h)
                x1 = int(ex - ax_w); x2 = int(ex + ax_w)
                dy1 = 0; dy2 = h_bb; dx1 = 0; dx2 = w_bb
                if y1 < 0:            dy1 = -y1;                     y1 = 0
                if y2 > img.shape[0]: dy2 = h_bb-(y2-img.shape[0]); y2 = img.shape[0]
                if x1 < 0:            dx1 = -x1;                     x1 = 0
                if x2 > img.shape[1]: dx2 = w_bb-(x2-img.shape[1]); x2 = img.shape[1]
                if y2 > y1 and x2 > x1 and dy2 > dy1 and dx2 > dx1:
                    m = mask[dy1:dy2, dx1:dx2] == 255
                    img[y1:y2, x1:x2][m] = eye_img[dy1:dy2, dx1:dx2][m]

            # === Draw tears ===
            if p.is_crying:
                cycle_time = 1.5
                offset     = 0.5 if is_right_eye else 0.0
                progress   = ((self.current_tear_time + offset) % cycle_time) / cycle_time
                tear_x       = int(ex + (cur_w*0.2 if is_right_eye else -cur_w*0.2))
                tear_start_y = int(ey + cur_h * 0.3)
                tear_y       = int(tear_start_y + progress * 60)
                tear_rx = 5; tear_ry = 9
                if   progress < 0.2: alpha_tear = progress / 0.2
                elif progress > 0.8: alpha_tear = (1.0 - progress) / 0.2
                else:                alpha_tear = 1.0
                tear_rx = int(tear_rx * alpha_tear); tear_ry = int(tear_ry * alpha_tear)
                if tear_rx > 0 and tear_ry > 0:
                    cv2.ellipse(img, (tear_x, tear_y), (tear_rx, tear_ry), 0, 0, 360, TEAR_COLOR, -1)
                    tip_y = tear_y - tear_ry
                    cv2.ellipse(img, (tear_x, tip_y),
                                (max(1, tear_rx//2), max(1, tear_ry//2)),
                                0, 0, 360, TEAR_COLOR, -1)

            # === Upper eyelid (curved) ===
            if lid_top > 0.01 or abs(p.brow_angle) > 0.1:
                lid_drop     = cur_h * lid_top
                tilt         = -p.brow_angle if is_right_eye else p.brow_angle
                lid_y_center = int((ey - ax_h) + lid_drop + cur_h * 0.08)
                margin       = int(self.base_eye_w * 0.6)
                left_x       = ex - margin; right_x = ex + margin
                m            = math.tan(math.radians(tilt))
                y_left       = int(lid_y_center + m * (left_x  - ex))
                y_right      = int(lid_y_center + m * (right_x - ex))
                pts = np.array([
                    [left_x,  0],
                    [right_x, 0],
                    [right_x, y_right],
                    [ex,      lid_y_center + int(lid_drop * 0.15)],
                    [left_x,  y_left]
                ], np.int32)
                cv2.fillPoly(img, [pts], BG_COLOR)

            # === Lower eyelid (curved) ===
            if lid_bot > 0.01:
                lid_rise     = cur_h * lid_bot
                lid_y_center = int((ey + ax_h) - lid_rise - cur_h * 0.05)
                margin       = int(self.base_eye_w * 0.5)
                left_x       = ex - margin; right_x = ex + margin
                pts = np.array([
                    [left_x,  lid_y_center],
                    [ex,      lid_y_center - int(lid_rise * 0.1)],
                    [right_x, lid_y_center],
                    [right_x, self.height],
                    [left_x,  self.height]
                ], np.int32)
                cv2.fillPoly(img, [pts], BG_COLOR)

    def render(self) -> np.ndarray:
        """Render the face into a landscape RGB uint8 array (HEIGHT x WIDTH x 3).

        Color values are RGB; the driver consumes RGB directly.
        This method must not call bitwise_not or do any RGB565/SPI work —
        all of that lives in WiniDisplayDriver.
        """
        img = self._frame
        img[:] = 0

        p = self.current_params

        ctx = _RenderContext(
            center_x   = self.width  // 2,
            center_y   = self.height // 2 + self.eye_y_offset,
            cur_w      = self.base_eye_w * p.eye_width_scale  * self.current_beat_scale,
            cur_h      = self.base_eye_h * p.eye_height_scale * self.current_beat_scale,
            gaze_dx    = self.current_gaze_x * 50.0,
            gaze_dy    = self.current_gaze_y * 50.0,
            pupil_size = max(0.05, min(0.7,
                              self.base_pupil_size * self.current_pupil_factor
                              + (self.current_gaze_z - 0.5) * 0.4)),
            eye_color  = p.color,
        )

        left_offset  = -(self.eye_spacing + ctx.cur_w / 2)
        right_offset =  (self.eye_spacing + ctx.cur_w / 2)
        self._draw_eye(img, ctx, left_offset,  is_right_eye=False)
        self._draw_eye(img, ctx, right_offset, is_right_eye=True)

        # Re-bind for the overlay sections below.
        center_x    = ctx.center_x
        center_y    = ctx.center_y
        cur_w       = ctx.cur_w
        cur_h       = ctx.cur_h
        eye_spacing = self.eye_spacing

        # === Blush cheeks (soft-edged via Gaussian blur on a local mask) ===
        if self.current_params.is_blushing:
            left_ex   = int(center_x + left_offset)
            right_ex  = int(center_x + right_offset)
            cheek_y   = int(center_y + cur_h / 2 + 30)

            # Localized region around the two cheeks — keeps the blur cheap.
            pad = 50
            y1 = max(0, cheek_y - pad)
            y2 = min(img.shape[0], cheek_y + pad)
            x1 = max(0, min(left_ex, right_ex) - 70)
            x2 = min(img.shape[1], max(left_ex, right_ex) + 70)
            if y2 > y1 and x2 > x1:
                mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
                cv2.ellipse(mask, (left_ex - x1, cheek_y - y1), (45, 28),
                            0, 0, 360, 255, -1)
                cv2.ellipse(mask, (right_ex - x1, cheek_y - y1), (45, 28),
                            0, 0, 360, 255, -1)
                mask = cv2.GaussianBlur(mask, (31, 31), 0)

                alpha_max = 0.7 * min(1.0, self.current_intensity * 2)
                mask_f = (mask.astype(np.float32) / 255.0 * alpha_max)[:, :, None]
                roi    = img[y1:y2, x1:x2].astype(np.float32)
                blush  = np.array(BLUSH_COLOR, dtype=np.float32)
                img[y1:y2, x1:x2] = (roi * (1.0 - mask_f) + blush * mask_f).astype(np.uint8)

        # === Excitement sparkles ===
        if self.current_params.is_excited:
            left_ex  = int(center_x + left_offset)
            right_ex = int(center_x + right_offset)
            ax_h_    = int(cur_h / 2)
            ax_w_    = int(cur_w / 2)
            t_sp     = self.current_sparkle_time; sparkle_cycle = 0.6
            phase_a  = (math.sin(2*math.pi*t_sp/sparkle_cycle) + 1) / 2
            phase_b  = phase_a   # sync: both sparkle groups pop together
            max_outer = 14; min_outer = 5

            r_a = int(min_outer + (max_outer-min_outer)*phase_a)
            r_b = int(min_outer + (max_outer-min_outer)*phase_b)
            if r_a >= 3: self._draw_star(img, left_ex  - ax_w_ - 10, center_y - ax_h_,    r_a, r_a//2, SPARKLE_COLOR)
            if r_b >= 3: self._draw_star(img, left_ex  + ax_w_ + 10, center_y + ax_h_//2, r_b, r_b//2, SPARKLE_COLOR)
            if r_b >= 3: self._draw_star(img, right_ex + ax_w_ + 10, center_y - ax_h_,    r_b, r_b//2, SPARKLE_COLOR)
            if r_a >= 3: self._draw_star(img, right_ex - ax_w_ - 10, center_y + ax_h_//2, r_a, r_a//2, SPARKLE_COLOR)

        # === Dizzy wavy lines ===
        if self.current_params.is_dizzy:
            wave_color = p.color
            x_start = int(center_x - cur_w * 1.1)
            x_end   = int(center_x + cur_w * 1.1)
            xs = np.arange(x_start, x_end, 3, dtype=np.int32)
            if xs.size > 1:
                t_ws = (xs - x_start).astype(np.float32) / max(1, x_end - x_start)
                wave = (6.0 * np.sin(4.0 * np.pi * t_ws)).astype(np.int32)
                for line_i in range(2):
                    y_base = int(center_y + cur_h * 0.72 + line_i * 16)
                    ys = y_base + wave
                    pts = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)
                    cv2.polylines(img, [pts], False, wave_color, 3, cv2.LINE_AA)

        # === XEYES open mouth ===
        if self.current_params.is_xeyed:
            mouth_color = p.color
            cv2.ellipse(img,
                        (center_x, int(center_y + cur_h*0.72)),
                        (int(cur_w*0.35), int(cur_h*0.15)),
                        0, 0, 360, mouth_color, -1)

        # === Smirk mouth ===
        if self.current_params.is_smirking:
            mouth_color   = p.color
            mouth_y_base  = int(center_y + cur_h * 0.88)
            mouth_left_x  = int(center_x - cur_w * 0.5)
            mouth_right_x = int(center_x + cur_w * 0.6)
            fracs = np.linspace(0.0, 1.0, 40, dtype=np.float32)
            mxs = mouth_left_x + (mouth_right_x - mouth_left_x) * fracs
            mys = mouth_y_base - fracs * fracs * 25.0
            pts = np.stack([mxs, mys], axis=1).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(img, [pts], False, mouth_color, 4, cv2.LINE_AA)

        # === Smile mouth (HAPPY) — gentle symmetric upward arc ===
        # Width and arc scale with `current_smile` (lerped 0..1) so the mouth
        # grows in / shrinks out smoothly when emotions change.
        if self.current_smile > 0.02:
            sa = self.current_smile
            smile_color  = (255, 255, 255)
            smile_y_base = int(center_y + cur_h * 0.95)
            smile_width  = int(cur_w * 0.55 * sa)
            smile_arc    = int(cur_h * 0.18 * sa)
            fracs = np.linspace(-1.0, 1.0, 40, dtype=np.float32)
            mxs = center_x + fracs * smile_width
            mys = smile_y_base + (1.0 - fracs * fracs) * smile_arc
            pts = np.stack([mxs, mys], axis=1).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(img, [pts], False, smile_color, 3, cv2.LINE_AA)

        # === Tongue (CONFUSED high intensity) ===
        if self.current_params.is_tongue_out:
            tongue_cx    = center_x - 5
            tongue_cy    = center_y + int(cur_h * 0.95)
            tongue_angle = math.sin(self.current_tongue_time * 3.0) * 30.0
            cv2.ellipse(img, (tongue_cx, tongue_cy), (14, 30),
                        int(tongue_angle), 0, 360, TONGUE_COLOR, -1)
            cv2.rectangle(img,
                          (tongue_cx - 24, 0),
                          (tongue_cx + 24, tongue_cy - 4),
                          BG_COLOR, -1)

        # === Sweat drop (TIRED high intensity) ===
        if self.current_params.is_sweating:
            progress    = (self.current_sweat_time % 2.0) / 2.0
            drop_x      = center_x + int(eye_spacing + cur_w + 10)
            drop_start_y = int(center_y - cur_h * 0.6)
            drop_end_y  = int(center_y - cur_h * 0.1)
            drop_y      = int(drop_start_y + progress * (drop_end_y - drop_start_y))
            if   progress < 0.15: alpha_drop = progress / 0.15
            elif progress > 0.85: alpha_drop = (1.0 - progress) / 0.15
            else:                 alpha_drop = 1.0
            drop_rx = max(1, int(7  * alpha_drop))
            drop_ry = max(1, int(10 * alpha_drop))
            cv2.ellipse(img, (drop_x, drop_y), (drop_rx, drop_ry), 0, 0, 360, SWEAT_COLOR, -1)
            cv2.ellipse(img, (drop_x, drop_y - drop_ry),
                        (max(1, drop_rx//2), max(1, drop_ry//2)),
                        0, 0, 360, SWEAT_COLOR, -1)

        return img

