"""Render the family tree page: pages/family_tree.html with family_tree.json inlined.

Usage: uv run python -I pages/family_tree_page.py FAMILY_TREE.json OUT.html
"""

import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "family_tree.html"


def main() -> None:
    tree, out = Path(sys.argv[1]), Path(sys.argv[2])
    data = tree.read_text()
    page = TEMPLATE.read_text()
    if page.count("/*DATA*/null") != 1:
        sys.exit(f"{TEMPLATE}: expected one /*DATA*/null placeholder")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.replace("/*DATA*/null", data.strip().replace("</", "<\\/")))
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
