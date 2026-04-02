"""
Med-Audit Linux 离线包下载工具
同时下载 cp39 和 cp311 的 wheel，兼容服务器 Python 3.9 和 3.11
"""
import subprocess
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == 'scripts' else SCRIPT_DIR
PACKAGES_DIR = os.path.join(BACKEND_DIR, "packages")
REQ_FILE = os.path.join(BACKEND_DIR, "requirements.linux.txt")

os.makedirs(PACKAGES_DIR, exist_ok=True)

def pip_download(extra_args, req_file=None, packages=None):
    cmd = [sys.executable, "-m", "pip", "download",
           "--dest", PACKAGES_DIR] + extra_args
    if req_file:
        cmd += ["-r", req_file]
    if packages:
        cmd += packages
    result = subprocess.run(cmd)
    return result.returncode == 0

print("[INFO] Step 1: Downloading pure-Python wheels (platform-independent)...")
pip_download(
    ["--platform", "manylinux2014_x86_64",
     "--python-version", "39",
     "--only-binary", ":all:"],
    req_file=REQ_FILE
)

print("\n[INFO] Step 2: Downloading cp39 native wheels (Python 3.9 / OpenEuler)...")
pip_download(
    ["--platform", "manylinux2014_x86_64",
     "--python-version", "39",
     "--abi", "cp39",
     "--only-binary", ":all:"],
    req_file=REQ_FILE
)

print("\n[INFO] Step 3: Downloading cp311 native wheels (Python 3.11 fallback)...")
pip_download(
    ["--platform", "manylinux2014_x86_64",
     "--python-version", "311",
     "--abi", "cp311",
     "--only-binary", ":all:"],
    req_file=REQ_FILE
)

print("\n[INFO] Step 4: Downloading abi3 wheels (compatible with cp3x)...")
pip_download(
    ["--platform", "manylinux2014_x86_64",
     "--python-version", "39",
     "--abi", "abi3",
     "--only-binary", ":all:"],
    packages=["cryptography>=42.0.0", "bcrypt==4.0.1", "cffi"]
)

# 统计下载结果
wheels = [f for f in os.listdir(PACKAGES_DIR) if f.endswith('.whl')]
print(f"\n[OK] Total {len(wheels)} wheel files in {PACKAGES_DIR}")
for w in sorted(wheels):
    print(f"  {w}")

print("\n[DONE] Download complete. Both cp39 and cp311 wheels available.")
sys.exit(0)
