"""Receiving files shared from Android"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from rich.console import Console

from androlator.config import Config

console = Console()

DEFAULT_PORT = 7381
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads"
DEFAULT_PID_FILE = Path.home() / ".config" / "androlator" / "receiver.pid"
DEFAULT_APK_PATH = Path(__file__).resolve().parent / "assets" / "androlator-share.apk"
STAGING_DIR = Path("/tmp/androlator_staging")


def ask_save_path(filename: str, default_dir: Path) -> Path | None:
    """Prompt user via GUI (yad / zenity) where to save the file on the host.

    Returns the chosen Path, or None if user cancelled.
    """
    default_target = default_dir / filename
    env = os.environ.copy()
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"

    # Try yad
    yad_bin = shutil.which("yad")
    if yad_bin:
        cmd = [
            yad_bin,
            "--file",
            "--save",
            "--confirm-overwrite",
            f"--filename={str(default_target)}",
            f"--title=Save file ({filename})",
            "--center",
            "--width=680",
            "--height=480",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if res.returncode == 0 and res.stdout.strip():
                path_str = res.stdout.strip().split("|")[0].strip()
                if path_str:
                    return Path(path_str)
            return None
        except Exception as e:
            console.print(f"[yellow]yad file dialog error: {e}[/yellow]")

    # Try zenity
    zenity_bin = shutil.which("zenity")
    if zenity_bin:
        cmd = [
            zenity_bin,
            "--file-selection",
            "--save",
            "--confirm-overwrite",
            f"--filename={str(default_target)}",
            f"--title=Save file ({filename})",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if res.returncode == 0 and res.stdout.strip():
                return Path(res.stdout.strip())
            return None
        except Exception as e:
            console.print(f"[yellow]zenity file dialog error: {e}[/yellow]")

    # If no GUI dialog tool found, save to default directory
    console.print("[yellow]No GUI file chooser (yad/zenity) found — saving to default directory.[/yellow]")
    return default_target


class FileUploadHandler(BaseHTTPRequestHandler):
    """HTTP handler for receiving files uploaded from Android."""

    download_dir: Path = DEFAULT_DOWNLOAD_DIR

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default stdout access log."""
        pass

    def do_POST(self) -> None:
        """Handle incoming file upload."""
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/upload":
            self.send_response(404)
            self.end_headers()
            return

        # Extract filename from query parameter or header
        query = urllib.parse.parse_qs(parsed.query)
        filename = query.get("filename", [None])[0]

        if not filename:
            filename = self.headers.get("X-Filename", "received_file")

        filename = os.path.basename(urllib.parse.unquote(filename))
        if not filename:
            filename = "received_file"

        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        staging_file = STAGING_DIR / f"{time.time_ns()}_{filename}"

        content_length = int(self.headers.get("Content-Length", 0))
        try:
            with open(staging_file, "wb") as f:
                remaining = content_length
                chunk_size = 65536
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, chunk_size))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")

            threading.Thread(
                target=self._prompt_and_save,
                args=(staging_file, filename, self.download_dir),
                daemon=True,
            ).start()

        except Exception as e:
            console.print(f"[red]Error receiving uploaded file:[/red] {e}")
            if staging_file.exists():
                staging_file.unlink(missing_ok=True)
            self.send_response(500)
            self.end_headers()

    @classmethod
    def _prompt_and_save(cls, staging_file: Path, filename: str, default_dir: Path) -> None:
        """Prompt user where to save the file and move it from staging."""
        target_path = ask_save_path(filename, default_dir)

        if target_path is None:
            # User cancelled the save dialog
            staging_file.unlink(missing_ok=True)
            console.print(f"[yellow]Save cancelled for {filename}[/yellow]")
            cls._notify("Save cancelled", f"File {filename} not saved")
            return

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging_file), str(target_path))
            console.print(
                f"[green]Saved from Android:[/green] [bold]{target_path.name}[/bold] -> {target_path}"
            )
            cls._notify(target_path.name, str(target_path))
        except Exception as e:
            console.print(f"[red]Failed to move file to {target_path}:[/red] {e}")
            staging_file.unlink(missing_ok=True)

    @staticmethod
    def _notify(title: str, message: str) -> None:
        """Send desktop notification via notify-send."""
        env = os.environ.copy()
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        try:
            subprocess.run(
                [
                    "notify-send",
                    "-i", "document-save",
                    "Androlator",
                    f"{title}\n{message}",
                ],
                capture_output=True,
                timeout=3,
                env=env,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass


class ReceiverManager:
    """Manages the background HTTP receiver server and process lifecycle."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        download_dir: Path | None = None,
        pid_file: Path | None = None,
    ):
        self.port = port
        self.download_dir = download_dir or DEFAULT_DOWNLOAD_DIR
        self.pid_file = pid_file or DEFAULT_PID_FILE
        self._server: HTTPServer | None = None

    def run_server(self) -> None:
        """Run HTTP server in current thread (blocks)."""
        FileUploadHandler.download_dir = self.download_dir
        self._server = HTTPServer(("127.0.0.1", self.port), FileUploadHandler)
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if self._server:
                self._server.server_close()

    def is_running(self) -> bool:
        """Check if receiver daemon is currently running."""
        if not self.pid_file.exists():
            return False
        try:
            pid = int(self.pid_file.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, OSError):
            try:
                self.pid_file.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def start_daemon(self, config: Config | None = None) -> bool:
        """Start receiver daemon in a background process and configure adb reverse."""
        if self.is_running():
            return True

        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        log_file = self.pid_file.parent / "receiver.log"

        env = os.environ.copy()
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"

        cmd = [sys.executable, "-m", "androlator.receiver", "--port", str(self.port)]
        with open(log_file, "a") as f:
            proc = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )

        self.pid_file.write_text(str(proc.pid))
        time.sleep(0.3)

        # Configure adb reverse port forwarding
        adb_port = config.container.adb_port if config else 5555
        self._setup_adb_reverse(adb_port)
        return True

    def stop_daemon(self, config: Config | None = None) -> bool:
        """Stop receiver daemon and remove adb reverse port forwarding."""
        adb_port = config.container.adb_port if config else 5555
        self._remove_adb_reverse(adb_port)

        if not self.pid_file.exists():
            return True

        try:
            pid = int(self.pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.2)
            if self.is_running():
                os.kill(pid, signal.SIGKILL)
        except (ValueError, OSError):
            pass
        finally:
            try:
                self.pid_file.unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def _setup_adb_reverse(self, adb_port: int) -> None:
        """Configure adb reverse port forwarding."""
        try:
            subprocess.run(
                [
                    "adb",
                    "-s", f"localhost:{adb_port}",
                    "reverse",
                    f"tcp:{self.port}",
                    f"tcp:{self.port}",
                ],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def _remove_adb_reverse(self, adb_port: int) -> None:
        """Remove adb reverse port forwarding."""
        try:
            subprocess.run(
                [
                    "adb",
                    "-s", f"localhost:{adb_port}",
                    "reverse",
                    "--remove",
                    f"tcp:{self.port}",
                ],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    @staticmethod
    def ensure_share_app_installed(config: Config) -> bool:
        """Ensure the Androlator Share APK is installed in the Android container."""
        from androlator.apps import AppManager

        am = AppManager(config)
        packages = am.list_packages(third_party_only=False)
        if "com.androlator.share" in packages:
            return True

        apk_path = DEFAULT_APK_PATH
        if not apk_path.exists():
            console.print(f"[yellow]Share APK not found at {apk_path}[/yellow]")
            return False

        console.print("Installing [bold]Androlator Share[/bold] app in container")
        ok = am.install(str(apk_path))
        if ok:
            try:
                subprocess.run(
                    [
                        "adb",
                        "-s", f"localhost:{config.container.adb_port}",
                        "shell",
                        "appops",
                        "set",
                        "com.androlator.share",
                        "MANAGE_EXTERNAL_STORAGE",
                        "allow",
                    ],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass
        return ok


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Androlator File Receiver")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    args = parser.parse_args()

    manager = ReceiverManager(port=args.port)
    manager.run_server()
