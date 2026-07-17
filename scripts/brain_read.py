#!/usr/bin/env python3
"""Print bounded excerpts from the Hermes brain bus for cron/chat prompts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR, SECTIONS  # noqa: E402


def _filter_product(text: str, product: str) -> str:
    if not product:
        return text
    lines = text.splitlines()
    keep = []
    taking = False
    prod = product.lower()
    for line in lines:
        if line.startswith("#"):
            taking = prod in line.lower()
            if taking:
                keep.append(line)
            continue
        if taking:
            keep.append(line)
        elif prod in line.lower():
            keep.append(line)
    return "\n".join(keep) if keep else text


def read_section(name: str, product: str | None, max_chars: int) -> str:
    key = name.upper()
    if key not in SECTIONS:
        return f"[unknown section: {name}]"
    path = BRAIN_DIR / SECTIONS[key]
    if not path.exists():
        return f"## {key}\n\n(empty — file missing)\n"
    text = path.read_text(encoding="utf-8")
    if product:
        text = _filter_product(text, product)
    if len(text) > max_chars:
        text = text[: max_chars - 20].rstrip() + "\n\n…[truncated]…\n"
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Hermes brain sections")
    parser.add_argument(
        "--sections",
        default="INDEX,PRODUCTS,MARKET,BUYERS,PIPELINES,DECISIONS",
        help="Comma-separated section names",
    )
    parser.add_argument("--product", default="", help="Optional product filter")
    parser.add_argument("--max-chars", type=int, default=4000, help="Max chars per section")
    args = parser.parse_args()

    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    names = [s.strip() for s in args.sections.split(",") if s.strip()]
    chunks = []
    for name in names:
        chunks.append(read_section(name, args.product or None, args.max_chars))
        chunks.append("")
    sys.stdout.write("\n".join(chunks).rstrip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
