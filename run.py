"""Wermes Client — 一键启动"""
import subprocess
import sys
import time
from pathlib import Path

def main():
    print("Wermes Client 启动中...")
    print(f"地址: http://127.0.0.1:7861")
    print()

    server = Path(__file__).parent / "server.py"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", "7861",
         "--log-level", "warning"],
        cwd=str(Path(__file__).parent),
    )
    time.sleep(1)
    print("✅ 服务已启动，浏览器打开 http://127.0.0.1:7861")
    print("按 Ctrl+C 停止")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\n已停止")

if __name__ == "__main__":
    main()
