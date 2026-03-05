#!/usr/bin/env python3
#
# hookCLI — Standalone CLI for extracting text from visual novels via LunaHook.
#
# Copyright (C) 2025 Torii Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# This program uses LunaHook from LunaTranslator (https://github.com/HIllya51/LunaTranslator),
# licensed under the GNU General Public License v3.0.
#
"""
hookCLI — Standalone CLI for extracting text from visual novels via LunaHook.

Usage:
    hookCLI.exe --attach <PID> [options]

The following files must be in a "lunahook/" subfolder next to this exe:
    lunahook/LunaHost64.dll
    lunahook/LunaHook64.dll
    lunahook/LunaHook32.dll
    lunahook/shareddllproxy64.exe
    lunahook/shareddllproxy32.exe
"""

import argparse
import ctypes
import ctypes.wintypes
import json
import os
import signal
import subprocess
import sys
import time
import threading
from ctypes import (
    CDLL,
    CFUNCTYPE,
    Structure,
    c_bool,
    c_char,
    c_char_p,
    c_float,
    c_int,
    c_int64,
    c_uint,
    c_uint8,
    c_uint32,
    c_uint64,
    c_void_p,
    c_wchar,
    c_wchar_p,
)
from ctypes.wintypes import DWORD, LPCWSTR


# ─── Version ────────────────────────────────────────────────────────────────

__version__ = "1.0.0"


# ─── Resolve base directory (works for both .py and PyInstaller .exe) ───────

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ─── Force UTF-8 on stdout/stderr (prevents cp1251/cp932 encode errors) ─────

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ─── Structures ─────────────────────────────────────────────────────────────

class ThreadParam(Structure):
    _fields_ = [
        ("processId", c_uint),
        ("addr", c_uint64),
        ("ctx", c_uint64),
        ("ctx2", c_uint64),
    ]

    def __hash__(self):
        return hash((self.processId, self.addr, self.ctx, self.ctx2))

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    def __repr__(self):
        return f"(pid={self.processId}, addr=0x{self.addr:X}, ctx=0x{self.ctx:X}, ctx2=0x{self.ctx2:X})"


class SearchParam(Structure):
    _fields_ = [
        ("pattern", c_char * 30),
        ("address_method", c_int),
        ("search_method", c_int),
        ("length", c_int),
        ("offset", c_int),
        ("searchTime", c_int),
        ("maxRecords", c_int),
        ("codepage", c_int),
        ("padding", c_int64),
        ("minAddress", c_uint64),
        ("maxAddress", c_uint64),
        ("boundaryModule", c_wchar * 120),
        ("exportModule", c_wchar * 120),
        ("text", c_wchar * 30),
        ("isjithook", c_bool),
        ("sharememname", c_wchar * 64),
        ("sharememsize", c_uint64),
    ]


# ─── Callback signatures ────────────────────────────────────────────────────

ProcessEvent = CFUNCTYPE(None, DWORD)
ThreadEvent_maybeEmbed = CFUNCTYPE(None, c_wchar_p, c_char_p, ThreadParam, c_bool)
ThreadEvent = CFUNCTYPE(None, c_wchar_p, c_char_p, ThreadParam)
OutputCallback = CFUNCTYPE(None, c_wchar_p, c_char_p, ThreadParam, c_wchar_p)
HostInfoHandler = CFUNCTYPE(None, c_int, c_wchar_p)
HookInsertHandler = CFUNCTYPE(None, DWORD, c_uint64, c_wchar_p)
EmbedCallback = CFUNCTYPE(None, c_wchar_p, ThreadParam)
I18NQueryCallback = CFUNCTYPE(c_void_p, c_wchar_p)
FindHooksCallback_t = CFUNCTYPE(None, c_wchar_p, c_wchar_p)
QueryHistoryCallback = CFUNCTYPE(None, c_wchar_p)


# ─── Win32 helpers ──────────────────────────────────────────────────────────

def is_process_64bit(pid: int) -> bool:
    """Detect whether a process is 64-bit using IsWow64Process."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Fallback: assume 64-bit on 64-bit OS
        return sys.maxsize > 2**32

    try:
        is_wow64 = ctypes.c_int(0)
        kernel32.IsWow64Process(handle, ctypes.byref(is_wow64))
        # If running under WOW64, it's a 32-bit process on a 64-bit OS
        return not is_wow64.value
    finally:
        kernel32.CloseHandle(handle)


def process_exists(pid: int) -> bool:
    """Check if a process is still running."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(handle)




# ─── Output formatting ──────────────────────────────────────────────────────

class OutputFormatter:
    """Handles text output in various formats."""

    def __init__(self, fmt="text", outfile=None):
        self.fmt = fmt
        self._lock = threading.Lock()
        if outfile:
            self._fp = open(outfile, "a", encoding="utf-8")
        else:
            self._fp = None

    def emit_text(self, hookcode, hookname, tp, text):
        with self._lock:
            if self.fmt == "json":
                obj = {
                    "type": "text",
                    "hookcode": hookcode,
                    "hookname": hookname,
                    "pid": tp.processId,
                    "addr": f"0x{tp.addr:X}",
                    "ctx": f"0x{tp.ctx:X}",
                    "ctx2": f"0x{tp.ctx2:X}",
                    "text": text,
                    "timestamp": time.time(),
                }
                line = json.dumps(obj, ensure_ascii=False)
            else:
                line = f"[{hookcode}] {text}"
            self._write(line)

    def emit_event(self, event_type, **kwargs):
        with self._lock:
            if self.fmt == "json":
                obj = {"type": event_type, "timestamp": time.time(), **kwargs}
                line = json.dumps(obj, ensure_ascii=False)
            else:
                detail = ", ".join(f"{k}={v}" for k, v in kwargs.items())
                line = f"[{event_type.upper()}] {detail}"
            self._write(line)

    def _write(self, line):
        print(line, flush=True)
        if self._fp:
            self._fp.write(line + "\n")
            self._fp.flush()

    def close(self):
        if self._fp:
            self._fp.close()


# ─── HookCLI Engine ─────────────────────────────────────────────────────────

class HookCLI:
    """Main CLI engine wrapping LunaHost DLL."""

    def __init__(self, dll_dir, formatter):
        self.dll_dir = dll_dir
        self.fmt = formatter
        self._keepref = []  # prevent GC of callbacks
        self._attached_pids = []
        self._all_disconnected = threading.Event()
        self._all_disconnected.set()  # starts as set (no connections yet)

        host_dll = os.path.join(dll_dir, "LunaHost64.dll")
        if not os.path.isfile(host_dll):
            print(f"ERROR: Cannot find {host_dll}", file=sys.stderr)
            print(f"Make sure the lunahook/ folder is next to the executable.", file=sys.stderr)
            sys.exit(1)

        self.host = CDLL(host_dll)
        self._bind_functions()

    def _bind_functions(self):
        h = self.host

        h.Luna_Start.argtypes = (
            ProcessEvent, ProcessEvent,
            ThreadEvent_maybeEmbed, ThreadEvent,
            OutputCallback, HostInfoHandler,
            HookInsertHandler, EmbedCallback,
            I18NQueryCallback,
        )

        h.Luna_ConnectProcess.argtypes = (DWORD,)
        h.Luna_CheckIfNeedInject.argtypes = (DWORD,)
        h.Luna_CheckIfNeedInject.restype = c_bool

        h.Luna_Settings.argtypes = (c_int, c_bool, c_int, c_int, c_int)

        h.Luna_InsertHookCode.argtypes = (DWORD, LPCWSTR)
        h.Luna_InsertHookCode.restype = c_bool

        h.Luna_InsertPCHooks.argtypes = (DWORD, c_int)
        h.Luna_RemoveHook.argtypes = (DWORD, c_uint64)
        h.Luna_DetachProcess.argtypes = (DWORD,)
        h.Luna_SyncThread.argtypes = (ThreadParam, c_bool)
        h.Luna_ResetLang.argtypes = ()

        h.Luna_FindHooks.argtypes = (DWORD, SearchParam, FindHooksCallback_t, c_wchar_p)
        h.Luna_QueryThreadHistory.argtypes = (ThreadParam, c_bool, c_void_p)

        h.Luna_AllocString.argtypes = (c_wchar_p,)
        h.Luna_AllocString.restype = c_void_p

        h.Luna_EmbedSettings.argtypes = (
            DWORD, c_uint32, c_uint8, c_bool, c_wchar_p,
            c_uint32, c_bool, c_bool, c_bool, c_float,
        )
        h.Luna_CheckIsUsingEmbed.argtypes = (ThreadParam,)
        h.Luna_CheckIsUsingEmbed.restype = c_bool
        h.Luna_UseEmbed.argtypes = (ThreadParam, c_bool)
        h.Luna_EmbedCallback.argtypes = (ThreadParam, LPCWSTR, LPCWSTR)

    # ── Callbacks ──

    def _on_connect(self, pid):
        self._all_disconnected.clear()  # we have active connections now
        self._attached_pids.append(pid)
        self.fmt.emit_event("connected", pid=pid)

        # Mirror LunaTranslator: Re-insert hooks directly upon process connection
        # This re-trigger is required to have the DLL broadcast its hooks upon reconnection
        if hasattr(self, "_startup_hookcodes"):
            for hc in self._startup_hookcodes:
                self.insert_hookcode(pid, hc)
        if getattr(self, "_startup_auto_hooks", False):
            self.insert_pc_hooks(pid)

        # Mirror LunaTranslator: supply default EmbedSettings upon connecting.
        # Luna's onprocconnect calls flashembedsettings(pid) at this point.
        if hasattr(self.host, "Luna_EmbedSettings"):
            self.host.Luna_EmbedSettings(
                pid,
                2000,   # timeout_translate (2000ms)
                2,      # charset (Shift-JIS/etc)
                False,  # changecharset
                "",     # changefont_font
                0,      # displaymode
                True,   # wait
                False,  # clearText
                False,  # changefontsize_use
                0.0     # changefontsize
            )

    def _on_disconnect(self, pid):
        if pid in self._attached_pids:
            self._attached_pids.remove(pid)
        self.fmt.emit_event("disconnected", pid=pid)
        if not self._attached_pids:
            self._all_disconnected.set()  # all processes have fully disconnected

    def _on_new_hook(self, hookcode, hookname_bytes, tp, is_embedable):
        hookname = hookname_bytes.decode("utf-8", errors="replace") if hookname_bytes else ""

        # Mirror LunaTranslator: sync this thread so we receive text output from it.
        if hasattr(self.host, "Luna_SyncThread"):
            self.host.Luna_SyncThread(tp, True)
            

        self.fmt.emit_event(
            "hook_found",
            hookcode=hookcode,
            hookname=hookname,
            pid=tp.processId,
            addr=f"0x{tp.addr:X}",
            ctx=f"0x{tp.ctx:X}",
            ctx2=f"0x{tp.ctx2:X}",
            embedable=is_embedable,
        )

    def _on_remove_hook(self, hookcode, hookname_bytes, tp):
        hookname = hookname_bytes.decode("utf-8", errors="replace") if hookname_bytes else ""
        self.fmt.emit_event(
            "hook_removed",
            hookcode=hookcode,
            hookname=hookname,
            pid=tp.processId,
        )

    def _on_output(self, hookcode, hookname_bytes, tp, text):
        hookname = hookname_bytes.decode("utf-8", errors="replace") if hookname_bytes else ""
        self.fmt.emit_text(hookcode, hookname, tp, text)

    def _on_info(self, info_type, message):
        self.fmt.emit_event("info", code=info_type, message=message)

    def _on_hook_insert(self, pid, addr, hookcode):
        self.fmt.emit_event(
            "hook_inserted",
            pid=pid,
            addr=f"0x{addr:X}",
            hookcode=hookcode,
        )

    def _on_embed(self, text, tp):
        pass  # no-op for read-only extraction

    def _on_i18n(self, query_text):
        if not hasattr(self.host, "Luna_AllocString"):
            return None
        # We must return a valid wide string pointer allocated from the DLL's internal heap.
        # If we return None, the injected target game DLL will dereference a NULL pointer 
        # when attempting to draw overlay text, crashing its IPC thread and permanently 
        # poisoning the game instance against future reconnections.
        if query_text:
            return self.host.Luna_AllocString(query_text)
        return self.host.Luna_AllocString("")

    # ── Public API ──

    def start(self, delay=200, codepage=932, max_buffer=1000, max_history=10):
        """Initialize the host engine and configure settings."""
        callbacks = [
            ProcessEvent(self._on_connect),
            ProcessEvent(self._on_disconnect),
            ThreadEvent_maybeEmbed(self._on_new_hook),
            ThreadEvent(self._on_remove_hook),
            OutputCallback(self._on_output),
            HostInfoHandler(self._on_info),
            HookInsertHandler(self._on_hook_insert),
            EmbedCallback(self._on_embed),
            I18NQueryCallback(self._on_i18n),
        ]
        self._keepref.extend(callbacks)
        self.host.Luna_Start(*callbacks)
        self.host.Luna_ResetLang()
        self.host.Luna_Settings(delay, False, codepage, max_buffer, max_history)
        self.fmt.emit_event("engine_started", delay=delay, codepage=codepage)

    def attach(self, pid, is_64bit=None):
        """Attach to a game process and inject the hook DLL.

        Matches LunaTranslator's start_unsafe() flow exactly:
        Luna_ConnectProcess → CheckIfNeedInject → inject only if needed.
        """
        if is_64bit is None:
            is_64bit = is_process_64bit(pid)

        arch = "64" if is_64bit else "32"
        self.fmt.emit_event("attaching", pid=pid, arch=f"{arch}-bit")

        self.host.Luna_ConnectProcess(pid)

        if self.host.Luna_CheckIfNeedInject(pid):
            dll_path = os.path.join(self.dll_dir, f"LunaHook{arch}.dll")
            injector = os.path.join(self.dll_dir, f"shareddllproxy{arch}.exe")

            if not os.path.isfile(dll_path):
                print(f"ERROR: Cannot find {dll_path}", file=sys.stderr)
                sys.exit(1)
            if not os.path.isfile(injector):
                print(f"ERROR: Cannot find {injector}", file=sys.stderr)
                sys.exit(1)

            cmd = f'"{injector}" dllinject {pid} "{dll_path}"'
            self.fmt.emit_event("injecting", cmd=cmd)

            # Mirror Luna's injectdll() logic exactly:
            # 1. Try normal injection first
            # 2. If it returns non-zero, the injector RAN but we don't retry
            #    (the DLL may have loaded even with a non-zero exit code)
            # 3. Only use admin elevation if the normal injector couldn't run at all
            #
            # CRITICAL: Do NOT retry with admin if the injector already ran!
            # A second LoadLibrary on an already-loaded DLL increments its ref count
            # to 2. When the DLL later calls FreeLibraryAndExitThread to detach,
            # FreeLibrary only decrements 2→1, so the DLL NEVER unloads. Its pipe 
            # thread exits but the DLL stays loaded as a zombie — permanently 
            # poisoning the game process against any future hook connections.
            try:
                ret = subprocess.run(cmd, shell=True, capture_output=True).returncode
                if ret != 0:
                    # Injector ran but returned non-zero. This does NOT mean the DLL
                    # wasn't loaded — in fact it often IS loaded (we see CONNECTED).
                    # Do NOT retry. Match Luna's behavior: "if ret: return"
                    self.fmt.emit_event("inject_returned_nonzero", returncode=ret,
                        message="Injector returned non-zero but DLL may have loaded. Not retrying to avoid double-load.")
            except FileNotFoundError:
                # Injector couldn't be found/run at all → try with admin
                self.fmt.emit_event("inject_elevated", reason="injector not accessible, retrying as admin")
                ctypes.windll.shell32.ShellExecuteW(
                    0, "runas", injector,
                    f'dllinject {pid} "{dll_path}"',
                    None, 0,
                )
        else:
            self.fmt.emit_event("already_injected", pid=pid)

    def insert_hookcode(self, pid, hookcode):
        ok = self.host.Luna_InsertHookCode(pid, hookcode)
        self.fmt.emit_event("hookcode_result", hookcode=hookcode, success=ok)
        return ok

    def insert_pc_hooks(self, pid):
        self.host.Luna_InsertPCHooks(pid, 0)
        self.host.Luna_InsertPCHooks(pid, 1)
        self.fmt.emit_event("pc_hooks_inserted", pid=pid)

    def detach(self, pid):
        self.host.Luna_DetachProcess(pid)
        self.fmt.emit_event("detached", pid=pid)

    def detach_all(self):
        for pid in self._attached_pids.copy():
            self.detach(pid)


# ─── CLI argument parsing ───────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="hookCLI",
        description="Extract text from visual novels using LunaHook.",
        epilog=(
            "Examples:\n"
            "  hookCLI --attach 12345\n"
            "  hookCLI --attach 12345 --format json --output log.jsonl\n"
            "  hookCLI --attach 12345 --hookcode /HS-8@4025A0\n"
            "  hookCLI --attach 12345 --codepage 932 --delay 200 --auto-hooks\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )

    # ── Required ──
    parser.add_argument(
        "--attach", type=int, required=True, metavar="PID",
        help="Process ID of the game to attach to.",
    )

    # ── Architecture ──
    parser.add_argument(
        "--arch", choices=["32", "64"], default=None,
        help="Force 32-bit or 64-bit mode. Auto-detected if omitted.",
    )

    # ── Settings ──
    settings = parser.add_argument_group("settings")
    settings.add_argument(
        "--codepage", type=int, default=932,
        help="Text codepage (default: 932 = Shift-JIS).",
    )
    settings.add_argument(
        "--delay", type=int, default=200,
        help="Text thread delay in ms before flushing (default: 200).",
    )
    settings.add_argument(
        "--max-buffer", type=int, default=1000,
        help="Max buffer size in characters (default: 1000).",
    )
    settings.add_argument(
        "--max-history", type=int, default=10,
        help="Max history entries per hook thread (default: 10).",
    )

    # ── Hook codes ──
    hooks = parser.add_argument_group("hooks")
    hooks.add_argument(
        "--hookcode", type=str, action="append", default=[],
        help="Insert a custom H-code (can be repeated). E.g. /HS-8@4025A0",
    )
    hooks.add_argument(
        "--auto-hooks", action="store_true",
        help="Auto-detect and insert common PC game hooks.",
    )

    # ── Output ──
    output = parser.add_argument_group("output")
    output.add_argument(
        "--format", choices=["text", "json"], default="text", dest="out_format",
        help="Output format: 'text' (human-readable) or 'json' (one JSON object per line, for piping). Default: text.",
    )
    output.add_argument(
        "--output", "-o", type=str, default=None, metavar="FILE",
        help="Also write output to a file (appends).",
    )

    # ── Advanced ──
    advanced = parser.add_argument_group("advanced")
    advanced.add_argument(
        "--dll-dir", type=str, default=None,
        help="Path to directory containing LunaHook DLLs. Default: lunahook/ next to this exe.",
    )
    advanced.add_argument(
        "--watch", action="store_true",
        help="Keep running even after the game process exits (wait for re-attach).",
    )

    return parser


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()

    # Resolve DLL directory
    dll_dir = args.dll_dir or os.path.join(BASE_DIR, "lunahook")
    dll_dir = os.path.abspath(dll_dir)

    if not os.path.isdir(dll_dir):
        print(f"ERROR: DLL directory not found: {dll_dir}", file=sys.stderr)
        print(f"Place the LunaHook DLLs in a 'lunahook/' folder next to this exe,", file=sys.stderr)
        print(f"or use --dll-dir to specify the path.", file=sys.stderr)
        sys.exit(1)

    # Validate PID
    pid = args.attach
    if not process_exists(pid):
        print(f"ERROR: Process {pid} does not exist or is not accessible.", file=sys.stderr)
        print(f"You may need to run this as Administrator.", file=sys.stderr)
        sys.exit(1)

    # Determine architecture
    if args.arch:
        is_64bit = args.arch == "64"
    else:
        is_64bit = is_process_64bit(pid)

    # Create formatter
    formatter = OutputFormatter(fmt=args.out_format, outfile=args.output)

    # Create engine
    engine = HookCLI(dll_dir, formatter)

    # Handle Ctrl+C gracefully
    shutting_down = threading.Event()

    def signal_handler(sig, frame):
        shutting_down.set()
        formatter.emit_event("shutting_down")

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal_handler)

    # Listen directly to stdin to detect a deliberate command or EOF from parent process
    def stdin_listener():
        try:
            for line in sys.stdin:
                if line.strip().lower() == 'quit':
                    break
        except Exception:
            pass
        finally:
            shutting_down.set()
            formatter.emit_event("shutting_down", reason="stdin closed or quit command")

    stdin_thread = threading.Thread(target=stdin_listener, daemon=True)
    stdin_thread.start()

    # Tell engine what to initialize upon _on_connect
    engine._startup_hookcodes = args.hookcode
    engine._startup_auto_hooks = args.auto_hooks

    # Start engine
    engine.start(
        delay=args.delay,
        codepage=args.codepage,
        max_buffer=args.max_buffer,
        max_history=args.max_history,
    )

    # Attach to process
    engine.attach(pid, is_64bit)

    # Wait a moment for connection to establish
    time.sleep(1.0)

    formatter.emit_event("listening", pid=pid, message="Advance dialogue in the game to see hooked text.")

    # Main loop — keep alive and watch for process exit
    try:
        while not shutting_down.is_set():
            if not args.watch and not process_exists(pid):
                formatter.emit_event("process_exited", pid=pid)
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutting_down.set()
    finally:
        formatter.emit_event("teardown_starting", message="Waiting for game DLL to process detach and fully disconnect...")
        engine.detach_all()
        
        # CRITICAL: We MUST wait for the OnDisconnect callback to fire before
        # allowing the process to exit. This callback fires in LunaHost's 
        # __handlepipethread ONLY after the game-side DLL has:
        #   1. Received HOST_COMMAND_DETACH via the named pipe
        #   2. Set running=false and exited its command parse loop  
        #   3. Either unloaded itself (FreeLibraryAndExitThread, releasing
        #      the ITH_HOOKMAN_MUTEX_ named mutex) OR looped back to 
        #      wait for a new host connection
        #   4. Closed its pipe handles, causing the host's ReadFile loop to end
        #
        # If we exit before this completes, the host-side pipes are ripped out
        # from under the game DLL. It receives a pipe-read failure instead of 
        # a clean DETACH command, leaving the named mutex and hook state in a
        # corrupted state that prevents ALL future reconnections (even Luna's).
        disconnect_timeout = 10.0
        if not engine._all_disconnected.wait(timeout=disconnect_timeout):
            formatter.emit_event("teardown_timeout", 
                message=f"Timed out after {disconnect_timeout}s waiting for disconnect callback. "
                        f"Remaining PIDs: {engine._attached_pids}")
        else:
            formatter.emit_event("teardown_complete", message="All processes cleanly disconnected.")
        
        # Small extra grace period for any final pipe I/O to flush
        time.sleep(0.3)
        
        formatter.close()
        # sys.exit cleanly finalizes threads, garbage collects objects/handles (such as CDLL),
        # instead of abruptly massacring process memory handles with os._exit(0)
        sys.exit(0)


if __name__ == "__main__":
    main()
