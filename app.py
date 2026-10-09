from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
DATA_FILE = APP_DIR / "tasks.json"
BACKUP_FILE = APP_DIR / "tasks.json.bak"
INSTANCE_FILE = APP_DIR / ".notestrata-port"
MAX_BODY_BYTES = 5 * 1024 * 1024
_MUTEX_HANDLE: int | None = None


def open_app_window(address: str) -> None:
    """Open the interface in the user's default browser."""
    webbrowser.open(address)


def acquire_instance_lock() -> bool:
    """Allow one NoteStrata server per application directory on Windows."""
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True

    digest = hashlib.sha256(str(APP_DIR).casefold().encode("utf-8")).hexdigest()[:20]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, f"Local\\NoteStrata-{digest}")
    if not handle:
        return True
    _MUTEX_HANDLE = int(handle)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def release_instance_lock() -> None:
    global _MUTEX_HANDLE
    if os.name == "nt" and _MUTEX_HANDLE:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_MUTEX_HANDLE))
        _MUTEX_HANDLE = None


def open_existing_instance() -> None:
    """Open the server URL written by the already-running instance."""
    for _ in range(20):
        try:
            port = int(INSTANCE_FILE.read_text(encoding="ascii").strip())
            address = f"http://127.0.0.1:{port}/"
            with urlopen(f"{address}api/tasks", timeout=0.5) as response:
                if response.status == 200:
                    open_app_window(address)
                    return
        except (OSError, ValueError):
            time.sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalWorkList/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/tasks":
            if DATA_FILE.exists():
                try:
                    body = DATA_FILE.read_bytes()
                    json.loads(body)
                except (OSError, json.JSONDecodeError):
                    self.send_bytes(500, "application/json; charset=utf-8", b'{"error":"Unable to read tasks.json"}')
                    return
            else:
                body = b'{"tasks": []}'
            self.send_bytes(200, "application/json; charset=utf-8", body)
            return

        if path in ("/", "/index.html"):
            try:
                body = (RESOURCE_DIR / "index.html").read_bytes()
            except OSError:
                self.send_bytes(500, "text/plain; charset=utf-8", "找不到界面文件 index.html".encode())
                return
            self.send_bytes(200, "text/html; charset=utf-8", body)
            return

        self.send_bytes(404, "text/plain; charset=utf-8", "Not found".encode())

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/tasks":
            self.send_bytes(404, "application/json; charset=utf-8", b'{"error":"Not found"}')
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0 or size > MAX_BODY_BYTES:
                raise ValueError("数据大小超出限制")
            body = self.rfile.read(size)
            data = json.loads(body)
            if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
                raise ValueError("数据格式不正确")

            temporary = APP_DIR / "tasks.json.tmp"
            encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            temporary.write_bytes(encoded)
            if DATA_FILE.exists():
                shutil.copy2(DATA_FILE, BACKUP_FILE)
            temporary.replace(DATA_FILE)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            message = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_bytes(400, "application/json; charset=utf-8", message)
            return

        self.send_bytes(200, "application/json; charset=utf-8", b'{"ok":true}')


def main() -> None:
    if not acquire_instance_lock():
        open_existing_instance()
        release_instance_lock()
        return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    address = f"http://127.0.0.1:{server.server_port}/"
    INSTANCE_FILE.write_text(str(server.server_port), encoding="ascii")
    print("工作清单已启动。关闭此窗口即可退出。")
    print(f"本机地址：{address}")
    if "--no-browser" not in sys.argv and os.environ.get("NOTESTRATA_NO_BROWSER") != "1":
        threading.Timer(0.8, open_app_window, args=(address,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            INSTANCE_FILE.unlink(missing_ok=True)
        finally:
            release_instance_lock()
        print("工作清单已关闭。")


if __name__ == "__main__":
    main()
