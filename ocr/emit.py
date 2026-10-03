"""Getting the recognised text *into* the terminal, not just onto it.

Three levels, in increasing order of how much they need from the environment:

  print   -- write to stdout. Always works, including over ssh and in pipes.
  copy    -- put it on the system clipboard, so one paste finishes the job.
  type    -- synthesise keystrokes so the text lands at the shell prompt (or in
             whatever window has focus) exactly as if it had been typed.

`type` is the "automatically" part, and it is the one with teeth: text pushed
into a shell's input queue is text the shell will run the moment it sees a
newline. So newlines are stripped unless the caller opts in explicitly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


class EmitError(RuntimeError):
    """No usable clipboard / keystroke backend on this machine."""


# --- clipboard ------------------------------------------------------------

# first entry whose binary exists wins
_CLIPBOARD = [
    ("pbcopy", ["pbcopy"]),                                   # macOS
    ("wl-copy", ["wl-copy"]),                                 # Wayland
    ("xclip", ["xclip", "-selection", "clipboard"]),          # X11
    ("xsel", ["xsel", "--clipboard", "--input"]),             # X11
    ("clip.exe", ["clip.exe"]),                               # WSL
]


def clipboard_backend() -> list[str] | None:
    for name, cmd in _CLIPBOARD:
        if shutil.which(name):
            return cmd
    return None


def copy(text: str) -> str:
    """Put `text` on the clipboard; returns the backend used."""
    cmd = clipboard_backend()
    if not cmd:
        raise EmitError(
            "no clipboard tool found. Install one of: "
            "xclip, xsel, wl-clipboard (Linux); pbcopy ships with macOS.")
    subprocess.run(cmd, input=text.encode(), check=True)
    return cmd[0]


# --- keystrokes -----------------------------------------------------------

def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def keystroke_backend() -> str | None:
    """Which typing mechanism this machine can actually use, if any."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wtype"):
        return "wtype"
    if os.environ.get("DISPLAY") and shutil.which("xdotool"):
        return "xdotool"
    if sys.stdin.isatty() and _tiocsti_allowed():
        return "tiocsti"
    return None


def _tiocsti_allowed() -> bool:
    """TIOCSTI pushes bytes into our own tty's input queue. Linux >= 6.2 gates
    it behind a sysctl that most distros now ship switched off."""
    try:
        import termios  # noqa: F401
    except ImportError:
        return False
    knob = "/proc/sys/dev/tty/legacy_tiocsti"
    try:
        with open(knob) as f:
            return f.read().strip() == "1"
    except FileNotFoundError:
        return sys.platform.startswith(("linux", "darwin", "freebsd"))
    except OSError:
        return False


def type_out(text: str, *, allow_newlines: bool = False, delay_ms: int = 12) -> str:
    """Type `text` as if on the keyboard; returns the backend used.

    Newlines are turned into spaces unless `allow_newlines` is set -- at a shell
    prompt a newline submits the line, so multi-line OCR output would otherwise
    run several lines of recognised text as commands.
    """
    if not allow_newlines:
        text = " ".join(text.split("\n"))
    backend = keystroke_backend()
    if backend == "xdotool":
        subprocess.run(["xdotool", "type", "--clearmodifiers",
                        "--delay", str(delay_ms), "--", text], check=True)
    elif backend == "wtype":
        subprocess.run(["wtype", "-d", str(delay_ms), "--", text], check=True)
    elif backend == "tiocsti":
        _push_to_tty(text)
    else:
        raise EmitError(
            "cannot synthesise keystrokes here.\n"
            "  X11     : sudo apt-get install xdotool\n"
            "  Wayland : sudo apt-get install wtype\n"
            "  bare tty: sudo sysctl -w dev.tty.legacy_tiocsti=1\n"
            "Otherwise use --copy (clipboard) or plain stdout.")
    return backend


def _push_to_tty(text: str) -> None:
    """Feed bytes back into this terminal's input queue, so they show up at the
    prompt as typed characters."""
    import fcntl
    import termios

    fd = sys.stdin.fileno()
    for byte in text.encode():
        fcntl.ioctl(fd, termios.TIOCSTI, bytes([byte]))


def preflight(*, to_clipboard: bool = False, as_keystrokes: bool = False) -> None:
    """Fail before any OCR work if a requested output channel is unusable, so a
    batch of images does not repeat the same error once per file."""
    if to_clipboard and clipboard_backend() is None:
        copy("")                # raises EmitError carrying the install hints
    if as_keystrokes and keystroke_backend() is None:
        type_out("")            # ditto


def deliver(text: str, *, to_stdout: bool = True, to_clipboard: bool = False,
            as_keystrokes: bool = False, allow_newlines: bool = False) -> list[str]:
    """Send `text` out over every channel asked for; returns what was used."""
    used = []
    if to_stdout:
        print(text)
        used.append("stdout")
    if to_clipboard:
        used.append(f"clipboard:{copy(text)}")
    if as_keystrokes:
        used.append(f"keystrokes:{type_out(text, allow_newlines=allow_newlines)}")
    return used
