import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Tuple
import math
import time

# --- Configuration Constants ---
WIDTH = 480   # Landscape width (rendered first, then rotated to portrait)
HEIGHT = 320  # Landscape height
BG_COLOR = (0, 0, 0)  # Black background (BGR)

# --- Data Structures ---

@dataclass
class EyeParams:
    """Parameters defining eye appearance for a specific emotion."""
    # Eyelids: 0.0 = fully open, 1.0 = fully closed
    eyelid_top: float = 0.0
    eyelid_bottom: float = 0.0
    # Brow tilt (degrees): positive = angry (inner-down), negative = sad (inner-up)
    brow_angle: float = 0.0
    # Eye shape scaling
    eye_width_scale: float = 1.0
    eye_height_scale: float = 1.0
    # Eye color (BGR)
    color: Tuple[int, int, int] = (100, 35, 12)  # Light blue (pre-inverted for display)
    # Shape: 'oval' or 'heart'
    shape_type: str = 'oval'
    # Asymmetry for confused: offset applied to right eye lids
    lid_asymmetry: float = 0.0
    # Flag to trigger crying animation
    is_crying: bool = False
    # Flag to trigger tongue-out animation
    is_tongue_out: bool = False
    # Flag to trigger sweat drop animation
    is_sweating: bool = False
    # Flag to draw blush cheeks
    is_blushing: bool = False
    # Flag to draw excitement sparkles
    is_excited: bool = False
    # Flag for dizzy wavy lines below eyes
    is_dizzy: bool = False
    # Flag for X-eyes open mouth
    is_xeyed: bool = False
    # Flag for smirk side-mouth
    is_smirking: bool = False


class EmotionPresets:
    """Pre-defined emotion parameters. Intensity modulates interpolation toward these."""

    NEUTRAL = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,  # Resting position (intensity opens them)
        brow_angle=0.0,
        eye_width_scale=1.0, eye_height_scale=1.0,
        #color=(100, 35, 12)
        color=(255, 255, 255)
    )

    HAPPY = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.55,  # Bottom lid up = smile eyes
        brow_angle=-5.0,
        eye_width_scale=1.0, eye_height_scale=0.75,  # Squished vertically
        color=(100, 35, 12)
    )

    SAD = EyeParams(
        eyelid_top=0.35, eyelid_bottom=0.0,  # Droopy top
        brow_angle=-20.0,  # Inner brows raised
        eye_width_scale=1.0, eye_height_scale=0.9,
        color=(110, 40, 15)  # Slightly dimmer light blue
    )

    ANGRY = EyeParams(
        eyelid_top=0.25, eyelid_bottom=0.1,
        brow_angle=30.0,   # Inner brows down aggressively
        eye_width_scale=1.05, eye_height_scale=0.85,
        color=(0, 0, 255)  # Red
    )

    SURPRISED = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,  # Wide open
        brow_angle=-15.0,  # Brows raised
        eye_width_scale=1.2, eye_height_scale=1.3,  # Big eyes
        color=(100, 35, 12)
    )

    CONFUSED = EyeParams(
        eyelid_top=0.15, eyelid_bottom=0.0,
        brow_angle=-10.0,
        eye_width_scale=1.0, eye_height_scale=0.9,
        color=(100, 35, 12),
        lid_asymmetry=0.4  # Right eye squinted more
    )

    TIRED = EyeParams(
        eyelid_top=0.55, eyelid_bottom=0.1,  # Heavy drooping
        brow_angle=0.0,
        eye_width_scale=1.0, eye_height_scale=0.85,
        color=(115, 45, 18)  # Slightly dim light blue
    )

    BLUSH = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.55,  # Bottom lid up = smile eyes
        brow_angle=-5.0,
        eye_width_scale=1.0, eye_height_scale=0.75,  # Squished vertically
        color=(100, 35, 12),
        is_blushing=True
    )

    LOVE = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=0.0,
        eye_width_scale=0.85, eye_height_scale=0.85,
        color=(0, 0, 255),  # Red hearts
        shape_type='heart'
    )

    EXCITEMENT = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,      # Fully open — widest possible
        brow_angle=-18.0,                        # Raised brows: alert and lively
        eye_width_scale=1.15, eye_height_scale=1.2,  # Large bright eyes
        color=(0, 0, 255),                      # Pre-inverted warm yellow (bright)
        is_excited=True
    )

    SMIRK = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=7.0,                          # Slight smug inner-brow drop
        eye_width_scale=1.0, eye_height_scale=0.9,
        color=(255, 255, 255),                   # Dark eyes
        lid_asymmetry=0.4,                       # Right eye squinted = classic smirk
        is_smirking=True
    )

    DIZZY = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=0.0,
        eye_width_scale=1.05, eye_height_scale=1.05,
        color=(255, 255, 255),                   # Dark spiral lines
        shape_type='spiral',
        is_dizzy=True
    )

    XEYES = EyeParams(
        eyelid_top=0.0, eyelid_bottom=0.0,
        brow_angle=-5.0,                         # Slight raise for shocked look
        eye_width_scale=1.05, eye_height_scale=1.05,
        color=(255, 255, 255),                   # Dark X lines
        shape_type='xeye',
        is_xeyed=True
    )


# Fully open "base" state for interpolation
_BASE_OPEN = EyeParams()


class RobotEyes:
    def __init__(self, width=WIDTH, height=HEIGHT):
        self.width = width
        self.height = height

        # Current interpolated eye parameters (start fully neutral/open)
        self.current_params = EyeParams()
        self.target_params = EmotionPresets.NEUTRAL

        # Intensity: 0.0 to 1.0
        self.current_intensity = 0.5
        self.target_intensity = 0.5

        # Gaze: x, y, z (independent of emotion)
        self.current_gaze_x = 0.0  # -1.0 (left) to 1.0 (right)
        self.current_gaze_y = 0.0  # -1.0 (up) to 1.0 (down)
        self.current_gaze_z = 0.4  # 0.0 (tiny pupil) to 1.0 (large pupil)
        self.target_gaze_x = 0.0
        self.target_gaze_y = 0.0
        self.target_gaze_z = 0.4

        # Smoothing
        self.smoothing = 0.15

        # Blink state
        self.is_blinking = False
        self.blink_start_time = 0
        self.blink_duration = 0.15

        # Heartbeat state (for love emotion)
        self.heartbeat_start = 0
        self.current_beat_scale = 1.0

        # Crying state
        self.tear_drop_start = 0
        self.current_tear_time = 0.0

        # Tongue-out state (for confused emotion)
        self.tongue_start = 0
        self.current_tongue_time = 0.0

        # Sweat drop state (for tired emotion)
        self.sweat_drop_start = 0
        self.current_sweat_time = 0.0

        # Sparkle state (for excitement emotion)
        self.sparkle_start = 0
        self.current_sparkle_time = 0.0

        # Dizzy/spiral state (for DIZZY emotion)
        self.dizzy_start = 0
        self.current_dizzy_time = 0.0

        # Pre-allocated buffers
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Portrait output: 320h x 240w (after rotation)
        self._rgb565 = np.zeros((width, height), dtype=np.uint16)
        self._bg_bgr = np.array([BG_COLOR[2], BG_COLOR[1], BG_COLOR[0]], dtype=np.uint8)

        

    # --- Public API ---

    def set_emotion(self, emotion_name: str, intensity: int):
        """Set emotion. intensity: 0-15 (4-bit)."""
        self.target_intensity = max(0, min(15, intensity)) / 15.0
        name = emotion_name.upper()
        if hasattr(EmotionPresets, name):
            self.target_params = getattr(EmotionPresets, name)
        else:
            self.target_params = EmotionPresets.NEUTRAL

    def set_gaze(self, x: float, y: float, z: float):
        """
        Set gaze direction and pupil size (independent of emotion).
        x: -1.0 (left) to 1.0 (right)
        y: -1.0 (up) to 1.0 (down)
        z: 0.0 (tiny pupil) to 1.0 (large pupil)
        """
        self.target_gaze_x = max(-1.0, min(1.0, x))
        self.target_gaze_y = max(-1.0, min(1.0, y))
        self.target_gaze_z = max(0.0, min(1.0, z))

    def trigger_blink(self):
        """Manually trigger a blink."""
        if not self.is_blinking:
            self.is_blinking = True
            self.blink_start_time = time.time()
            self.blink_duration = 0.15

    # --- Update (smooth interpolation) ---

    def update(self):
        """Interpolate all parameters toward targets."""
        s = self.smoothing

        def lerp(a, b, t):
            return a + (b - a) * t

        # Intensity
        self.current_intensity = lerp(self.current_intensity, self.target_intensity, s)

        # Gaze (independent, always interpolated)
        self.current_gaze_x = lerp(self.current_gaze_x, self.target_gaze_x, s)
        self.current_gaze_y = lerp(self.current_gaze_y, self.target_gaze_y, s)
        self.current_gaze_z = lerp(self.current_gaze_z, self.target_gaze_z, s)

        # Eye params: intensity modulates emotion expression
        # For NEUTRAL: high intensity = eyes open, low = eyes closed (drooping top lid)
        # For others: high intensity = stronger emotion
        t = self.target_params
        intensity = self.current_intensity
        is_neutral = (t is EmotionPresets.NEUTRAL)

        p = self.current_params

        if is_neutral:
            # If neutral, the eyelids close as intensity drops towards 0
            # 1.0 intensity -> 0.0 droop (open)
            # 0.0 intensity -> top droops 0.8, bottom rises 0.4 (top closes twice as much)
            target_lid_top = (1.0 - intensity) * 0.5
            target_lid_bottom = (1.0 - intensity) * 0.25
            p.eyelid_top = lerp(p.eyelid_top, target_lid_top, s)
            p.eyelid_bottom = lerp(p.eyelid_bottom, target_lid_bottom, s)
        else:
            p.eyelid_top = lerp(p.eyelid_top, t.eyelid_top * intensity, s)
            p.eyelid_bottom = lerp(p.eyelid_bottom, t.eyelid_bottom * intensity, s)
        p.brow_angle = lerp(p.brow_angle, t.brow_angle * intensity, s)
        p.eye_width_scale = lerp(p.eye_width_scale,
                                  lerp(1.0, t.eye_width_scale, intensity), s)
        p.eye_height_scale = lerp(p.eye_height_scale,
                                   lerp(1.0, t.eye_height_scale, intensity), s)
        p.lid_asymmetry = lerp(p.lid_asymmetry, t.lid_asymmetry * intensity, s)

        # Color: lerp toward target color by intensity
        base_color = (100, 35, 12)  # Light blue (pre-inverted)
        p.color = (
            int(lerp(p.color[0], lerp(base_color[0], t.color[0], intensity), s)),
            int(lerp(p.color[1], lerp(base_color[1], t.color[1], intensity), s)),
            int(lerp(p.color[2], lerp(base_color[2], t.color[2], intensity), s)),
        )

        # Smooth scaling during shape transitions (prevents artifacts when shapes suddenly snap)
        # If we are transitioning to/from a shape change, squish the eye briefly so the snap is less noticeable
        is_shape_transitioning = p.shape_type != t.shape_type
        if is_shape_transitioning:
            # Drop the scale down rapidly while waiting for intensity to cross the threshold
            transition_squish = 0.5  # Scale multiplier during swap
            p.eye_width_scale = lerp(p.eye_width_scale, transition_squish, s * 1.5)
            p.eye_height_scale = lerp(p.eye_height_scale, transition_squish, s * 1.5)
            
            # Shape type snap: wait until the squish is deep or intensity crosses midpoint
            if abs(p.eye_height_scale - transition_squish) < 0.2 or intensity > 0.6:
                p.shape_type = t.shape_type
        else:
            # Normal snapping logic if the shape is the same (or after snapping completes)
            p.shape_type = t.shape_type

        # Heartbeat animation for love
        now = time.time()
        if t.shape_type == 'heart' and intensity > 0.3:
            if self.heartbeat_start == 0:
                self.heartbeat_start = now
            elapsed = (now - self.heartbeat_start) % 1.0
            # lub-dub pattern
            if elapsed < 0.1:
                self.current_beat_scale = 1.0 + 0.15 * (elapsed / 0.1)
            elif elapsed < 0.2:
                self.current_beat_scale = 1.15 - 0.15 * ((elapsed - 0.1) / 0.1)
            elif elapsed < 0.3:
                self.current_beat_scale = 1.0 + 0.1 * ((elapsed - 0.2) / 0.1)
            elif elapsed < 0.4:
                self.current_beat_scale = 1.1 - 0.1 * ((elapsed - 0.3) / 0.1)
            else:
                self.current_beat_scale = 1.0
        else:
            self.heartbeat_start = 0
            self.current_beat_scale = lerp(self.current_beat_scale, 1.0, 0.3)

        # Crying animation for SAD at intensity > 10
        if t is EmotionPresets.SAD and intensity > (10 / 15.0):
            p.is_crying = True
            if self.tear_drop_start == 0:
                self.tear_drop_start = now
            self.current_tear_time = now - self.tear_drop_start
        else:
            p.is_crying = False
            self.tear_drop_start = 0
            self.current_tear_time = 0.0

        # Tongue-out animation for CONFUSED at intensity > 10
        if t is EmotionPresets.CONFUSED and intensity > (10 / 15.0):
            p.is_tongue_out = True
            if self.tongue_start == 0:
                self.tongue_start = now
            self.current_tongue_time = now - self.tongue_start
        else:
            p.is_tongue_out = False
            self.tongue_start = 0
            self.current_tongue_time = 0.0

        # Sweat drop animation for TIRED at intensity > 10
        if t is EmotionPresets.TIRED and intensity > (10 / 15.0):
            p.is_sweating = True
            if self.sweat_drop_start == 0:
                self.sweat_drop_start = now
            self.current_sweat_time = now - self.sweat_drop_start
        else:
            p.is_sweating = False
            self.sweat_drop_start = 0
            self.current_sweat_time = 0.0

        # Blushing cheeks for BLUSH emotion
        p.is_blushing = (t is EmotionPresets.BLUSH and intensity > 0.3)

        # Excitement sparkles
        if t is EmotionPresets.EXCITEMENT and intensity > 0.3:
            p.is_excited = True
            if self.sparkle_start == 0:
                self.sparkle_start = now
            self.current_sparkle_time = now - self.sparkle_start
        else:
            p.is_excited = False
            self.sparkle_start = 0
            self.current_sparkle_time = 0.0

        # Dizzy spiral animation for DIZZY emotion
        if t is EmotionPresets.DIZZY and intensity > 0.1:
            p.is_dizzy = True
            if self.dizzy_start == 0:
                self.dizzy_start = now
            self.current_dizzy_time = now - self.dizzy_start
        else:
            p.is_dizzy = False
            self.dizzy_start = 0
            self.current_dizzy_time = 0.0

        # X-eyes mouth flag
        p.is_xeyed = (t is EmotionPresets.XEYES and intensity > 0.1)

        # Smirk side-mouth flag
        p.is_smirking = (t is EmotionPresets.SMIRK and intensity > 0.1)

        # Blink: override eyelids
        if self.is_blinking:
            elapsed = now - self.blink_start_time
            if elapsed >= self.blink_duration:
                self.is_blinking = False
            else:
                progress = elapsed / self.blink_duration
                # Triangle: 0→1→0
                blink_val = 1.0 - abs(2.0 * progress - 1.0)
                blink_val = max(0.0, min(1.0, blink_val))
                p.eyelid_top = max(p.eyelid_top, blink_val)
                p.eyelid_bottom = max(p.eyelid_bottom, blink_val * 0.3)

    # --- Rendering ---

    def render_to_rgb565(self) -> np.ndarray:
        """
        Render eyes in landscape (320×240), rotate to portrait (240×320),
        convert to RGB565, return numpy uint16 array.
        """
        img = self._frame
        img[:] = 0  # Black background

        p = self.current_params
        bg_bgr = BG_COLOR

        # Geometry
        center_x = self.width // 2   # 160
        center_y = self.height // 2 - 40  # 80 (shifted up 40px)
        eye_spacing = 50
        base_eye_w = 108
        base_eye_h = 135

        cur_w = base_eye_w * p.eye_width_scale * self.current_beat_scale
        cur_h = base_eye_h * p.eye_height_scale * self.current_beat_scale

        # Gaze offsets (independent of emotion)
        max_gaze_px = 50.0
        gaze_dx = self.current_gaze_x * max_gaze_px
        gaze_dy = self.current_gaze_y * max_gaze_px
        pupil_size = 0.15 + self.current_gaze_z * 0.45  # Map 0-1 to 0.15-0.6

        eye_color_bgr = (p.color[2], p.color[1], p.color[0])

        def draw_eye(offset_x, is_right_eye):
            ex = int(center_x + offset_x)
            ey = int(center_y)

            # Per-eye lid values (asymmetry for confused)
            asym = p.lid_asymmetry if is_right_eye else 0.0
            lid_top = min(1.0, p.eyelid_top + asym)
            lid_bot = min(1.0, p.eyelid_bottom)

            # === Draw eye shape ===
            if p.shape_type == 'heart':
                points = []
                steps = 50
                for i in range(steps):
                    t = (i / steps) * 2 * math.pi
                    px = 16 * (math.sin(t) ** 3)
                    py = -(13 * math.cos(t) - 5 * math.cos(2*t) -
                           2 * math.cos(3*t) - math.cos(4*t))
                    sx = ex + px * (cur_w / 2 / 16.0)
                    sy = ey + (py - 5) * (cur_h / 2 / 17.0)
                    points.append([int(sx), int(sy)])
                pts = np.array(points, np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(img, [pts], eye_color_bgr)
            elif p.shape_type == 'xeye':
                # X-shaped crossed eyes (smaller than before for balanced proportions)
                arm_w = int(cur_w * 0.22)
                arm_h = int(cur_h * 0.22)
                thick = max(5, int(min(cur_w, cur_h) * 0.10))
                cv2.line(img, (ex - arm_w, ey - arm_h), (ex + arm_w, ey + arm_h),
                         eye_color_bgr, thick, cv2.LINE_AA)
                cv2.line(img, (ex + arm_w, ey - arm_h), (ex - arm_w, ey + arm_h),
                         eye_color_bgr, thick, cv2.LINE_AA)
                # Rounded caps at each tip
                tip_r = thick // 2
                for tip in [(ex - arm_w, ey - arm_h), (ex + arm_w, ey + arm_h),
                            (ex + arm_w, ey - arm_h), (ex - arm_w, ey + arm_h)]:
                    cv2.circle(img, tip, tip_r, eye_color_bgr, -1)

            elif p.shape_type == 'spiral':
                # True Archimedean spiral that rotates slowly
                # r(theta) = a * theta — draws from center outward, creating a real spiral
                rot = (self.current_dizzy_time * 60) % 360  # 60 deg/sec rotation
                rot_rad = math.radians(rot)
                thick = max(3, int(min(cur_w, cur_h) * 0.06))
                max_radius_x = cur_w / 2 * 0.85
                max_radius_y = cur_h / 2 * 0.85
                total_turns = 3.0
                total_angle = total_turns * 2 * math.pi
                steps = 120
                pts = []
                for si in range(steps + 1):
                    theta = (si / steps) * total_angle
                    frac = theta / total_angle  # 0 to 1
                    rx = max_radius_x * frac
                    ry = max_radius_y * frac
                    angle = theta + rot_rad
                    sx = int(ex + rx * math.cos(angle))
                    sy = int(ey + ry * math.sin(angle))
                    pts.append([sx, sy])
                if len(pts) > 1:
                    pts_arr = np.array(pts, np.int32).reshape((-1, 1, 2))
                    cv2.polylines(img, [pts_arr], False, eye_color_bgr, thick, cv2.LINE_AA)

            else:
                ax_w = int(cur_w / 2)
                ax_h = int(cur_h / 2)
                if ax_w > 0 and ax_h > 0:
                    cv2.ellipse(img, (ex, ey), (ax_w, ax_h),
                                0, 0, 360, eye_color_bgr, -1)

                # === Draw pupil (gaze-controlled, independent of emotion) ===
                if pupil_size > 0.01 and p.shape_type != 'heart':
                    p_w = int(cur_w * pupil_size / 2)
                    p_h = int(cur_h * pupil_size / 2)
                    px = int(ex + gaze_dx)
                    py = int(ey + gaze_dy)
                    if p_w > 0 and p_h > 0:
                        cv2.ellipse(img, (px, py), (p_w, p_h),
                                    0, 0, 360, (0, 0, 0), -1)

                # === Draw tears (for crying animation) ===
                if p.is_crying:
                    # Animate a tear dropping down the cheek
                    # Tear cycle offsets so left/right don't fall at the exact same sub-millisecond
                    cycle_time = 1.5
                    offset = 0.0 if not is_right_eye else 0.5
                    progress = ((self.current_tear_time + offset) % cycle_time) / cycle_time
                    
                    # Tear geometry
                    tear_x = int(ex + (cur_w * 0.2 if is_right_eye else -cur_w * 0.2))
                    tear_start_y = int(ey + cur_h * 0.3)
                    tear_max_drop = 60
                    tear_y = int(tear_start_y + progress * tear_max_drop)
                    
                    # Tear size (starts small, drops, then shrinks out)
                    tear_rx = 5
                    tear_ry = 9
                    if progress < 0.2:
                        # Growing out of eye
                        alpha_tear = progress / 0.2
                    elif progress > 0.8:
                        # Fading at bottom
                        alpha_tear = (1.0 - progress) / 0.2
                    else:
                        alpha_tear = 1.0
                        
                    tear_rx = int(tear_rx * alpha_tear)
                    tear_ry = int(tear_ry * alpha_tear)
                    
                    if tear_rx > 0 and tear_ry > 0:
                        tear_color_bgr = (255, 220, 130)  # Pre-inverted light blue tear
                        # Rounded body
                        cv2.ellipse(img, (tear_x, tear_y), (tear_rx, tear_ry), 0, 0, 360, tear_color_bgr, -1)
                        # Pointed tip above (classic teardrop shape)
                        tip_y = tear_y - tear_ry
                        cv2.ellipse(img, (tear_x, tip_y),
                                    (max(1, tear_rx // 2), max(1, tear_ry // 2)),
                                    0, 0, 360, tear_color_bgr, -1)

                # === Upper eyelid (curved) ===
                if lid_top > 0.01 or abs(p.brow_angle) > 0.1:
                    # The upper eyelid is a filled region from the top of the eye
                    # down to a curved line. More lid_top = line is lower = more closed.
                    lid_drop = cur_h * lid_top  # How far down the lid comes
                    tilt = p.brow_angle if not is_right_eye else -p.brow_angle

                    # Reference line: top of eye is ey - ax_h
                    lid_y_center = int((ey - ax_h) + lid_drop + cur_h * 0.08)

                    # Create curved lid using an arc polygon
                    margin = int(base_eye_w * 0.6)
                    left_x = ex - margin
                    right_x = ex + margin

                    # Tilt the lid line
                    m = math.tan(math.radians(tilt))
                    y_left = int(lid_y_center + m * (left_x - ex))
                    y_right = int(lid_y_center + m * (right_x - ex))

                    # Build polygon: rectangle from top of screen to the lid line
                    pts = np.array([
                        [left_x, 0],
                        [right_x, 0],
                        [right_x, y_right],
                        [ex, lid_y_center + int(lid_drop * 0.15)],  # Slight curve
                        [left_x, y_left]
                    ], np.int32)
                    cv2.fillPoly(img, [pts], bg_bgr)

                # === Lower eyelid (curved) ===
                if lid_bot > 0.01:
                    lid_rise = cur_h * lid_bot

                    # Bottom of eye is ey + ax_h
                    lid_y_center = int((ey + ax_h) - lid_rise - cur_h * 0.05)

                    margin = int(base_eye_w * 0.5)
                    left_x = ex - margin
                    right_x = ex + margin

                    # Build polygon from lid line to bottom of screen
                    pts = np.array([
                        [left_x, lid_y_center],
                        [ex, lid_y_center - int(lid_rise * 0.1)],  # Slight curve
                        [right_x, lid_y_center],
                        [right_x, self.height],
                        [left_x, self.height]
                    ], np.int32)
                    cv2.fillPoly(img, [pts], bg_bgr)

        # Draw both eyes
        left_offset = -(eye_spacing + cur_w / 2)
        right_offset = (eye_spacing + cur_w / 2)
        draw_eye(left_offset, is_right_eye=False)
        draw_eye(right_offset, is_right_eye=True)

        # === Draw blush cheeks (for BLUSH emotion, drawn after eyes over the cheek area) ===
        if self.current_params.is_blushing:
            ax_h = int(cur_h / 2)
            left_ex = int(center_x + left_offset)
            right_ex = int(center_x + right_offset)
            cheek_y = int(center_y + ax_h + 30)   # Lower, below the eye
            cheek_rx, cheek_ry = 30, 20            # Wide flat ellipse

            # Pink color: (150, 50, 200) pre-inverted -> (105, 205, 55) after inversion
            blush_color = (150, 50, 200)
            alpha = 0.65 * min(1.0, self.current_intensity * 2)

            overlay = img.copy()
            cv2.ellipse(overlay, (left_ex, cheek_y), (cheek_rx, cheek_ry), 0, 0, 360, blush_color, -1)
            cv2.ellipse(overlay, (right_ex, cheek_y), (cheek_rx, cheek_ry), 0, 0, 360, blush_color, -1)
            cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

        # === Draw excitement sparkles (drawn after eyes) ===
        if self.current_params.is_excited:
            # Two sparkles per eye, alternating phase so they pulse offset from each other
            # Sparkle positions: above-outer and below-outer each eye
            left_ex  = int(center_x + left_offset)
            right_ex = int(center_x + right_offset)
            ax_h = int(cur_h / 2)
            ax_w = int(cur_w / 2)

            sparkle_cycle = 0.6  # seconds per pulse
            t_sp = self.current_sparkle_time

            def draw_star(cx, cy, outer_r, inner_r, color_bgr):
                """Draw a 4-pointed star centred at (cx, cy)."""
                pts = []
                for k in range(8):
                    angle_rad = math.pi / 4 * k - math.pi / 4
                    r = outer_r if k % 2 == 0 else inner_r
                    pts.append([int(cx + r * math.cos(angle_rad)),
                                 int(cy + r * math.sin(angle_rad))])
                star_pts = np.array(pts, np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(img, [star_pts], color_bgr)

            # Phase A: pulses in sync with sparkle_cycle
            # Phase B: offset by half a cycle
            phase_a = (math.sin(2 * math.pi * t_sp / sparkle_cycle) + 1) / 2  # 0→1 smoothly
            phase_b = (math.sin(2 * math.pi * t_sp / sparkle_cycle + math.pi) + 1) / 2

            max_outer = 14
            min_outer = 5

            # Pre-inverted bright warm yellow — renders as vivid yellow on display
            sparkle_color = (0, 25, 220)

            # Left eye: sparkle above-left and below-right
            r_a = int(min_outer + (max_outer - min_outer) * phase_a)
            r_b = int(min_outer + (max_outer - min_outer) * phase_b)
            if r_a >= 3:
                draw_star(left_ex - ax_w - 10, center_y - ax_h, r_a, r_a // 2, sparkle_color)
            if r_b >= 3:
                draw_star(left_ex + ax_w + 10, center_y + ax_h // 2, r_b, r_b // 2, sparkle_color)

            # Right eye: opposite phase to feel more dynamic
            if r_b >= 3:
                draw_star(right_ex + ax_w + 10, center_y - ax_h, r_b, r_b // 2, sparkle_color)
            if r_a >= 3:
                draw_star(right_ex - ax_w - 10, center_y + ax_h // 2, r_a, r_a // 2, sparkle_color)

        # === Draw dizzy wavy lines (for DIZZY emotion) ===
        if self.current_params.is_dizzy:
            wave_color = (p.color[2], p.color[1], p.color[0])
            amplitude  = 6
            freq_rad   = 4.0 * math.pi   # 2 full waves across the width
            for line_i in range(2):
                y_base = int(center_y + cur_h * 0.72 + line_i * 16)
                pts = []
                x_start = int(center_x - cur_w * 1.1)
                x_end   = int(center_x + cur_w * 1.1)
                for px_x in range(x_start, x_end, 3):
                    t_w = (px_x - x_start) / max(1, x_end - x_start)
                    px_y = int(y_base + amplitude * math.sin(freq_rad * t_w))
                    pts.append([px_x, px_y])
                if len(pts) > 1:
                    pts_arr = np.array(pts, np.int32).reshape((-1, 1, 2))
                    cv2.polylines(img, [pts_arr], False, wave_color, 3, cv2.LINE_AA)

        # === Draw open round mouth (for XEYES emotion — enlarged to balance with smaller X) ===
        if self.current_params.is_xeyed:
            mouth_color = (p.color[2], p.color[1], p.color[0])
            mouth_cx = center_x
            mouth_cy = int(center_y + cur_h * 0.72)
            mouth_rx  = int(cur_w * 0.35)
            mouth_ry  = int(cur_h * 0.15)
            cv2.ellipse(img, (mouth_cx, mouth_cy), (mouth_rx, mouth_ry),
                        0, 0, 360, mouth_color, -1)

        # === Draw smirk side-mouth (for SMIRK emotion) ===
        if self.current_params.is_smirking:
            mouth_color = (p.color[2], p.color[1], p.color[0])
            # Asymmetric curve: starts flat on the left, rises on the right
            mouth_y_base = int(center_y + cur_h * 0.88)
            mouth_left_x  = int(center_x - cur_w * 0.5)
            mouth_right_x = int(center_x + cur_w * 0.6)
            pts = []
            for si in range(40):
                frac = si / 39.0
                mx = int(mouth_left_x + (mouth_right_x - mouth_left_x) * frac)
                # Quadratic rise towards the right side
                rise = frac * frac * 25  # Stronger curve on right
                my = int(mouth_y_base - rise)
                pts.append([mx, my])
            if len(pts) > 1:
                pts_arr = np.array(pts, np.int32).reshape((-1, 1, 2))
                cv2.polylines(img, [pts_arr], False, mouth_color, 4, cv2.LINE_AA)

        # === Draw tongue (for confused animation, drawn after eyes) ===
        if self.current_params.is_tongue_out:
            # Tongue wiggles left-right using a sine wave on the angle
            tongue_cx = center_x - 5
            tongue_cy = center_y + int(cur_h * 0.95)
            tongue_rx, tongue_ry = 14, 30
            # Oscillate angle between -30 and +30 degrees
            tongue_angle = math.sin(self.current_tongue_time * 3.0) * 30.0
            tongue_color_bgr = (255, 255, 150)

            # Draw the tongue oval
            cv2.ellipse(img, (tongue_cx, tongue_cy), (tongue_rx, tongue_ry),
                        int(tongue_angle), 0, 360, tongue_color_bgr, -1)
            # Mask the top half to give a flat edge
            cv2.rectangle(img, (tongue_cx - tongue_rx - 10, 0),
                          (tongue_cx + tongue_rx + 10, tongue_cy - 4), BG_COLOR, -1)

        # === Draw sweat drop (for tired animation, on forehead above eyes) ===
        if self.current_params.is_sweating:
            cycle_time = 2.0
            progress = (self.current_sweat_time % cycle_time) / cycle_time

            # Sweat drop slides from forehead (top) downward
            drop_x = center_x + int(eye_spacing + cur_w + 10)  # Outer side of right eye
            drop_start_y = int(center_y - cur_h * 0.6)  # Above the eye
            drop_end_y = int(center_y - cur_h * 0.1)    # Just above the eye
            drop_y = int(drop_start_y + progress * (drop_end_y - drop_start_y))

            # Teardrop shape: small circle + tiny pointed trail above it
            drop_rx = 7
            drop_ry = 10

            # Fade in/out at extremes
            if progress < 0.15:
                alpha_drop = progress / 0.15
            elif progress > 0.85:
                alpha_drop = (1.0 - progress) / 0.15
            else:
                alpha_drop = 1.0

            drop_rx = max(1, int(drop_rx * alpha_drop))
            drop_ry = max(1, int(drop_ry * alpha_drop))

            # Pre-inverted light blue sweat color (same as tears)
            sweat_color_bgr = (255, 220, 130)
            cv2.ellipse(img, (drop_x, drop_y), (drop_rx, drop_ry), 0, 0, 360, sweat_color_bgr, -1)
            # Pointed tip above (upward triangle approximated by a smaller ellipse slightly above)
            tip_y = drop_y - drop_ry
            cv2.ellipse(img, (drop_x, tip_y), (max(1, drop_rx // 2), max(1, drop_ry // 2)), 0, 0, 360, sweat_color_bgr, -1)

        # Invert colors (white background with dark features)
        cv2.bitwise_not(img, dst=img)

        # Rotate to portrait: landscape 320×240 → portrait 240×320
        img_portrait = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

        # Horizontal flip to correct mirroring
        cv2.flip(img_portrait, 1, dst=img_portrait)

        # RGB565 conversion (swap R/B for correct ST7789 color output)
        r = img_portrait[:, :, 0].astype(np.uint16)  # BGR channel 0 = Blue → R bits
        g = img_portrait[:, :, 1].astype(np.uint16)
        b = img_portrait[:, :, 2].astype(np.uint16)  # BGR channel 2 = Red → B bits

        np.multiply(r & 0xF8, 256, out=self._rgb565)
        self._rgb565 |= ((g & 0xFC) << 3)
        self._rgb565 |= (b >> 3)
        self._rgb565.byteswap(inplace=True)

        return self._rgb565

    # --- Legacy render (PIL image, for fallback) ---
    def render(self):
        """Render to PIL Image (legacy path)."""
        from PIL import Image
        img = self._frame.copy()
        img[:] = 0
        # ... simplified, use render_to_rgb565 for optimized path
        return Image.fromarray(cv2.bitwise_not(img))