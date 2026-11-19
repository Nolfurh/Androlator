"""APK and app management for Androlator"""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from androlator.config import Config

console = Console()


class AppManager:
    """Manages Android app installation and listing."""

    def __init__(self, config: Config):
        self.config = config
        self._serial = f"localhost:{config.container.adb_port}"

    def _adb(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        """Run an ADB command."""
        cmd = ["adb", "-s", self._serial, *args]
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )

    def install(self, apk_path: str) -> bool:
        """Install an APK file."""
        path = Path(apk_path)
        if not path.exists():
            console.print(f"[red]APK file not found:[/red] {apk_path}")
            return False

        if path.suffix.lower() != ".apk":
            console.print(f"[yellow]Warning: file does not have .apk extension[/yellow]")

        console.print(f"Installing [bold]{path.name}[/bold]")
        try:
            result = self._adb("install", "-r", str(path), timeout=120)
            if "success" in result.stdout.lower():
                console.print(f"[green]Successfully installed {path.name}[/green]")
                return True
            else:
                console.print(
                    f"[red]Installation failed:[/red]\n"
                    f"{result.stdout.strip()}\n{result.stderr.strip()}"
                )
                return False
        except subprocess.TimeoutExpired:
            console.print("[red]Installation timed out (120s).[/red]")
            return False

    def uninstall(self, package: str) -> bool:
        """Uninstall an app by package name."""
        console.print(f"Uninstalling [bold]{package}[/bold]")
        try:
            result = self._adb("uninstall", package)
            if "success" in result.stdout.lower():
                console.print(f"[green]Uninstalled {package}[/green]")
                return True
            else:
                console.print(f"[red]Failed:[/red] {result.stdout.strip()}")
                return False
        except subprocess.TimeoutExpired:
            console.print("[red]Uninstall timed out.[/red]")
            return False

    def list_packages(self, third_party_only: bool = True) -> list[str]:
        """List installed packages."""
        try:
            args = ["shell", "pm", "list", "packages"]
            if third_party_only:
                args.append("-3")
            result = self._adb(*args)
            packages = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("package:"):
                    packages.append(line[len("package:"):])
            return sorted(packages)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def print_packages(self, third_party_only: bool = True) -> None:
        """Print installed packages in a nice table."""
        packages = self.list_packages(third_party_only)

        if not packages:
            label = "third-party " if third_party_only else ""
            console.print(f"[yellow]No {label}packages installed.[/yellow]")
            return

        table = Table(title="Installed Apps")
        table.add_column("#", style="dim", justify="right")
        table.add_column("Package Name", style="bold")

        for i, pkg in enumerate(packages, 1):
            table.add_row(str(i), pkg)

        console.print(table)

    def launch(self, package: str) -> bool:
        """Launch an app by package name."""
        try:
            resolve = self._adb("shell", "cmd", "package", "resolve-activity", "--brief", package)
            lines = [line.strip() for line in resolve.stdout.strip().splitlines() if line.strip()]

            activity = None
            if lines and "no activity found" not in resolve.stdout.lower():
                candidate = lines[-1]
                if "/" in candidate:
                    activity = candidate

            if activity:
                result = self._adb("shell", "am", "start", "-n", activity)
                if result.returncode == 0 and "error:" not in result.stdout.lower():
                    console.print(f"[green]Launched {package} ({activity})[/green]")
                    return True


            result = self._adb(
                "shell", "monkey",
                "--pct-syskeys", "0",
                "-p", package,
                "-c", "android.intent.category.LAUNCHER",
                "1"
            )
            if result.returncode != 0:
                if "no activities found" in result.stdout.lower():
                    console.print(f"[red]No launchable activity found for {package}[/red]")
                else:
                    err = result.stderr.strip() or result.stdout.strip()
                    console.print(f"[red]Failed to launch {package}:[/red]\n{err}")
                return False

            console.print(f"[green]Launched {package}[/green]")
            return True
        except subprocess.TimeoutExpired:
            console.print("[red]Launch timed out.[/red]")
            return False

    def shell(self) -> None:
        """Open an interactive ADB shell."""
        console.print(f"[dim]Connecting to localhost:{self.config.container.adb_port}[/dim]")
        subprocess.run(["adb", "-s", self._serial, "shell"])
