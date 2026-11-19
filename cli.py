"""Androlator CLI"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from androlator import __version__
from androlator.config import Config, detect_intel_gpu_node

console = Console()


def _load_config(ctx: click.Context) -> Config:
    """Load config from context or default."""
    config_path = ctx.obj.get("config") if ctx.obj else None
    return Config.load(config_path)


@click.group()
@click.option(
    "--config", "-c",
    type=click.Path(exists=False),
    default=None,
    help="Path to config file.",
)
@click.version_option(__version__, prog_name="androlator")
@click.pass_context
def main(ctx: click.Context, config: str | None) -> None:
    """Androlator — Run Android apps on Linux.

    Lightweight Android app runner built on Redroid (Docker) and Scrcpy.
    """
    ctx.ensure_object(dict)
    if config:
        from pathlib import Path
        ctx.obj["config"] = Path(config)


@main.command()
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Check system prerequisites."""
    from androlator.setup import run_all_checks, print_check_results

    results = run_all_checks()
    all_ok = print_check_results(results)
    ctx.exit(0 if all_ok else 1)


@main.command()
@click.option("--no-display", is_flag=True, help="Start container without scrcpy.")
@click.option("--foreground", "-f", is_flag=True, help="Run scrcpy in foreground.")
@click.option(
    "--gpu/--no-gpu", default=True,
    help="Enable/disable GPU acceleration (default: enabled)."
)
@click.pass_context
def start(ctx: click.Context, no_display: bool, foreground: bool, gpu: bool) -> None:
    """Start Androlator (container + display)."""
    from androlator.container import ContainerManager
    from androlator.display import DisplayManager

    config = _load_config(ctx)

    # Auto-detect GPU node if not set or if GPU disabled
    if not gpu:
        config.container.gpu_mode = "guest"
        console.print("[yellow]GPU acceleration disabled — using SwiftShader.[/yellow]")
    else:
        detected = detect_intel_gpu_node()
        if detected:
            config.container.gpu_node = detected
        elif config.container.gpu_mode == "host":
            console.print(
                "[yellow]No Intel GPU found. Falling back to software rendering.[/yellow]"
            )
            config.container.gpu_mode = "guest"

    container_manager = ContainerManager(config)

    # Pull image if needed
    if not container_manager.image_exists():
        container_manager.pull_image()

    # Create and start container
    container_manager.create_and_start()

    # Connect ADB
    console.print("Connecting ADB")
    container_manager.connect_adb()

    # Wait for Android boot
    if not container_manager.wait_for_boot(timeout=120):
        console.print("[red]Container started but Android boot timed out.[/red]")
        console.print("You can check logs with: [bold]androlator logs[/bold]")
        return

    # Show Android info
    info = container_manager.get_android_info()
    table = Table(title="Android Instance")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    for key, value in info.items():
        table.add_row(key, value)
    console.print(table)

    # Start File Receiver and ensure Share APK is installed
    from androlator.receiver import ReceiverManager
    receiver_manager = ReceiverManager()
    ReceiverManager.ensure_share_app_installed(config)
    receiver_manager.start_daemon(config)

    # Launch scrcpy
    if not no_display:
        display_manager = DisplayManager(config)
        if not display_manager.start(foreground=foreground):
            console.print(
                "[yellow]Scrcpy failed to start. "
                "The container is still running — try manually:[/yellow]\n"
                f"  scrcpy --serial localhost:{config.container.adb_port}"
            )
    else:
        console.print(
            f"[dim]Container running. Connect manually: "
            f"adb connect localhost:{config.container.adb_port}[/dim]"
        )


@main.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Stop Androlator (display + container + receiver)."""
    from androlator.container import ContainerManager
    from androlator.display import DisplayManager
    from androlator.receiver import ReceiverManager

    config = _load_config(ctx)

    # Stop receiver daemon
    receiver_manager = ReceiverManager()
    receiver_manager.stop_daemon(config)

    # Stop scrcpy first
    display_manager = DisplayManager(config)
    display_manager.stop()

    # Disconnect ADB
    import subprocess
    try:
        subprocess.run(
            ["adb", "disconnect", f"localhost:{config.container.adb_port}"],
            capture_output=True, timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Stop container
    container_manager = ContainerManager(config)
    container_manager.stop()


@main.command()
@click.pass_context
def destroy(ctx: click.Context) -> None:
    """Stop and remove the container (deletes all data)."""
    from androlator.container import ContainerManager
    from androlator.display import DisplayManager

    config = _load_config(ctx)

    display_manager = DisplayManager(config)
    display_manager.stop()

    container_manager = ContainerManager(config)
    container_manager.destroy()


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show Androlator status."""
    from androlator.container import ContainerManager
    from androlator.display import DisplayManager

    config = _load_config(ctx)
    container_manager = ContainerManager(config)
    display_manager = DisplayManager(config)

    table = Table(title="Androlator Status")
    table.add_column("Component", style="bold")
    table.add_column("Status")

    # Container status
    cont_status = container_manager.get_status()
    if cont_status is None:
        table.add_row("Container", "[dim]Not created[/dim]")
    elif cont_status == "running":
        table.add_row("Container", "[green]Running[/green]")
    else:
        table.add_row("Container", f"[yellow]{cont_status}[/yellow]")

    # Scrcpy status
    if display_manager.is_running():
        table.add_row("Display (scrcpy)", "[green]Running[/green]")
    else:
        table.add_row("Display (scrcpy)", "[dim]Not running[/dim]")

    # GPU info
    gpu_node = detect_intel_gpu_node()
    if gpu_node:
        table.add_row("Intel GPU", f"[green]{gpu_node}[/green]")
    else:
        table.add_row("Intel GPU", "[yellow]Not found[/yellow]")

    # Receiver status
    from androlator.receiver import ReceiverManager
    receiver_manager = ReceiverManager()
    if receiver_manager.is_running():
        table.add_row("Share Receiver", f"[green]Running (port {receiver_manager.port})[/green]")
    else:
        table.add_row("Share Receiver", "[dim]Not running[/dim]")

    console.print(table)

    # If running, show Android info
    if cont_status == "running":
        info = container_manager.get_android_info()
        if info.get("Boot Completed") == "1":
            info_table = Table(title="Android Info")
            info_table.add_column("Property", style="bold")
            info_table.add_column("Value")
            for key, value in info.items():
                info_table.add_row(key, value)
            console.print(info_table)


@main.command()
@click.argument("apk_path")
@click.pass_context
def install(ctx: click.Context, apk_path: str) -> None:
    """Install an APK file."""
    from androlator.apps import AppManager

    config = _load_config(ctx)
    app_manager = AppManager(config)
    app_manager.install(apk_path)


@main.command()
@click.argument("package")
@click.pass_context
def uninstall(ctx: click.Context, package: str) -> None:
    """Uninstall an app by package name."""
    from androlator.apps import AppManager

    config = _load_config(ctx)
    app_manager = AppManager(config)
    app_manager.uninstall(package)


@main.command(name="apps")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all packages (not just third-party).")
@click.pass_context
def list_apps(ctx: click.Context, show_all: bool) -> None:
    """List installed apps."""
    from androlator.apps import AppManager

    config = _load_config(ctx)
    app_manager = AppManager(config)
    app_manager.print_packages(third_party_only=not show_all)


@main.command()
@click.argument("package")
@click.pass_context
def launch(ctx: click.Context, package: str) -> None:
    """Launch an installed app."""
    from androlator.apps import AppManager

    config = _load_config(ctx)
    app_manager = AppManager(config)
    app_manager.launch(package)


@main.command()
@click.pass_context
def shell(ctx: click.Context) -> None:
    """Open an ADB shell into the Android container."""
    from androlator.apps import AppManager

    config = _load_config(ctx)
    app_manager = AppManager(config)
    app_manager.shell()


@main.command()
@click.option("--tail", "-n", default=50, help="Number of log lines to show.")
@click.pass_context
def logs(ctx: click.Context, tail: int) -> None:
    """Show container logs."""
    from androlator.container import ContainerManager

    config = _load_config(ctx)
    container_manager = ContainerManager(config)
    console.print(container_manager.logs(tail=tail))


@main.command(name="config")
@click.option("--show", is_flag=True, help="Show current configuration.")
@click.option("--init", "do_init", is_flag=True, help="Create default config file.")
@click.pass_context
def config_cmd(ctx: click.Context, show: bool, do_init: bool) -> None:
    """Show or initialize configuration."""
    from androlator.config import DEFAULT_CONFIG_FILE

    config = _load_config(ctx)

    if do_init:
        config.save()
        console.print(f"[green]Config saved to {DEFAULT_CONFIG_FILE}[/green]")
        return

    if show or True:
        table = Table(title=f"Configuration")
        table.add_column("Key", style="bold")
        table.add_column("Value")

        table.add_row("[dim]── Display ──[/dim]", "")
        table.add_row("max_fps", str(config.display.max_fps))
        table.add_row("video_bitrate", config.display.video_bitrate)
        table.add_row("video_codec", config.display.video_codec)
        table.add_row("video_buffer", str(config.display.video_buffer))
        table.add_row("no_audio", str(config.display.no_audio))
        table.add_row("keyboard_mode", config.display.keyboard_mode)
        table.add_row("mouse_mode", config.display.mouse_mode)
        table.add_row("hwdec", config.display.hwdec)
        table.add_row("window_title", config.display.window_title)
        table.add_row("fullscreen", str(config.display.fullscreen))

        table.add_row("[dim]── Container ──[/dim]", "")
        table.add_row("image", config.container.image)
        table.add_row("name", config.container.name)
        table.add_row("adb_port", str(config.container.adb_port))
        table.add_row("gpu_mode", config.container.gpu_mode)
        table.add_row("gpu_node", config.container.gpu_node)
        table.add_row("cpus", str(config.container.cpus))
        table.add_row("memory", config.container.memory)
        table.add_row("data_dir", config.container.data_dir or "(none)")
        table.add_row("use_sudo", str(config.container.use_sudo))

        console.print(table)


@main.group(name="receiver")
def receiver_group() -> None:
    """Manage Android to Host Share receiver."""
    pass


@receiver_group.command(name="start")
@click.pass_context
def receiver_start_cmd(ctx: click.Context) -> None:
    """Start the file receiver daemon."""
    from androlator.receiver import ReceiverManager

    config = _load_config(ctx)
    receiver_manager = ReceiverManager()
    ReceiverManager.ensure_share_app_installed(config)
    if receiver_manager.start_daemon(config):
        console.print(f"[green]Share receiver started on port {receiver_manager.port}[/green]")
    else:
        console.print("[red]Failed to start receiver.[/red]")


@receiver_group.command(name="stop")
@click.pass_context
def receiver_stop_cmd(ctx: click.Context) -> None:
    """Stop the file receiver daemon."""
    from androlator.receiver import ReceiverManager

    config = _load_config(ctx)
    receiver_manager = ReceiverManager()
    receiver_manager.stop_daemon(config)
    console.print("[green]Share receiver stopped.[/green]")


@receiver_group.command(name="status")
@click.pass_context
def receiver_status_cmd(ctx: click.Context) -> None:
    """Check file receiver daemon status."""
    from androlator.receiver import ReceiverManager

    receiver_manager = ReceiverManager()
    if receiver_manager.is_running():
        console.print(f"[green]Share receiver running on port {receiver_manager.port}[/green]")
    else:
        console.print("[yellow]Share receiver not running.[/yellow]")


if __name__ == "__main__":
    main()
