"""Native folder chooser for the learning workspace.

Why this exists: the learning UI runs inside a browser engine, so a dropped
folder or a browser-picked directory never exposes a real absolute path back to
the page. The server runs on the same desktop (it binds 127.0.0.1 only), so it
can raise a proper desktop dialog and return the path over the API.

Safety rules, because a misbehaving chooser takes the whole session with it:

* Only one dialog at a time; a second request is rejected instead of stacking
  windows that fight over the input focus.
* The dialog is spawned as its own session leader, so it never joins the
  server's process group and cannot take the server down when it exits.
* Whatever the desktop provides is used; if nothing works the API raises and
  the page falls back to typing a path, which always works.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

# The dialog stays open for as long as the user needs. This only bounds the
# pathological case where a chooser starts but never returns.
DIALOG_TIMEOUT = 900

_lock = threading.Lock()


class DialogUnavailable(ValueError):
    """No usable native chooser on this machine.

    Subclasses ValueError so the server's existing 400 handler renders it as a
    readable message instead of an unhandled crash.
    """


def has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _spawn(command: list[str]) -> str | None:
    """Run a chooser to completion and return its output.

    Returns None when the binary is missing or produced nothing usable, so the
    caller can move on to the next candidate.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DIALOG_TIMEOUT,
            check=False,
            # Own session: the dialog must not inherit the server's group, and
            # must not be able to signal it. GTK_A11Y avoids the a11y-bus noise
            # Deepin logs on every GTK spin-up.
            start_new_session=True,
            env={**os.environ, "GTK_A11Y": "none"},
        )
    except (FileNotFoundError, PermissionError):
        return None
    except subprocess.TimeoutExpired:
        return None

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0:
        # zenity / kdialog / tkinter all exit non-zero on "cancel". That is a
        # normal answer, not a broken chooser, so keep it distinguishable.
        return "" if not lines else lines[0]
    return lines[0] if lines else ""


def _zenity(initial: str) -> str | None:
    return _spawn(
        [
            "zenity",
            "--file-selection",
            "--directory",
            "--title=选择视频工程目录",
            "--filename=" + (initial.rstrip("/") + "/" if initial else ""),
        ]
    )


def _kdialog(initial: str) -> str | None:
    return _spawn(["kdialog", "--getexistingdirectory", initial, "--title", "选择视频工程目录"])


def _tkinter(initial: str) -> str | None:
    """Tk fallback, isolated in a child process so no GUI state leaks in."""
    script = (
        "import sys, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk(); root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        "picked = filedialog.askdirectory(title='选择视频工程目录', initialdir=sys.argv[1] or None)\n"
        "print(picked or '')\n"
    )
    return _spawn(["python3", "-c", script, initial])


def _candidates() -> list:
    found = []
    if shutil.which("zenity"):
        found.append(_zenity)
    if shutil.which("kdialog"):
        found.append(_kdialog)
    if shutil.which("python3"):
        found.append(_tkinter)
    return found


def pick_directory(initial: str = "") -> str:
    """Raise a desktop folder chooser and return the absolute path.

    Returns "" when the user cancelled. Raises DialogUnavailable (a ValueError,
    so the API answers 400) when the machine has no chooser or one is already
    open.
    """
    if not has_display():
        raise DialogUnavailable("当前环境没有图形界面，无法弹出目录选择框，请手动填写路径")

    if not _lock.acquire(blocking=False):
        raise DialogUnavailable("已有目录选择框打开，请先在其中完成或取消")

    try:
        start = ""
        if initial:
            path = Path(initial).expanduser()
            start = str(path if path.is_dir() else path.parent)
        if not start or not Path(start).is_dir():
            start = str(Path.home())

        for chooser in _candidates():
            picked = chooser(start)
            if picked is None:
                continue
            if picked == "":
                return ""
            path = Path(picked).expanduser()
            if path.is_dir():
                return str(path.resolve())
            raise ValueError("选择的不是目录")

        raise DialogUnavailable("未找到可用的目录选择框，请手动填写路径")
    finally:
        _lock.release()
