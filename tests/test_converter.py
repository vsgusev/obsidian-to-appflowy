"""Golden-style checks for markdown → AppFlowy block JSON."""

from pathlib import Path

import pytest

from obsidian_to_appflowy.converter import build_image_index, md_to_blocks, parse_inline


def _types(children: list) -> list[str]:
    return [b["type"] for b in children]


def test_heading_and_paragraph() -> None:
    page = md_to_blocks("# Title\n\nHello.", {}, None)
    assert page["type"] == "page"
    ch = page["children"]
    assert ch[0]["type"] == "heading"
    assert ch[0]["data"]["level"] == 1
    assert ch[1]["type"] == "paragraph"


def test_frontmatter_stripped() -> None:
    md = "---\ntitle: x\n---\n\nBody here."
    page = md_to_blocks(md, {}, None)
    deltas = [c["data"]["delta"] for c in page["children"] if c["type"] == "paragraph"]
    joined = "".join(op["insert"] for d in deltas for op in d)
    assert "Body here" in joined
    assert "title:" not in joined


def test_wikilink_to_display_text() -> None:
    page = md_to_blocks("See [[My Note|Alias]] here.", {}, None)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    text = "".join(op["insert"] for op in para["data"]["delta"])
    assert "Alias" in text
    assert "[[" not in text


def test_fenced_code_block() -> None:
    page = md_to_blocks("```python\nx = 1\n```", {}, None)
    code = page["children"][0]
    assert code["type"] == "code"
    assert code["data"]["language"] == "python"
    assert "x = 1" in code["data"]["delta"][0]["insert"]


def test_nested_list_has_children() -> None:
    md = "- a\n  - b\n- c"
    page = md_to_blocks(md, {}, None)
    lists = [c for c in page["children"] if c["type"] == "bulleted_list"]
    assert len(lists) == 2
    assert "children" in lists[0]
    assert lists[0]["children"][0]["type"] == "bulleted_list"


def test_markdown_table() -> None:
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    page = md_to_blocks(md, {}, None)
    assert page["children"][0]["type"] == "simple_table"


def test_divider() -> None:
    page = md_to_blocks("before\n\n---\n\nafter", {}, None)
    assert "divider" in _types(page["children"])


def test_parse_inline_bold() -> None:
    ops = parse_inline("**x**")
    assert ops[0].get("attributes", {}).get("bold") is True
    assert ops[0]["insert"] == "x"


def test_missing_wiki_image_reported(tmp_path: Path) -> None:
    miss: list[str] = []
    md_to_blocks("x ![[missing.png]] y", {}, None, missing_images=miss)
    assert any("missing.png" in m for m in miss)


def test_wiki_image_resolved(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    idx = build_image_index(tmp_path)
    miss: list[str] = []
    md_to_blocks("![[a.png]]", idx, None, missing_images=miss)
    assert not miss


def test_blockquote_single_line() -> None:
    page = md_to_blocks("> quoted", {}, None)
    assert page["children"][0]["type"] == "quote"


def test_build_image_index_duplicate_warns(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    d = tmp_path / "sub"
    d.mkdir()
    (tmp_path / "x.png").write_bytes(b"a")
    (d / "x.png").write_bytes(b"b")
    build_image_index(tmp_path)
    err = capsys.readouterr().err
    assert "duplicate" in err.lower()
