"""Set `guidance_page` of every requirement (and general principle) of a catalogue from its bundled guidance PDF.

Usage:  python scripts/assign_guidance_pages.py data/guidance/food-enzymes/cep_2021_6851_requirements.json [--check]

The page is the first page on which the requirement's quote is found verbatim (whitespace- and hyphen-insensitive,
as in tests/test_characterisation*.py). A quote split over two pages is accepted on the page where it starts.
With --check nothing is written; the script exits 1 if a quote is not found or a stored page differs.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import characterisation as c  # noqa: E402


def _compact(text: str) -> str:
    return c._compact(c._fix_ligatures(text))[0]


def locate(quote: str, pages: list[str]) -> int:
    parts = [p for p in quote.split("[...]") if p.strip()]
    needle = _compact(parts[0])
    for i, page in enumerate(pages, start=1):
        if needle in _compact(page):
            return i
    # quote running over a page break
    joined = [_compact(p) for p in pages]
    for i in range(len(joined) - 1):
        if needle in joined[i] + joined[i + 1]:
            return i + 1
    return 0


def main() -> int:
    path = Path(sys.argv[1])
    check = "--check" in sys.argv
    cat = json.loads(path.read_text(encoding="utf-8"))
    pages = c.load_pdf_pages(path.parent / cat["guidance"]["bundled_file"])
    if not pages:
        print(f"bundled PDF {cat['guidance']['bundled_file']} missing or unreadable")
        return 1
    bad = 0
    items = [(r["id"], r) for r in cat["requirements"]] + [(f"general {g['section']}", g) for g in cat["guidance"].get("general_principles", [])]
    for name, item in items:
        page = locate(item["quote"], pages)
        key = "guidance_page" if "id" in item else "page"
        if not page:
            print(f"NOT FOUND {name}: {item['quote'][:80]}")
            bad += 1
        elif item.get(key) != page:
            print(f"{'DIFFERS' if check else 'set'} {name}: {item.get(key)} -> {page}")
            bad += check
            item[key] = page
    if not check:
        path.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
