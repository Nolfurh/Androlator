"""System prerequisite checker for Androlator."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from androlator.config import detect_intel_gpu_node

console = Console()


@dataclass
class CheckResult:
    """Result of a single prerequisite check."""

    name: str
    passed: bool
    detail: str
    fix_hint: str = ""


def check_kvm() -> CheckResult:
    """Check if KVM is available."""
    kvm_path = Path("/dev/kvm")
    if kvm_path.exists() and os.access(str(kvm_path), os.R_OK | os.W_OK):
        return CheckResult("KVM", True, "/dev/kvm accessible")
    elif kvm_path.exists():
        return CheckResult(
            "KVM", False, "/dev/kvm exists but not accessible",
            fix_hint="sudo chmod 666 /dev/kvm"
        )
    else:
        return CheckResult(
            "KVM", False, "/dev/kvm not found",
            fix_hint="Enable VT-x/AMD-V in BIOS and load kvm module"
        )


def check_binderfs() -> CheckResult:
    """Check if binderfs is mounted."""
    binderfs = Path("/dev/binderfs")
    control = binderfs / "binder-control"

    if control.exists():
        return CheckResult("Binderfs", True, "Mounted at /dev/binderfs")

    # Check if binder filesystem type is available
    filesystems = Path("/proc/filesystems").read_text()
    if "binder" in filesystems:
        return CheckResult(
            "Binderfs", False, "Binder fs type available but not mounted",
            fix_hint="sudo mkdir -p /dev/binderfs && sudo mount -t binder binder /dev/binderfs"
        )

    return CheckResult(
        "Binderfs", False, "Binder filesystem not available in kernel",
        fix_hint="Rebuild kernel with CONFIG_ANDROID_BINDER_IPC=y or CONFIG_ANDROID_BINDER_IPC_RUST=y"
    )


def check_docker() -> CheckResult:
    """Check if Docker daemon is running and accessible."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return CheckResult(
            "Docker", False, "Docker not installed",
            fix_hint="sudo pacman -S docker"
        )

    # Direct access first
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return CheckResult("Docker", True, "Docker daemon running (direct access)")
    except subprocess.TimeoutExpired:
        pass

    # Try with sudo
    try:
        result = subprocess.run(
            ["sudo", "-n", "docker", "info"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return CheckResult("Docker", True, "Docker daemon running (via sudo)")
    except subprocess.TimeoutExpired:
        pass

    # Check if daemon is actually running
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "docker"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip() == "active":
            return CheckResult(
                "Docker", True,
                "Docker daemon running (use_sudo=true in config)",
            )
        else:
            return CheckResult(
                "Docker", False, "Docker daemon not running",
                fix_hint="sudo systemctl start docker"
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(
            "Docker", False, "Cannot determine Docker status",
            fix_hint="sudo systemctl start docker"
        )


def check_adb() -> CheckResult:
    """Check if ADB is installed."""
    adb_bin = shutil.which("adb")
    if adb_bin:
        return CheckResult("ADB", True, f"Found at {adb_bin}")
    return CheckResult(
        "ADB", False, "ADB not found",
        fix_hint="sudo pacman -S android-tools"
    )


def check_scrcpy() -> CheckResult:
    """Check if scrcpy is installed."""
    scrcpy_bin = shutil.which("scrcpy")
    if scrcpy_bin:
        return CheckResult("Scrcpy", True, f"Found at {scrcpy_bin}")
    return CheckResult(
        "Scrcpy", False, "scrcpy not found",
        fix_hint="sudo pacman -S scrcpy"
    )


def check_gpu() -> CheckResult:
    """Check for Intel iGPU render node (required for GPU-accelerated Redroid)."""
    node = detect_intel_gpu_node()
    if node:
        return CheckResult("Intel GPU", True, f"Found at {node}")

    # Check if any render node exists
    dri = Path("/dev/dri")
    if dri.exists():
        render_nodes = list(dri.glob("renderD*"))
        if render_nodes:
            return CheckResult(
                "Intel GPU", False,
                f"Render nodes found ({', '.join(n.name for n in render_nodes)}) but none are Intel",
                fix_hint="Redroid will use software rendering (SwiftShader). "
                         "For GPU acceleration, ensure Intel iGPU is enabled in BIOS."
            )

    return CheckResult(
        "Intel GPU", False, "No render nodes found in /dev/dri",
        fix_hint="Load GPU kernel driver: modprobe i915"
    )


def run_all_checks() -> list[CheckResult]:
    """Run all prerequisite checks and return results."""
    checks = [
        check_kvm(),
        check_binderfs(),
        check_docker(),
        check_adb(),
        check_scrcpy(),
        check_gpu(),
    ]
    return checks


def print_check_results(results: list[CheckResult]) -> bool:
    """Print check results as a rich table. Returns True if all passed."""
    table = Table(title="Androlator — System Prerequisites")
    table.add_column("Component", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail")

    all_passed = True
    for r in results:
        status = "[green]✓[/green]" if r.passed else "[red]✗[/red]"
        detail = r.detail
        if not r.passed:
            all_passed = False
            if r.fix_hint:
                detail += f"\n[dim]Fix: {r.fix_hint}[/dim]"
        table.add_row(r.name, status, detail)

    console.print(table)

    if all_passed:
        console.print("\n[bold green]All checks passed![/bold green] Ready to start.\n")
    else:
        console.print(
            "\n[bold yellow]Some checks failed.[/bold yellow] "
            "Fix the issues above and run [bold]androlator setup[/bold] again.\n"
        )

    return all_passed
