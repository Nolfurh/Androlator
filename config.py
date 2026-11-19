"""Configuration management for Androlator."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "androlator"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.toml"

# Redroid image defaults
DEFAULT_IMAGE = "redroid/redroid:14.0.0_64only-latest"
DEFAULT_CONTAINER_NAME = "androlator"
DEFAULT_ADB_PORT = 5555

# Display defaults
DEFAULT_MAX_FPS = 60
DEFAULT_VIDEO_BITRATE = "8M"
DEFAULT_VIDEO_CODEC = "h264"

# Resource defaults
DEFAULT_CPUS = 4
DEFAULT_MEMORY = "4g"


@dataclass
class DisplayConfig:
    """Scrcpy display settings."""

    max_fps: int = DEFAULT_MAX_FPS
    video_bitrate: str = DEFAULT_VIDEO_BITRATE
    video_codec: str = DEFAULT_VIDEO_CODEC
    video_buffer: int = 0
    display_buffer: int = 0  # alias for backwards compatibility
    no_audio: bool = True
    keyboard_mode: str = "sdk"
    mouse_mode: str = "sdk"
    hwdec: str = "auto"
    window_title: str = "Androlator"
    fullscreen: bool = False


@dataclass
class ContainerConfig:
    """Docker/Redroid container settings."""

    image: str = DEFAULT_IMAGE
    name: str = DEFAULT_CONTAINER_NAME
    adb_port: int = DEFAULT_ADB_PORT
    gpu_mode: str = "host"
    gpu_node: str = "/dev/dri/renderD129"  # Intel iGPU
    cpus: int = DEFAULT_CPUS
    memory: str = DEFAULT_MEMORY
    data_dir: str = ""  # persistent data volume path
    use_sudo: bool = True  # use sudo for docker commands


@dataclass
class Config:
    """Root configuration."""

    display: DisplayConfig = field(default_factory=DisplayConfig)
    container: ContainerConfig = field(default_factory=ContainerConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Load configuration from TOML file, falling back to defaults."""
        config_path = path or DEFAULT_CONFIG_FILE
        cfg = cls()

        if config_path.exists():
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            cfg._apply(data)

        return cfg

    def _apply(self, data: dict[str, Any]) -> None:
        """Apply dictionary values to config dataclasses."""
        if "display" in data:
            for key, value in data["display"].items():
                if key == "display_buffer":
                    self.display.video_buffer = value
                    self.display.display_buffer = value
                elif hasattr(self.display, key):
                    setattr(self.display, key, value)

        if "container" in data:
            for key, value in data["container"].items():
                if hasattr(self.container, key):
                    setattr(self.container, key, value)

    def save(self, path: Path | None = None) -> None:
        """Save current configuration to TOML file."""
        config_path = path or DEFAULT_CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# Androlator Configuration",
            "",
            "[display]",
            f'max_fps = {self.display.max_fps}',
            f'video_bitrate = "{self.display.video_bitrate}"',
            f'video_codec = "{self.display.video_codec}"',
            f'video_buffer = {self.display.video_buffer}',
            f'no_audio = {"true" if self.display.no_audio else "false"}',
            f'keyboard_mode = "{self.display.keyboard_mode}"',
            f'mouse_mode = "{self.display.mouse_mode}"',
            f'hwdec = "{self.display.hwdec}"',
            f'window_title = "{self.display.window_title}"',
            f'fullscreen = {"true" if self.display.fullscreen else "false"}',
            "",
            "[container]",
            f'image = "{self.container.image}"',
            f'name = "{self.container.name}"',
            f'adb_port = {self.container.adb_port}',
            f'gpu_mode = "{self.container.gpu_mode}"',
            f'gpu_node = "{self.container.gpu_node}"',
            f'cpus = {self.container.cpus}',
            f'memory = "{self.container.memory}"',
            f'data_dir = "{self.container.data_dir}"',
            f'use_sudo = {"true" if self.container.use_sudo else "false"}',
            "",
        ]

        config_path.write_text("\n".join(lines))


def detect_intel_gpu_node() -> str | None:
    """Auto-detect the Intel iGPU render node by checking sysfs vendor IDs."""
    dri_path = Path("/dev/dri")
    if not dri_path.exists():
        return None

    for node in sorted(dri_path.glob("renderD*")):
        vendor_path = Path(f"/sys/class/drm/{node.name}/device/vendor")
        if vendor_path.exists():
            vendor = vendor_path.read_text().strip()
            if vendor == "0x8086":  # Intel
                return str(node)

    return None
