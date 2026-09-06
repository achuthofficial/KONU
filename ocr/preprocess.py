"""Optional image clean-up before OCR.

Tesseract is trained on ~300 DPI black-on-white text. Anything else -- a phone
photo, a screenshot at 1x, light text on a dark terminal, a small captcha --
reads better after a pass through here. Needs Pillow; without it every preset
degrades to "hand the original file to Tesseract", which still works.
"""

from __future__ import annotations

from pathlib import Path

try:                                            # Pillow is optional
    from PIL import Image, ImageFilter, ImageOps
except ImportError:                             # pragma: no cover - env dependent
    Image = None

PILLOW_HINT = "preprocessing needs Pillow:  pip install pillow"

# name -> (min target height in px, binarize?, sharpen?, recommended psm)
PRESETS: dict[str, tuple[int, bool, bool, int]] = {
    "none":       (0,    False, False, 3),
    "scan":       (0,    True,  False, 3),   # already flat, just crush to b/w
    "photo":      (1200, False, True,  3),   # phone photo of a page
    "screenshot": (1000, False, False, 6),   # crisp pixels, often small
    "captcha":    (120,  True,  True,  7),   # tiny, noisy, one line
}


def available() -> bool:
    return Image is not None


def suggested_psm(preset: str) -> int:
    return PRESETS.get(preset, PRESETS["none"])[3]


def prepare(src: Path, workdir: Path, preset: str = "none",
            *, invert: bool = False) -> Path:
    """Return a path to the image Tesseract should actually read.

    That is `src` itself when there is nothing to do (or no Pillow), otherwise a
    cleaned-up PNG written into `workdir`.
    """
    src = Path(src)
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; pick one of {', '.join(PRESETS)}")
    if not available() or (preset == "none" and not invert):
        return src

    target_h, binarize, sharpen, _psm = PRESETS[preset]
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)          # honour phone-camera rotation
    img = img.convert("L")                      # grayscale

    if invert or _mostly_dark(img):
        img = ImageOps.invert(img)              # OCR wants dark text on light

    if target_h and img.height < target_h:
        scale = min(target_h / img.height, 4.0)
        img = img.resize((int(img.width * scale), int(img.height * scale)),
                         Image.LANCZOS)

    img = ImageOps.autocontrast(img, cutoff=1)
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    if binarize:
        img = img.point(lambda p: 255 if p > _otsu(img) else 0, mode="L")

    img = ImageOps.expand(img, border=20, fill=255)   # margin helps line finding

    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"{src.stem}.prepared.png"
    img.save(out)
    return out


def _mostly_dark(img) -> bool:
    """True for light-on-dark images (terminal grabs, dark-mode screenshots)."""
    hist = img.histogram()
    dark = sum(hist[:96])
    light = sum(hist[160:])
    return dark > light * 1.5


def _otsu(img) -> int:
    """Otsu's threshold over the image histogram."""
    hist = img.histogram()[:256]
    total = sum(hist) or 1
    sum_all = sum(i * h for i, h in enumerate(hist))
    w_b = sum_b = 0
    best, threshold = -1.0, 128
    for i, h in enumerate(hist):
        w_b += h
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * h
        var = w_b * w_f * (sum_b / w_b - (sum_all - sum_b) / w_f) ** 2
        if var > best:
            best, threshold = var, i
    return threshold
