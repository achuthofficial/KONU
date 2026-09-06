"""OCR an image and put its text in the terminal, automatically.

  read    -- OCR one or more images (or `-` for an image piped on stdin) and
             print the text. `--copy` also puts it on the clipboard, `--type`
             types it at the prompt as if you had keyed it in yourself.

  watch   -- sit on a directory and OCR every new image that lands in it. Point
             it at your screenshots folder and any grab you take is text a
             moment later, with no command to run.

  doctor  -- report what this machine can do: engine version, language packs,
             preprocessing, clipboard and keystroke backends.

Usage:
  python3 ocr/run.py read receipt.jpg
  python3 ocr/run.py read shot.png --preset screenshot --copy
  python3 ocr/run.py read code.png --digits --type       # types it at the prompt
  python3 ocr/run.py watch ~/Pictures/Screenshots --copy
  python3 ocr/run.py doctor
"""

from __future__ import annotations

import argparse
import glob as globlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import emit, engine, preprocess
from ocr.engine import OcrError, Options

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif",
                  ".webp", ".pnm", ".pbm", ".pgm", ".ppm"}
DIGITS = "0123456789"


def _options(args) -> Options:
    whitelist = args.whitelist
    if args.digits:
        whitelist = (whitelist or "") + DIGITS
    psm = args.psm if args.psm is not None else preprocess.suggested_psm(args.preset)
    return Options(lang=args.lang, psm=psm, oem=args.oem, whitelist=whitelist or None)


def _stdin_to_file(workdir: Path) -> Path:
    """Slurp an image piped on stdin into a real file -- Tesseract wants a path."""
    data = sys.stdin.buffer.read()
    if not data:
        raise OcrError("nothing on stdin")
    path = workdir / "stdin.img"
    path.write_bytes(data)
    return path


def _read_one(src: Path, args, workdir: Path) -> engine.Result:
    prepared = preprocess.prepare(src, workdir, args.preset, invert=args.invert)
    needs_scores = args.conf or args.json or args.min_conf > 0
    result = engine.read(prepared, _options(args), boxes=needs_scores)
    result.source = str(src)
    return result


def _report(result: engine.Result, args, *, label: bool) -> None:
    """Hand one result to the user over whichever channels they asked for."""
    if not result.text.strip():
        print(f"[{Path(result.source).name}: no text found]", file=sys.stderr)
        return
    if args.min_conf and result.confidence < args.min_conf:
        print(f"[{Path(result.source).name}: confidence {result.confidence} "
              f"below --min-conf {args.min_conf}, skipped]", file=sys.stderr)
        return
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    elif label:
        print(f"--- {result.source} ---", file=sys.stderr)
    used = emit.deliver(
        result.text,
        to_stdout=not (args.quiet or args.json),
        to_clipboard=args.copy,
        as_keystrokes=args.type,
        allow_newlines=args.allow_newlines,
    )
    if args.conf:
        print(f"[confidence {result.confidence} | {len(result.words)} words | "
              f"{', '.join(used)}]", file=sys.stderr)


def read(args) -> int:
    with tempfile.TemporaryDirectory(prefix="ocr-") as tmp:
        workdir = Path(tmp)
        sources: list[Path] = []
        for raw in args.images:
            if raw == "-":
                sources.append(_stdin_to_file(workdir))
            elif any(ch in raw for ch in "*?["):
                # the shell usually expands these; this covers quoted patterns
                # and absolute ones, which Path.glob refuses.
                sources.extend(Path(m) for m in sorted(globlib.glob(raw)))
            else:
                sources.append(Path(raw))
        if not sources:
            print("no images matched", file=sys.stderr)
            return 1
        emit.preflight(to_clipboard=args.copy, as_keystrokes=args.type)

        failures = 0
        for src in sources:
            try:
                _report(_read_one(src, args, workdir), args, label=len(sources) > 1)
            except OcrError as e:
                print(f"error: {e}", file=sys.stderr)
                failures += 1
    return 1 if failures else 0


def watch(args) -> int:
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"not a directory: {folder}", file=sys.stderr)
        return 1

    def images() -> set[Path]:
        return {p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES}

    emit.preflight(to_clipboard=args.copy, as_keystrokes=args.type)
    seen = set() if args.backlog else images()
    print(f"watching {folder} (every {args.interval}s, {len(seen)} existing files "
          f"ignored) -- ctrl-c to stop", file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="ocr-") as tmp:
        workdir = Path(tmp)
        try:
            while True:
                for path in sorted(images() - seen, key=lambda p: p.stat().st_mtime):
                    seen.add(path)
                    _settle(path)
                    try:
                        _report(_read_one(path, args, workdir), args, label=True)
                    except (OcrError, emit.EmitError) as e:
                        print(f"error: {e}", file=sys.stderr)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nstopped", file=sys.stderr)
    return 0


def _settle(path: Path, timeout: float = 5.0) -> None:
    """Wait until the file stops growing -- a screenshot tool may still be
    writing it when we first notice the name."""
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        size = path.stat().st_size
        if size == last and size > 0:
            return
        last = size
        time.sleep(0.15)


def doctor(_args) -> int:
    try:
        print(f"engine       : {engine.version()}")
        langs = engine.languages()
        print(f"languages    : {', '.join(langs) if langs else '(none installed)'}")
    except OcrError as e:
        print(f"engine       : MISSING\n{e}")
        return 1
    print(f"preprocessing: {'Pillow available' if preprocess.available() else preprocess.PILLOW_HINT}")
    clip = emit.clipboard_backend()
    print(f"clipboard    : {clip[0] if clip else 'none (install xclip / wl-clipboard)'}")
    keys = emit.keystroke_backend()
    print(f"keystrokes   : {keys or 'none (install xdotool / wtype, or enable TIOCSTI)'}")
    print(f"presets      : {', '.join(preprocess.PRESETS)}")
    return 0


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lang", default="eng", help="tesseract language, e.g. eng, tel, eng+tel")
    p.add_argument("--preset", default="none", choices=list(preprocess.PRESETS),
                   help="image clean-up profile (default: none)")
    p.add_argument("--psm", type=int, default=None,
                   help="page segmentation mode; overrides the preset's choice")
    p.add_argument("--oem", type=int, default=3, help="tesseract engine mode")
    p.add_argument("--whitelist", default=None, help="only recognise these characters")
    p.add_argument("--digits", action="store_true", help="digits only (shorthand)")
    p.add_argument("--invert", action="store_true",
                   help="force invert (light text on a dark background)")
    p.add_argument("--copy", action="store_true", help="also copy the text to the clipboard")
    p.add_argument("--type", action="store_true",
                   help="also type the text at the prompt as synthetic keystrokes")
    p.add_argument("--allow-newlines", action="store_true",
                   help="with --type, send newlines too (a shell will RUN each line)")
    p.add_argument("--quiet", action="store_true", help="do not print the text to stdout")
    p.add_argument("--conf", action="store_true", help="print confidence to stderr")
    p.add_argument("--min-conf", type=float, default=0.0,
                   help="skip results below this mean confidence (0-100)")
    p.add_argument("--json", action="store_true",
                   help="emit text + confidence + word boxes as JSON")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ocr", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("read", help="OCR one or more images")
    r.add_argument("images", nargs="+", help="image paths, a glob, or - for stdin")
    _add_common(r)

    w = sub.add_parser("watch", help="OCR every new image dropped in a folder")
    w.add_argument("folder", help="directory to watch")
    w.add_argument("--interval", type=float, default=1.0, help="poll seconds")
    w.add_argument("--backlog", action="store_true",
                   help="also process images already in the folder")
    _add_common(w)

    sub.add_parser("doctor", help="show what OCR support this machine has")

    argv = list(sys.argv[1:] if argv is None else argv)
    # Convenience: `ocr/run.py shot.png` means `ocr/run.py read shot.png`.
    if argv and argv[0] not in {"read", "watch", "doctor", "-h", "--help"} \
            and not argv[0].startswith("-"):
        argv.insert(0, "read")

    args = ap.parse_args(argv)
    try:
        return {"read": read, "watch": watch, "doctor": doctor}[args.cmd](args)
    except (OcrError, emit.EmitError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
