"""Wini display node.

Middleware between ROS 2 and the display driver. Subscribes to face/gaze/
emotion topics and an image override topic, holds the resulting state, and
orchestrates the face renderer + display driver. No graphics primitives or
SPI work live here — those belong to wini_face.py and wini_display_driver.py
respectively.

Default state renders the face. To override the display with a custom image,
publish an rgb8 sensor_msgs/Image of size CANVAS_W × CANVAS_H (landscape) to
/wini/display/image. As long as fresh images keep arriving within
IMAGE_TIMEOUT_S, the image is shown; otherwise the node falls back to the
face.
"""

import threading
import time

import numpy as np
import rclpy
from geometry_msgs.msg import Point
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from display_controll.wini_face import WiniFace
from display_controll.wini_display_driver import (
    WiniDisplayDriver, CANVAS_W, CANVAS_H,
)


IMAGE_TIMEOUT_S = 0.5            # revert to face if no image within this window
FRAME_PERIOD_S  = 1.0 / 30.0     # main render loop target (30 fps)


class WiniDisplayNode(Node):
    def __init__(self, state_ref):
        super().__init__('wini_display_node')
        self.state = state_ref

        self.create_subscription(Point,  '/wini/eyes_target',
                                 self._cb_gaze,    10)
        self.create_subscription(String, '/wini/emotion',
                                 self._cb_emotion, 10)
        self.create_subscription(Image,  '/wini/display/image',
                                 self._cb_image,   10)

    def _cb_gaze(self, msg: Point):
        z = msg.z + 0.001
        self.state['gaze_x'] = float(np.clip(msg.x / z * 1.5, -1.0, 1.0))
        self.state['gaze_y'] = float(np.clip(msg.y / z * 1.5, -1.0, 1.0))
        self.state['gaze_z'] = float(np.clip(0.8 - msg.z * 2,  0.1, 1.0))

    def _cb_emotion(self, msg: String):
        parts = msg.data.replace(':', ' ').replace(',', ' ').split()
        if not parts:
            return
        self.state['emotion'] = parts[0].strip().upper()
        if len(parts) > 1:
            try:
                self.state['intensity'] = int(parts[1].strip())
            except ValueError:
                pass

    def _cb_image(self, msg: Image):
        if msg.encoding != 'rgb8':
            self.get_logger().warn(
                f'Expected encoding rgb8, got {msg.encoding!r}; ignoring.'
            )
            return
        if (msg.height, msg.width) != (CANVAS_H, CANVAS_W):
            self.get_logger().warn(
                f'Expected {CANVAS_W}x{CANVAS_H} (landscape), '
                f'got {msg.width}x{msg.height}; ignoring.'
            )
            return
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(
            (msg.height, msg.width, 3)
        )
        self.state['image_rgb']  = arr.copy()
        self.state['image_time'] = time.time()


def main():
    rclpy.init()
    driver = WiniDisplayDriver()
    face   = WiniFace(width=CANVAS_W, height=CANVAS_H)

    face.set_style(
        style_name='linear',
        color1=(255, 255, 255),
        color2=(255, 255, 255),
        size_x=170,
        size_y=190,
        separation=40,
        pos_y=-50,
        pupil_size=0.8,
        iris_size=0.9,
        iris_style='radial',          # NEW
        iris_color2=(250, 244, 187),   # outer cream
        iris_color=(240, 234, 177),    # inner dark amber
        gaze_offset_y=0.7,
        blink_rate=1.0,
    )


    state = {
        'emotion':    'neutral',
        'intensity':  15,
        'gaze_x':     0.0,
        'gaze_y':     0.0,
        'gaze_z':     0.4,
        'image_rgb':  None,
        'image_time': 0.0,
    }

    face.set_emotion(state['emotion'], state['intensity'])
    face.set_gaze(state['gaze_x'], state['gaze_y'], state['gaze_z'])

    ros_node   = WiniDisplayNode(state)
    ros_thread = threading.Thread(target=rclpy.spin, args=(ros_node,), daemon=True)
    ros_thread.start()

    try:
        last_frame_time = time.time()
        while True:
            now = time.time()

            img = state['image_rgb']
            if img is not None and (now - state['image_time']) < IMAGE_TIMEOUT_S:
                # Image override — push the latest image as-is.
                driver.push_landscape(img)
            else:
                # Default — render face. Blink scheduling is internal to face.
                face.set_emotion(state['emotion'], state['intensity'])
                face.set_gaze(state['gaze_x'], state['gaze_y'], state['gaze_z'])
                face.update()

                frame = face.render()
                driver.push_landscape(frame)

            elapsed = time.time() - last_frame_time
            sleep_time = FRAME_PERIOD_S - elapsed
            if sleep_time > 0.001:
                time.sleep(sleep_time)
            last_frame_time = time.time()

    except KeyboardInterrupt:
        pass
    finally:
        try:
            ros_node.destroy_node()
        except Exception:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
