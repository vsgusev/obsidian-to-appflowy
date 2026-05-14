"""
Obsidian markdown → AppFlowy block-JSON converter.

Handles:
  - Headings, paragraphs, bullet/numbered lists (with nesting)
  - Fenced code blocks
  - Horizontal rules (dividers)
  - Inline formatting: bold, italic, strikethrough, inline code, links
  - Obsidian wikilinks  [[Note]]  [[Note|Alias]]
  - Images  ![[file.png]]  ![[file.png|300]]  ![alt](path)
  - Markdown tables  -> simple_table blocks
"""

import re
import sys
from pathlib import Path
from typing import Callable

# ── Regex helpers ────────────────────────────────────────────────────────────

_IMG_EXT = r"\.(?:png|jpe?g|gif|webp|svg|bmp)"
_RE_WIKI_IMG    = re.compile(rf"!\[\[(.+?{_IMG_EXT})(?:\|[^\]]+)?\]\]", re.IGNORECASE)
_RE_MD_IMG      = re.compile(rf"!\[.*?\]\((.+?{_IMG_EXT})\)", re.IGNORECASE)
_RE_WIKI_LINK   = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_RE_TABLE_SEP   = re.compile(r"^\s*\|?[\s\-:|]+(\|[\s\-:|]+)*\|?\s*$")
_RE_LIST_BULLET  = re.compile(r"^(\s*)([-*+])\s+(.*)")
_RE_LIST_NUMBERED = re.compile(r"^(\s*)(\d+\.)\s+(.*)")


# ── Inline delta parser ───────────────────────────────────────────────────────

_INLINE_RE = re.compile(
    r"__(.+?)__"               # bold (underscore)
    r"|\*\*(.+?)\*\*"          # bold (asterisk)
    r"|_(.+?)_"                # italic (underscore)
    r"|\*(.+?)\*"              # italic (asterisk)
    r"|~~(.+?)~~"              # strikethrough
    r"|`(.+?)`"                # inline code
    r"|\[(.+?)\]\((.+?)\)"    # [text](url)
    r"|([^*_~`\[]+)"           # plain text
)


def parse_inline(text: str) -> list[dict]:
    """Convert inline markdown to a list of Quill delta ops."""
    ops: list[dict] = []
    for m in _INLINE_RE.finditer(text):
        bold_ul, bold_ast, italic_ul, italic_ast, strike, code, link_text, link_url, plain = m.groups()
        bold = bold_ul or bold_ast
        italic = italic_ul or italic_ast
        if bold:
            ops.append({"insert": bold, "attributes": {"bold": True}})
        elif italic:
            ops.append({"insert": italic, "attributes": {"italic": True}})
        elif strike:
            ops.append({"insert": strike, "attributes": {"strikethrough": True}})
        elif code:
            ops.append({"insert": code, "attributes": {"code": True}})
        elif link_text and link_url:
            ops.append({"insert": link_text, "attributes": {"href": link_url}})
        elif plain:
            ops.append({"insert": plain})
    return ops or [{"insert": ""}]


# ── Frontmatter stripper ──────────────────────────────────────────────────────

def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from the start of the document."""
    if not text.startswith("---"):
        return text
    close = text.find("\n---", 3)
    if close == -1:
        return text
    return text[close + 4:].lstrip("\n")


# ── Wikilink / obsidian embed pre-processing ──────────────────────────────────

def _preprocess_obsidian(
    text: str,
    image_index: dict[str, Path],
    missing_images: list[str] | None = None,
) -> str:
    """
    Convert Obsidian-specific syntax to standard markdown before block parsing.

    ![[img.png|300]]  →  ![](resolved/path/img.png)   (resolved via image_index)
    ![[img.png]]      →  same
    [[Note|Alias]]    →  Alias
    [[Note]]          →  Note
    """
    def replace_wiki_img(m: re.Match) -> str:
        raw = m.group(1)
        name = Path(raw).name
        path = image_index.get(name.lower())
        if path:
            return f"![]({path})"
        if missing_images is not None:
            missing_images.append(f"![[{raw}]]")
        return ""

    text = _RE_WIKI_IMG.sub(replace_wiki_img, text)

    def replace_wikilink(m: re.Match) -> str:
        return m.group(2).strip() if m.group(2) else Path(m.group(1)).stem

    text = _RE_WIKI_LINK.sub(replace_wikilink, text)
    return text


# ── List helpers (with nesting) ───────────────────────────────────────────────

def _parse_list_item(lines: list[str], i: int) -> tuple[dict, int]:
    """
    Parse one list item and any deeper-indented children below it.
    Returns (block, next_line_index).
    """
    line = lines[i]
    mb = _RE_LIST_BULLET.match(line)
    mn = _RE_LIST_NUMBERED.match(line)
    m = mb or mn
    base_indent = len(m.group(1))
    block_type = "bulleted_list" if mb else "numbered_list"
    block: dict = {
        "type": block_type,
        "data": {"delta": parse_inline(m.group(3))},
    }

    i += 1
    sub: list[dict] = []
    while i < len(lines):
        next_line = lines[i]
        if next_line.strip() == "":
            break
        cm = _RE_LIST_BULLET.match(next_line) or _RE_LIST_NUMBERED.match(next_line)
        if not cm or len(cm.group(1)) <= base_indent:
            break
        child, i = _parse_list_item(lines, i)
        sub.append(child)

    if sub:
        block["children"] = sub
    return block, i


# ── Table helpers ─────────────────────────────────────────────────────────────

def _is_separator(line: str) -> bool:
    return bool(_RE_TABLE_SEP.match(line)) and "-" in line


def _split_row(line: str) -> list[str]:
    line = line.strip().lstrip("|").rstrip("|")
    return [c.strip() for c in line.split("|")]


def _make_table(rows: list[list[str]]) -> dict:
    ncols = max(len(r) for r in rows)
    table_rows = []
    for row in rows:
        row += [""] * (ncols - len(row))
        cells = [
            {
                "type": "simple_table_cell",
                "data": {},
                "children": [{"type": "paragraph",
                               "data": {"delta": parse_inline(cell)}}],
            }
            for cell in row
        ]
        table_rows.append({"type": "simple_table_row", "data": {}, "children": cells})
    return {"type": "simple_table", "data": {}, "children": table_rows}


# ── Main converter ────────────────────────────────────────────────────────────

def md_to_blocks(
    md_text: str,
    image_index: dict[str, Path],
    upload_image: Callable[[Path], str] | None = None,
    missing_images: list[str] | None = None,
) -> dict:
    """
    Convert a markdown string to an AppFlowy page_data block tree.

    Args:
        md_text:      Raw markdown content.
        image_index:  Map of filename.lower() → absolute Path (from the vault).
        upload_image: Optional callback that uploads a file and returns its URL.
                      If None, images are skipped.
        missing_images: If provided, unresolved image references are appended
                        (wikilink embeds and markdown images).
    """
    text = _strip_frontmatter(md_text)
    text = _preprocess_obsidian(text, image_index, missing_images)
    children: list[dict] = []
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ────────────────────────────────────────────────
        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            children.append({
                "type": "code",
                "data": {"delta": [{"insert": "\n".join(code_lines)}],
                         "language": lang or "plain text"},
            })
            if i < len(lines):  # skip closing ```; if missing, don't go out of bounds
                i += 1
            continue

        # ── Heading ──────────────────────────────────────────────────────────
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            children.append({
                "type": "heading",
                "data": {"delta": parse_inline(m.group(2)),
                         "level": len(m.group(1))},
            })
            i += 1
            continue

        # ── Horizontal rule ──────────────────────────────────────────────────
        if re.match(r"^-{3,}\s*$", line) or re.match(r"^\*{3,}\s*$", line):
            children.append({"type": "divider", "data": {}})
            i += 1
            continue

        # ── Markdown table ───────────────────────────────────────────────────
        if line.strip().startswith("|"):
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            rows = [_split_row(l) for l in table_lines if not _is_separator(l)]
            if rows:
                children.append(_make_table(rows))
            continue

        # ── Blockquote ───────────────────────────────────────────────────────
        m = re.match(r"^>\s?(.*)", line)
        if m:
            children.append({
                "type": "quote",
                "data": {"delta": parse_inline(m.group(1))},
            })
            i += 1
            continue

        # ── List (bullet or numbered, with nesting) ──────────────────────────
        if _RE_LIST_BULLET.match(line) or _RE_LIST_NUMBERED.match(line):
            block, i = _parse_list_item(lines, i)
            children.append(block)
            continue

        # ── Images ───────────────────────────────────────────────────────────
        all_imgs = _RE_MD_IMG.findall(line)
        if all_imgs:
            if upload_image:
                non_img = _RE_MD_IMG.sub("", line).strip()
                for img_path in all_imgs:
                    src = image_index.get(Path(img_path).name.lower())
                    if not src:
                        if missing_images is not None:
                            missing_images.append(f"![]({img_path})")
                        continue
                    url = upload_image(src)
                    if url:
                        children.append({"type": "image",
                                          "data": {"url": url, "align": "center"}})
                if non_img:
                    children.append({"type": "paragraph",
                                      "data": {"delta": parse_inline(non_img)}})
            else:
                # No uploader (--skip-images) — track misses, skip image blocks
                non_img = _RE_MD_IMG.sub("", line).strip()
                for img_path in all_imgs:
                    if missing_images is not None and image_index.get(Path(img_path).name.lower()) is None:
                        missing_images.append(f"![]({img_path})")
                if non_img:
                    children.append({"type": "paragraph",
                                      "data": {"delta": parse_inline(non_img)}})
            i += 1
            continue

        # ── Empty line ───────────────────────────────────────────────────────
        if line.strip() == "":
            children.append({"type": "paragraph",
                              "data": {"delta": [{"insert": ""}]}})
            i += 1
            continue

        # ── Regular paragraph ────────────────────────────────────────────────
        children.append({"type": "paragraph",
                          "data": {"delta": parse_inline(line)}})
        i += 1

    return {
        "type": "page",
        "children": children or [{"type": "paragraph",
                                   "data": {"delta": [{"insert": ""}]}}],
    }


# ── Image index builder ───────────────────────────────────────────────────────

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


def build_image_index(vault: Path) -> dict[str, Path]:
    """Return a map of filename.lower() → absolute Path for every image in the vault."""
    index: dict[str, Path] = {}
    for p in vault.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            key = p.name.lower()
            if key not in index:
                index[key] = p
            else:
                print(
                    f"  Warning: duplicate image filename {p.name!r} — "
                    f"embeds resolve to {index[key]}; skipped {p}",
                    file=sys.stderr,
                )
    return index
