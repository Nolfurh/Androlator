"""Docker container lifecycle management"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from androlator.config import Config

console = Console()


def _docker_cmd(config: Config) -> list[str]:
    """Return the base docker command, with sudo if configured."""
    if config.container.use_sudo:
        return ["sudo", "docker"]
    return ["docker"]


class ContainerManager:
    """Manages the Redroid Docker container lifecycle."""

    def __init__(self, config: Config):
        self.config = config
        self.cc = config.container

    def _run(
        self, *args: str, timeout: int = 30, check: bool = False
    ) -> subprocess.CompletedProcess:
        """Run a docker CLI command."""
        cmd = [*_docker_cmd(self.config), *args]
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )

    def _inspect(self) -> dict[str, Any] | None:
        """Inspect the container, returning parsed JSON or None."""
        result = self._run("inspect", self.cc.name)
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            return data[0] if data else None
        except (json.JSONDecodeError, IndexError):
            return None

    def get_status(self) -> str | None:
        """Get container status string, or None if it doesn't exist."""
        info = self._inspect()
        if info is None:
            return None
        return info.get("State", {}).get("Status")

    def is_running(self) -> bool:
        """Check if the container is running."""
        return self.get_status() == "running"

    def pull_image(self) -> None:
        """Pull the Redroid Docker image."""
        console.print(f"Pulling image [bold]{self.cc.image}[/bold]")
        cmd = [*_docker_cmd(self.config), "pull", self.cc.image]
        result = subprocess.run(cmd, timeout=600)
        if result.returncode != 0:
            console.print("[red]Failed to pull image.[/red]")
            raise SystemExit(1)
        console.print("[green]Image pulled successfully.[/green]")

    def image_exists(self) -> bool:
        """Check if the Redroid image is already pulled."""
        result = self._run("image", "inspect", self.cc.image)
        return result.returncode == 0

    def create_and_start(self) -> bool:
        """Create and start the Redroid container. Returns True on success."""
        status = self.get_status()

        if status == "running":
            console.print(
                f"[yellow]Container '{self.cc.name}' is already running.[/yellow]"
            )
            return True

        if status == "exited":
            console.print(f"Starting existing container '{self.cc.name}'")
            result = self._run("start", self.cc.name)
            if result.returncode == 0:
                console.print("[green]Container started.[/green]")
                return True
            console.print(f"[red]Failed to start:[/red] {result.stderr.strip()}")
            return False

        if status is not None:
            console.print(f"Removing container in state '{status}'")
            self._run("rm", "-f", self.cc.name)

        # Build docker run command
        gpu_node = self.cc.gpu_node
        cmd = [
            *_docker_cmd(self.config),
            "run", "-itd",
            "--name", self.cc.name,
            "--privileged",
            "-v", "/dev/binderfs:/dev/binderfs",
            "-p", f"{self.cc.adb_port}:5555",
            "--cpus", str(self.cc.cpus),
            "--memory", self.cc.memory,
        ]

        # GPU device passthrough
        if gpu_node and self.cc.gpu_mode == "host":
            cmd.extend(["--device", f"{gpu_node}:{gpu_node}"])

        # Persistent data volume
        if self.cc.data_dir:
            cmd.extend(["-v", f"{self.cc.data_dir}:/data"])

        # Image
        cmd.append(self.cc.image)

        # Redroid boot parameters (after image name)
        cmd.append(f"androidboot.redroid_gpu_mode={self.cc.gpu_mode}")
        if gpu_node and self.cc.gpu_mode == "host":
            cmd.append(f"androidboot.redroid_gpu_node={gpu_node}")

        console.print(f"Creating container [bold]{self.cc.name}[/bold]")
        console.print(f"  Image: {self.cc.image}")
        console.print(f"  GPU: {self.cc.gpu_mode} ({gpu_node or 'none'})")
        console.print(f"  ADB port: {self.cc.adb_port}")

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0:
            console.print(f"[red]Failed to create container:[/red] {result.stderr.strip()}")
            return False

        console.print(
            f"[green]Container '{self.cc.name}' created and started.[/green]"
        )
        return True

    def stop(self) -> None:
        """Stop the Redroid container."""
        status = self.get_status()
        if status is None:
            console.print("[yellow]No container found.[/yellow]")
            return

        if status != "running":
            console.print(
                f"[yellow]Container is not running (status: {status}).[/yellow]"
            )
            return

        console.print(f"Stopping container '{self.cc.name}'")
        result = self._run("stop", "-t", "10", self.cc.name, timeout=30)
        if result.returncode == 0:
            console.print("[green]Container stopped.[/green]")
        else:
            console.print(f"[red]Failed to stop:[/red] {result.stderr.strip()}")

    def destroy(self) -> None:
        """Stop and remove the container."""
        status = self.get_status()
        if status is None:
            console.print("[yellow]No container found to remove.[/yellow]")
            return

        console.print(f"Removing container '{self.cc.name}'")
        result = self._run("rm", "-f", self.cc.name, timeout=30)
        if result.returncode == 0:
            console.print("[green]Container removed.[/green]")
        else:
            console.print(f"[red]Failed to remove:[/red] {result.stderr.strip()}")

    def wait_for_boot(self, timeout: int = 120) -> bool:
        """Wait for Android to finish booting inside the container."""
        console.print("Waiting for Android to boot")
        start = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Booting", total=None)

            while time.time() - start < timeout:
                try:
                    result = subprocess.run(
                        ["adb", "-s", f"localhost:{self.cc.adb_port}",
                         "shell", "getprop", "sys.boot_completed"],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.stdout.strip() == "1":
                        progress.update(
                            task, description="[green]Android booted!"
                        )
                        return True
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

                time.sleep(2)

            progress.update(task, description="[red]Boot timeout!")

        console.print(
            f"[red]Android did not boot within {timeout}s.[/red]\n"
            f"Check logs: [bold]androlator logs[/bold]"
        )
        return False

    def connect_adb(self) -> bool:
        """Connect ADB to the running container."""
        try:
            result = subprocess.run(
                ["adb", "connect", f"localhost:{self.cc.adb_port}"],
                capture_output=True, text=True, timeout=10
            )
            if "connected" in result.stdout.lower():
                console.print(
                    f"[green]ADB connected to localhost:{self.cc.adb_port}[/green]"
                )
                return True
            else:
                console.print(
                    f"[red]ADB connection failed:[/red] {result.stdout.strip()}"
                )
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            console.print(f"[red]ADB error:[/red] {e}")
            return False

    def get_android_info(self) -> dict[str, str]:
        """Get basic info about the running Android instance."""
        info = {}
        props = [
            ("Android Version", "ro.build.version.release"),
            ("SDK Level", "ro.build.version.sdk"),
            ("CPU ABIs", "ro.product.cpu.abilist"),
            ("GPU Renderer", "ro.hardware.egl"),
            ("Boot Completed", "sys.boot_completed"),
        ]

        serial = f"localhost:{self.cc.adb_port}"
        for label, prop in props:
            try:
                result = subprocess.run(
                    ["adb", "-s", serial, "shell", "getprop", prop],
                    capture_output=True, text=True, timeout=5
                )
                info[label] = result.stdout.strip() or "(empty)"
            except (subprocess.TimeoutExpired, FileNotFoundError):
                info[label] = "(unavailable)"

        return info

    def logs(self, tail: int = 50) -> str:
        """Get recent container logs."""
        result = self._run("logs", "--tail", str(tail), self.cc.name, timeout=10)
        if result.returncode != 0:
            return f"Failed to get logs: {result.stderr.strip()}"
        return result.stdout
