import subprocess
import os

FILES_TO_DEPLOY = [
    "test_touch_audio.py",
    "touch_demo.py",
    "wini_client/sound_bank.py",
    "wini_client/audio_manager.py",
    "wini_client/client.py",
    "wini_platform/touch/gpio_touch.py",
    "wini_platform/touch_gestures.py",
    "wini_platform/emotion_engine.py",
    "wini_platform/supervisor.py",
]

PLINK_PATH = r"F:\ROS_testing\plink"
HOST = "winipi5@winipi5.local"
PASSWORD = "roavai"
HOST_KEY = "SHA256:9Cm9oVUWxYqNvzhp5f1rmkYYRtm0YFA/wE6aJVbXKH0"

def deploy():
    for rel_path in FILES_TO_DEPLOY:
        local_path = os.path.join(os.getcwd(), rel_path)
        with open(local_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        remote_path = f"~/cloud_tutor/cloud-CLI/{rel_path.replace(os.sep, '/')}"
        print(f"Deploying {rel_path} to {remote_path}...")
        
        # Write via plink
        cmd = [
            PLINK_PATH,
            "-batch",
            "-ssh",
            "-hostkey", HOST_KEY,
            "-pw", PASSWORD,
            HOST,
            f"cat > {remote_path}"
        ]
        
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        stdout, stderr = proc.communicate(input=content)
        
        if proc.returncode != 0:
            print(f"FAILED to deploy {rel_path}: {stderr}")
        else:
            print(f"Successfully deployed {rel_path}")

if __name__ == "__main__":
    deploy()
