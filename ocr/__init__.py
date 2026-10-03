"""Read text out of an image and put it in the terminal.

    from ocr import read_image
    print(read_image("receipt.jpg", preset="photo").text)

Command line:  python3 -m ocr read receipt.jpg --copy
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ocr import emit, engine, preprocess
from ocr.engine import OcrError, Options, Result, Word

__all__ = ["read_image", "OcrError", "Options", "Result", "Word",
           "emit", "engine", "preprocess"]


def read_image(path: str | Path, *, lang: str = "eng", preset: str = "none",
               psm: int | None = None, whitelist: str | None = None,
               invert: bool = False, boxes: bool = False) -> Result:
    """OCR a single image, applying the named preprocessing preset first."""
    src = Path(path)
    opts = Options(
        lang=lang,
        psm=psm if psm is not None else preprocess.suggested_psm(preset),
        whitelist=whitelist,
    )
    with tempfile.TemporaryDirectory(prefix="ocr-") as tmp:
        prepared = preprocess.prepare(src, Path(tmp), preset, invert=invert)
        result = engine.read(prepared, opts, boxes=boxes)
    result.source = str(src)
    return result
