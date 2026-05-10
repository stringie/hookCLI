# hookCLI

A standalone command-line interface for extracting text from visual novels using [LunaHook](https://github.com/HIllya51/LunaTranslator).

Built as a lightweight CLI wrapper around the LunaHook text hooking engine — attach to any game process, extract text threads, and pipe the output however you need.

## Features

- Attach to any running game process by PID
- Auto-detect 32-bit / 64-bit architecture
- JSON or plain text output (great for piping to other tools)
- Insert custom H-codes or auto-detect hooks
- Graceful attach/detach lifecycle (no "poisoning" of game processes)
- Designed for integration into other applications via stdin/stdout

## Quick Start

```bash
# Clone the repo (includes the required LunaHook binaries)
git clone https://github.com/stringie/hookCLI.git
cd hookCLI

# Run directly with Python (no build needed)
python hook_cli.py --attach <PID>

# Or build to a standalone exe
build.bat
dist\hookCLI.exe --attach <PID>
```

## Usage

```bash
# Basic — attach to a game by PID
hookCLI.exe --attach 12345

# JSON output (one JSON object per line, ideal for piping)
hookCLI.exe --attach 12345 --format json

# Insert a custom hook code
hookCLI.exe --attach 12345 --hookcode /HS-8@4025A0

# Auto-detect and insert common PC game hooks
hookCLI.exe --attach 12345 --auto-hooks

# Log output to a file
hookCLI.exe --attach 12345 --format json --output log.jsonl

# See all options
hookCLI.exe --help
```

Send `quit` via stdin or press Ctrl+C to gracefully detach and exit.

## Project Structure

```
hookCLI/
├── hook_cli.py          # Main source code
├── build.bat            # Build script (PyInstaller)
├── hookCLI.spec         # PyInstaller spec file
├── lunahook/            # LunaHook binaries (included)
│   ├── LunaHost64.dll   # Host library (loaded by hookCLI)
│   ├── LunaHook64.dll   # Injected into 64-bit games
│   ├── LunaHook32.dll   # Injected into 32-bit games
│   ├── LunaSubprocess64.exe  # DLL injector (64-bit)
│   └── LunaSubprocess32.exe  # DLL injector (32-bit)
├── LICENSE              # GPLv3
└── README.md
```

## Building from Source

Requires Python 3.8+ on Windows.

```bash
# Option 1: Use the build script
build.bat

# Option 2: Manual
pip install pyinstaller
pyinstaller --noconfirm --onefile --console --name hookCLI hook_cli.py
# Then copy the lunahook/ folder next to the output exe
```

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

The included LunaHook binaries are from [LunaTranslator](https://github.com/HIllya51/LunaTranslator) by [@HIllya51](https://github.com/HIllya51), also licensed under GPLv3.
