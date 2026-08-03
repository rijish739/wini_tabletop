import base64
import os
import sys
import paramiko

host = os.getenv("PI_HOST", "winipi5.local")
user = os.getenv("PI_USER", "winipi5")
password = os.getenv("PI_PASS", "roavai")

local_path = r"d:\cloud CLI\cloud_run_service\tutor_loop.py"
remote_path = "/home/winipi5/cloud_tutor/cloud-CLI/tutor_loop.py"

print(f"Connecting to {user}@{host}...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, username=user, password=password, timeout=10)

with open(local_path, "rb") as f:
    data = f.read()

print(f"File size: {len(data)} bytes. Clearing remote file...")
ssh.exec_command(f"rm -f {remote_path} && touch {remote_path}")

chunk_size = 30000
for i in range(0, len(data), chunk_size):
    chunk = data[i:i+chunk_size]
    b64 = base64.b64encode(chunk).decode("ascii")
    cmd = f"echo '{b64}' | base64 -d >> {remote_path}"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    stdout.read()
    print(f"Pushed chunk {i//chunk_size + 1}/{(len(data)+chunk_size-1)//chunk_size}")

ssh.close()
print("Push complete!")
