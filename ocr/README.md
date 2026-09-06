# ocr — image in, text in your terminal

Point it at an image; the text inside comes back on stdout. Add `--copy` and
it lands on the clipboard, or `--type` and it is keyed in at your prompt as if
you had typed it. Add `watch` and every screenshot you take turns into text
with no command at all.

Built on [Tesseract](https://github.com/tesseract-ocr/tesseract), called as a
subprocess — no Python OCR bindings to install.

## Install

```bash
sudo apt-get install tesseract-ocr        # Debian/Ubuntu  (brew install tesseract on macOS)
pip install pillow                        # optional: enables the --preset clean-ups

# optional, for the output channels beyond stdout
sudo apt-get install xclip                # --copy   on X11  (wl-clipboard on Wayland)
sudo apt-get install xdotool              # --type   on X11  (wtype on Wayland)

# extra languages, e.g. Telugu / Hindi
sudo apt-get install tesseract-ocr-tel tesseract-ocr-hin
```

`python3 ocr/run.py doctor` prints exactly which of those this machine has.

## Usage

```bash
python3 ocr/run.py read receipt.jpg               # text to stdout
python3 ocr/run.py receipt.jpg                    # same -- "read" is the default
python3 ocr/run.py read shot.png --preset screenshot --copy
python3 ocr/run.py read serial.png --digits --type       # types it at the prompt
python3 ocr/run.py read scan.png --lang eng+tel          # two scripts at once
python3 ocr/run.py read page.png --json                  # text + confidence + boxes
python3 ocr/run.py read "shots/*.png"                    # a batch
scrot -o /dev/stdout | python3 ocr/run.py read -         # straight off a pipe

python3 ocr/run.py watch ~/Pictures/Screenshots --copy    # hands-free
python3 ocr/run.py doctor
```

Also importable:

```python
from ocr import read_image

r = read_image("receipt.jpg", preset="photo", boxes=True)
print(r.text, r.confidence)        # 'Total 14,250.00 ...'  93.4
```

## The three ways text reaches you

| Flag | What happens | Needs |
|---|---|---|
| *(default)* | printed to stdout | nothing |
| `--copy` | on the system clipboard, ready to paste | xclip / xsel / wl-copy / pbcopy |
| `--type` | synthesised keystrokes — appears at the shell prompt | xdotool / wtype, or TIOCSTI on a bare tty |

`--type` is the literal "enter it in the terminal automatically" mode, and it
is the sharp one: characters pushed into a shell's input queue are characters
the shell runs as soon as it sees a newline. So **newlines are converted to
spaces** unless you pass `--allow-newlines`, which means a three-line OCR
result arrives as one editable line you still have to press Enter on. Don't
lift that guard for text you haven't read.

On a bare Linux console `--type` uses the `TIOCSTI` ioctl, which kernels since
6.2 gate behind `dev.tty.legacy_tiocsti` (off by default on most distros, for
exactly the reason above). `doctor` tells you whether it is available here.

## Presets

Tesseract expects dark text on a light background at roughly 300 DPI. Presets
(Pillow only) push an image toward that before OCR — grayscale, EXIF rotation,
auto-invert for light-on-dark, upscale, autocontrast, Otsu binarization, a
white margin — and each carries a sensible default page-segmentation mode.

| `--preset` | For | Does |
|---|---|---|
| `none` *(default)* | already-clean input | nothing; the file goes straight to Tesseract |
| `scan` | flatbed scans, PDFs rendered to PNG | binarize |
| `photo` | a phone photo of a page | upscale, sharpen, autocontrast |
| `screenshot` | UI and terminal grabs, dark mode included | upscale, treat as one text block |
| `captcha` | small, noisy, single-line images | upscale, sharpen, binarize, one-line mode |

Override any of it with `--psm`, `--oem`, `--whitelist`, `--invert`. Pair
`--min-conf 70` with `--json` when a script needs to know it can trust the read.

## Files

- `engine.py` — Tesseract subprocess wrapper: text, per-word boxes, confidence.
- `preprocess.py` — the presets; optional, degrades to a no-op without Pillow.
- `emit.py` — stdout / clipboard / keystroke delivery, and the newline guard.
- `run.py` — `read` / `watch` / `doctor` CLI.

## Not wired into the TS RERA captcha

`tsrera/` prompts a human to type its captcha on purpose — that hand cost is
what keeps automated load off a government server, and this module is
deliberately not plugged into it. Nothing here imports or is imported by
`tsrera/`.
