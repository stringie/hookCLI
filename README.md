# hookCLI

A standalone command-line interface for extracting text from visual novels using [LunaHook](https://github.com/HIllya51/LunaHook).

Built as a lightweight CLI wrapper around the LunaHook text hooking engine — attach to any game process, extract text threads, and pipe the output however you need.

## Features

- Attach to any running game process by PID
- Auto-detect 32-bit / 64-bit architecture
- JSON or plain text output (great for piping to other tools)
- Insert custom H-codes or auto-detect hooks
- Graceful attach/detach lifecycle (no "poisoning" of game processes)
- Designed for integration into other applications via stdin/stdout

## Requirements

You need the LunaHook binaries placed in a `lunahook/` folder next to the executable:

```
hookCLI.exe
lunahook/
    LunaHost64.dll
    LunaHook64.dll
    LunaHook32.dll
    shareddllproxy64.exe
    shareddllproxy32.exe
```

These can be obtained from the [LunaHook releases](https://github.com/HIllya51/LunaHook/releases).

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

## Building from Source

Requires Python 3.8+ on Windows.

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --console --name hookCLI hook_cli.py
```

Or just run `build.bat`, which also copies the LunaHook DLLs into the `dist/` folder.

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

This project uses [LunaHook](https://github.com/HIllya51/LunaHook), also licensed under GPLv3.
