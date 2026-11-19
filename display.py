"""Scrcpy display management"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from rich.console import Console

from androlator.config import Config

console = Console()


class DisplayManager:
    """Manages scrcpy process for displaying the Android screen."""

    def __init__(self, config: Config):
        self.config = config
        self.dc = config.display
        self.cc = config.container
        self._process: subprocess.Popen | None = None
        self._pid_file = Path.home() / ".config" / "androlator" / "scrcpy.pid"

    def _build_command(self) -> list[str]:
        """Build the scrcpy command line."""
        serial = f"localhost:{self.cc.adb_port}"

        cmd = [
            "scrcpy",
            "--serial", serial,
            "--video-codec", self.dc.video_codec,
            "--max-fps", str(self.dc.max_fps),
            "--video-bit-rate", self.dc.video_bitrate,
            "--window-title", self.dc.window_title,
            "--keyboard", self.dc.keyboard_mode,
            "--mouse", self.dc.mouse_mode,
        ]

        if getattr(self.dc, "hwdec", None):
            cmd.extend(["--hwdec", self.dc.hwdec])

        buffer_val = getattr(self.dc, "video_buffer", None)
        if buffer_val is None:
            buffer_val = getattr(self.dc, "display_buffer", 0)
        if buffer_val > 0:
            cmd.extend(["--video-buffer", str(buffer_val)])

        if self.dc.no_audio:
            cmd.append("--no-audio")

        if self.dc.fullscreen:
            cmd.append("--fullscreen")

        return cmd

    def start(self, foreground: bool = False) -> bool:
        """Start scrcpy to display the Android screen.

        Args:
            foreground: If True, scrcpy runs in the foreground.
                       If False, scrcpy runs in the background.
        """
        if self.is_running():
            console.print("[yellow]Scrcpy is already running.[/yellow]")
            return True

        cmd = self._build_command()
        console.print(f"Launching scrcpy: [dim]{' '.join(cmd)}[/dim]")

        try:
            if foreground:
                result = subprocess.run(cmd)
                return result.returncode == 0
            else:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                self._pid_file.parent.mkdir(parents=True, exist_ok=True)
                self._pid_file.write_text(str(self._process.pid))

                # Additional time for connection
                time.sleep(1)

                if self._process.poll() is not None:
                    stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                    console.print(
                        f"[red]Scrcpy exited immediately:[/red]\n{stderr}"
                    )
                    return False

                console.print(
                    f"[green]Scrcpy started (PID {self._process.pid}).[/green]"
                )
                return True

        except FileNotFoundError:
            console.print(
                "[red]scrcpy not found.[/red] "
                "Install with: [bold]sudo pacman -S scrcpy[/bold]"
            )
            return False

    def stop(self) -> None:
        """Stop the scrcpy process."""
        pid = self._get_pid()
        if pid is None:
            console.print("[yellow]No scrcpy process found.[/yellow]")
            return

        try:
            os.kill(pid, signal.SIGTERM)
            console.print(f"[green]Scrcpy stopped (PID {pid}).[/green]")
        except ProcessLookupError:
            console.print("[yellow]Scrcpy process already terminated.[/yellow]")

        self._cleanup_pid()

    def is_running(self) -> bool:
        """Check if scrcpy is currently running."""
        if self._process is not None and self._process.poll() is None:
            return True

        # Check PID file
        pid = self._get_pid()
        if pid is not None:
            try:
                os.kill(pid, 0)  # Signal 0 = check if process exists
                return True
            except (ProcessLookupError, PermissionError):
                self._cleanup_pid()

        return False

    def _get_pid(self) -> int | None:
        """Get the scrcpy PID from the PID file."""
        if self._process is not None and self._process.poll() is None:
            return self._process.pid

        if self._pid_file.exists():
            try:
                return int(self._pid_file.read_text().strip())
            except (ValueError, OSError):
                pass

        return None

    def _cleanup_pid(self) -> None:
        """Remove the PID file."""
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError:
            pass
