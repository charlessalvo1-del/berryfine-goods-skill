#!/usr/bin/env python3
"""Render labeled manifest photo windows for blind sequence review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--manifest", required=True, type=Path)
    value.add_argument("--photos", required=True, type=Path)
    value.add_argument("--output", required=True, type=Path)
    value.add_argument("--start", required=True, type=int)
    value.add_argument("--count", default=18, type=int)
    value.add_argument("--columns", default=3, type=int)
    value.add_argument("--cell-width", default=420, type=int)
    value.add_argument("--cell-height", default=360, type=int)
    return value


def main() -> int:
    args = parser().parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    photos = payload.get("photos", [])
    selected = photos[args.start - 1 : args.start - 1 + args.count]
    rows = (len(selected) + args.columns - 1) // args.columns
    sheet = Image.new("RGB", (args.columns * args.cell_width, rows * args.cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for offset, record in enumerate(selected):
        sequence = args.start + offset
        source = args.photos / record["relative_path"]
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((args.cell_width - 16, args.cell_height - 56), Image.Resampling.LANCZOS)
        x = (offset % args.columns) * args.cell_width
        y = (offset // args.columns) * args.cell_height
        px = x + (args.cell_width - image.width) // 2
        py = y + 38 + (args.cell_height - 46 - image.height) // 2
        sheet.paste(image, (px, py))
        label = f"{sequence:04d}  {Path(record['relative_path']).name}"
        draw.text((x + 8, y + 8), label, fill="black", font=font)
        draw.rectangle((x, y, x + args.cell_width - 1, y + args.cell_height - 1), outline="#666666", width=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
