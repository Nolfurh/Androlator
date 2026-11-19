# Androlator

Lightweight Android app runner for Linux, built on [Redroid](https://github.com/remote-android/redroid-doc) (Docker-based Android container) and [Scrcpy](https://github.com/Genymobile/scrcpy) (native display client).

## Quick Start

```bash
# 1. One-time host setup (run as root)
sudo ./scripts/setup-host.sh

# 2. Install Androlator
pip install -e .

# 3. Check prerequisites
androlator setup

# 4. Start Android
androlator start

# 5. Install an APK
androlator install path/to/app.apk

# 6. List & launch apps
androlator apps
androlator launch com.example.app
```

## Commands

| Command | Description |
|---|---|
| `androlator setup` | Check system prerequisites |
| `androlator start` | Start container + display |
| `androlator stop` | Stop display + container |
| `androlator destroy` | Remove container (deletes data) |
| `androlator status` | Show current status |
| `androlator install <apk>` | Install an APK |
| `androlator uninstall <pkg>` | Uninstall an app |
| `androlator apps` | List installed apps |
| `androlator launch <pkg>` | Launch an app |
| `androlator shell` | Open ADB shell |
| `androlator logs` | Show container logs |
| `androlator config` | Show/init configuration |
