#!/usr/bin/env python3
"""Atomic writes into the Hermes brain bus."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR, DEFAULT_BUDGETS, SECTIONS  # noqa: E402


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp"
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _trim(content: str, budget: int) -> str:
    if len(content) <= budget:
        return content
    return content[: budget - 30].rstrip() + "\n\n…[trimmed to budget]…\n"


def replace_section(text: str, heading: str, body: str) -> str:
    pattern = re.compile(
        rf"(^## {re.escape(heading)}\s*\n)(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    block = f"## {heading}\n\n{body.rstrip()}\n\n"
    if pattern.search(text):
        return pattern.sub(block, text, count=1)
    return text.rstrip() + "\n\n" + block


def main() -> int:
    parser = argparse.ArgumentParser(description="Write Hermes brain files")
    parser.add_argument("file", help="Section name (PRODUCTS) or filename (PRODUCTS.md)")
    parser.add_argument("--append", action="store_true", help="Append stamped note")
    parser.add_argument("--replace-section", default="", help="Replace ## section heading")
    parser.add_argument("--text", default="", help="Inline text (else stdin)")
    parser.add_argument("--stdin", action="store_true", help="Read body from stdin")
    args = parser.parse_args()

    name = args.file
    if name.upper() in SECTIONS:
        path = BRAIN_DIR / SECTIONS[name.upper()]
    elif name.endswith(".md"):
        path = BRAIN_DIR / name
    else:
        path = BRAIN_DIR / f"{name}.md"

    body = args.text
    if args.stdin or not body:
        if not args.text:
            body = sys.stdin.read()
    body = body.strip()
    if not body:
        print("empty body", file=sys.stderr)
        return 1

    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem}\n\n"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if args.replace_section:
        content = replace_section(existing, args.replace_section, body)
    elif args.append:
        note = f"\n### {stamp}\n\n{body}\n"
        content = existing.rstrip() + "\n" + note + "\n"
    else:
        content = body if body.lstrip().startswith("#") else f"# {path.stem}\n\n{body}\n"

    budget = DEFAULT_BUDGETS.get(path.name, 12000)
    content = _trim(content, budget)
    _atomic_write(path, content)

    index = BRAIN_DIR / "INDEX.md"
    idx = index.read_text(encoding="utf-8") if index.exists() else "# INDEX\n\n"
    line = f"- `{path.name}` updated {stamp}"
    if f"`{path.name}`" in idx:
        idx = re.sub(rf"- `{re.escape(path.name)}` updated .*", line, idx)
    else:
        idx = idx.rstrip() + "\n" + line + "\n"
    _atomic_write(index, _trim(idx, DEFAULT_BUDGETS["INDEX.md"]))

    print(f"wrote {path} ({len(content)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
