"""Tesseract wrapper: image file in, text (or per-word boxes) out.

Talks to the `tesseract` binary over subprocess rather than importing
pytesseract, so the only hard dependency of this package is Tesseract itself.
Pillow is optional and used only for preprocessing (see `preprocess.py`).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

INSTALL_HINT = (
    "tesseract not found. Install it:\n"
    "  Debian/Ubuntu : sudo apt-get install tesseract-ocr\n"
    "  macOS         : brew install tesseract\n"
    "  Windows       : https://github.com/UB-Mannheim/tesseract/wiki\n"
    "Extra languages: apt-get install tesseract-ocr-<lang>  (e.g. -tel, -hin)"
)


class OcrError(RuntimeError):
    """OCR could not be run: engine missing, unreadable image, or a crash."""


@dataclass
class Options:
    """Everything that changes what Tesseract does to one image."""

    lang: str = "eng"
    psm: int = 3          # page segmentation mode; 6 = one uniform block
    oem: int = 3          # engine mode; 3 = default (LSTM + legacy if built)
    whitelist: str | None = None   # restrict recognised characters
    extra: tuple[str, ...] = ()    # raw `-c key=value` pairs

    def argv(self) -> list[str]:
        args = ["-l", self.lang, "--psm", str(self.psm), "--oem", str(self.oem)]
        if self.whitelist:
            args += ["-c", f"tessedit_char_whitelist={self.whitelist}"]
        for kv in self.extra:
            args += ["-c", kv]
        return args


@dataclass
class Word:
    """One recognised word with its box and confidence (0-100)."""

    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int
    line: int


@dataclass
class Result:
    """What `read()` gives back for a single image."""

    source: str
    text: str
    words: list[Word] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        """Mean confidence over recognised words, 0.0 when nothing was read."""
        scored = [w.conf for w in self.words if w.conf >= 0]
        return round(sum(scored) / len(scored), 1) if scored else 0.0

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "text": self.text,
            "confidence": self.confidence,
            "words": [w.__dict__ for w in self.words],
        }


def binary() -> str:
    """Path to the tesseract executable, or raise with install instructions."""
    exe = shutil.which("tesseract")
    if not exe:
        raise OcrError(INSTALL_HINT)
    return exe


def version() -> str:
    out = subprocess.run([binary(), "--version"], capture_output=True, text=True)
    return (out.stdout or out.stderr).splitlines()[0].strip()


def languages() -> list[str]:
    """Language packs Tesseract can see (`eng`, `tel`, `osd`, ...)."""
    out = subprocess.run([binary(), "--list-langs"], capture_output=True, text=True)
    return [l.strip() for l in out.stdout.splitlines()[1:] if l.strip()]


def _run(image: Path, opts: Options, fmt: str) -> str:
    """Run tesseract on `image`, asking for output format `fmt` on stdout."""
    cmd = [binary(), str(image), "stdout", *opts.argv()]
    if fmt != "txt":
        cmd.append(fmt)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        detail = err[-1] if err else f"exit {proc.returncode}"
        if "Failed loading language" in proc.stderr:
            detail += f"\navailable languages: {', '.join(languages()) or 'none'}"
        raise OcrError(f"tesseract failed on {image.name}: {detail}")
    return proc.stdout


def _parse_tsv(tsv: str) -> list[Word]:
    words: list[Word] = []
    for line in tsv.splitlines()[1:]:          # skip the header row
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        text = cols[11].strip()
        if not text:
            continue
        try:
            words.append(Word(
                text=text,
                conf=float(cols[10]),
                left=int(cols[6]), top=int(cols[7]),
                width=int(cols[8]), height=int(cols[9]),
                line=int(cols[4]),
            ))
        except ValueError:                      # malformed row; skip it
            continue
    return words


def read(image: Path, opts: Options | None = None, *, boxes: bool = False) -> Result:
    """OCR one image file.

    `boxes=True` also returns per-word confidences and positions, which costs a
    second Tesseract pass.
    """
    image = Path(image)
    if not image.is_file():
        raise OcrError(f"no such image: {image}")
    opts = opts or Options()
    text = tidy(_run(image, opts, "txt"))
    words = _parse_tsv(_run(image, opts, "tsv")) if boxes else []
    return Result(source=str(image), text=text, words=words)


def tidy(text: str) -> str:
    """Strip trailing spaces per line and collapse the blank lines Tesseract
    likes to pad output with, without touching the words themselves."""
    lines = [l.rstrip() for l in text.replace("\f", "").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    out, blanks = [], 0
    for line in lines:
        blanks = blanks + 1 if not line else 0
        if blanks < 2:
            out.append(line)
    return "\n".join(out)
