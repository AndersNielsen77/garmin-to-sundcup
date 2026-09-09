"""A dependency-free checkbox list for the terminal.

Arrow keys (or j/k) move, space toggles, enter confirms, q/Esc cancels.
Falls back to a numbered prompt on terminals that cannot be put in cbreak
mode, and the caller is expected to skip it entirely when not on a TTY.
"""

from __future__ import annotations

import os
import sys
import termios
import tty
from dataclasses import dataclass
from select import select as _wait

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR_LINE = "\x1b[2K"
REVERSE = "\x1b[7m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


@dataclass
class Choice:
    label: str
    selected: bool
    hint: str = ""


def _read_key(fd: int) -> str:
    # Read the fd directly: sys.stdin's buffer would swallow a whole burst of
    # keystrokes, and then the readiness check below would see an empty fd.
    ch = os.read(fd, 1)
    if not ch:
        return ""
    if ch != b"\x1b":
        return ch.decode(errors="ignore")
    # Escape sequence, or a bare Esc if nothing follows within a moment.
    if not _wait([fd], [], [], 0.05)[0]:
        return "esc"
    return {b"[A": "up", b"[B": "down"}.get(os.read(fd, 2), "esc")


def _render(choices: list[Choice], cursor: int, first: bool) -> None:
    if not first:
        sys.stdout.write(f"\x1b[{len(choices)}A")
    for i, c in enumerate(choices):
        mark = "x" if c.selected else " "
        row = f"{'>' if i == cursor else ' '}[{mark}] {c.label}"
        if c.hint:
            row += f"  {DIM}{c.hint}{RESET}"
        sys.stdout.write(CLEAR_LINE + (REVERSE + row + RESET if i == cursor else row) + "\n")
    sys.stdout.flush()


def _select_raw(choices: list[Choice]) -> list[Choice] | None:
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    sys.stdout.write(HIDE_CURSOR)
    cursor = 0
    try:
        tty.setcbreak(fd)
        _render(choices, cursor, first=True)
        while True:
            key = _read_key(fd)
            if key in ("up", "k"):
                cursor = (cursor - 1) % len(choices)
            elif key in ("down", "j"):
                cursor = (cursor + 1) % len(choices)
            elif key == " ":
                choices[cursor].selected = not choices[cursor].selected
            elif key in ("a", "A"):
                for c in choices:
                    c.selected = True
            elif key in ("n", "N"):
                for c in choices:
                    c.selected = False
            elif key in ("\r", "\n"):
                return choices
            elif key in ("q", "Q", "esc", "\x03", "\x04", ""):
                return None
            _render(choices, cursor, first=False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()


def _select_numbered(choices: list[Choice]) -> list[Choice] | None:
    for i, c in enumerate(choices, 1):
        mark = "x" if c.selected else " "
        print(f" {i:>2}. [{mark}] {c.label}" + (f"  ({c.hint})" if c.hint else ""))
    print("Numbers to toggle (e.g. '1 3'), 'a' all, 'n' none, empty to accept, 'q' to cancel.")
    while True:
        try:
            reply = input("> ").strip()
        except EOFError:
            return None
        if not reply:
            return choices
        if reply in ("q", "Q"):
            return None
        if reply in ("a", "A", "n", "N"):
            for c in choices:
                c.selected = reply in ("a", "A")
        else:
            try:
                picks = [int(tok) for tok in reply.replace(",", " ").split()]
            except ValueError:
                print("Not a number.")
                continue
            for i in picks:
                if 1 <= i <= len(choices):
                    choices[i - 1].selected = not choices[i - 1].selected
        for i, c in enumerate(choices, 1):
            print(f" {i:>2}. [{'x' if c.selected else ' '}] {c.label}")


def select(title: str, choices: list[Choice]) -> list[Choice] | None:
    """Let the user tick boxes. Returns the choices, or None if cancelled."""
    if not choices:
        return choices
    print(title)
    try:
        return _select_raw(choices)
    except (termios.error, OSError):
        return _select_numbered(choices)
