"""Interactive prompts that work even when stdin is a pipe (curl | bash)."""

from __future__ import annotations

import sys
from typing import TextIO


def _tty_infile() -> TextIO:
    """Prefer /dev/tty so prompts work when installed via `curl | bash`."""
    if sys.stdin.isatty():
        return sys.stdin
    try:
        return open("/dev/tty", "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(
            "No interactive terminal available. "
            "Run with: sudo bash install.sh   "
            "or: bash <(curl -fsSL https://raw.githubusercontent.com/AliZolfaghar/azautov2ray/main/install.sh)"
        ) from exc


def read_line(prompt: str = "") -> str:
    """Print prompt to stderr/stdout and read one line from the real TTY."""
    if prompt:
        # Write prompts to stderr so they still show when stdout is redirected
        sys.stderr.write(prompt)
        sys.stderr.flush()
    infile = _tty_infile()
    try:
        line = infile.readline()
    finally:
        if infile is not sys.stdin:
            infile.close()
    if line == "":
        raise EOFError(
            "EOF while reading from terminal. "
            "Use an interactive SSH session, or: bash <(curl -fsSL .../install.sh)"
        )
    return line.rstrip("\r\n")


def ask(prompt: str, default: str | None = None, *, allow_empty: bool = False) -> str:
    """Ask for a value. If default is provided (even ""), Enter keeps/accepts it."""
    if default is not None:
        suffix = f" [{default}]" if default != "" else " [Enter to skip]"
        raw = read_line(f"{prompt}{suffix}: ").strip()
        return raw if raw else default
    while True:
        raw = read_line(f"{prompt}: ").strip()
        if raw or allow_empty:
            return raw
        sys.stderr.write("  Value required.\n")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = read_line(f"{prompt} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def ask_int(prompt: str, default: int) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            sys.stderr.write("  Enter a number.\n")


def ask_multiline(prompt: str) -> list[str]:
    print(prompt)
    print("  (enter one URL per line; empty line to finish)")
    lines: list[str] = []
    while True:
        line = read_line("  > ").strip()
        if not line:
            break
        lines.append(line)
    return lines


def pause(message: str = "\nPress Enter to continue...") -> None:
    try:
        read_line(message)
    except EOFError:
        pass
