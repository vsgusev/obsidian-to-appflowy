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


def test_frontmatter_preserved_as_yaml_code_block() -> None:
    # Frontmatter must NOT silently disappear — clipper-style notes use it for
    # the source URL, author, etc., which is often the only valuable bit.
    md = "---\ntitle: x\nsource: https://example.com\n---\n\nBody here."
    page = md_to_blocks(md, {}, None)
    assert page["children"][0]["type"] == "code"
    assert page["children"][0]["data"]["language"] == "yaml"
    yaml_text = page["children"][0]["data"]["delta"][0]["insert"]
    assert "title: x" in yaml_text
    assert "source: https://example.com" in yaml_text
    assert "---" not in yaml_text  # markers themselves are stripped
    paragraphs = [c for c in page["children"] if c["type"] == "paragraph"]
    joined = "".join(op["insert"] for p in paragraphs for op in p["data"]["delta"])
    assert "Body here" in joined


def test_no_frontmatter_no_yaml_block() -> None:
    # If the file has no frontmatter, we don't fabricate one.
    page = md_to_blocks("# Hello\n\nJust text.", {}, None)
    assert not any(c["type"] == "code" and c["data"].get("language") == "yaml"
                   for c in page["children"])


def test_frontmatter_clipper_style_preserved() -> None:
    # Real-world Obsidian Web Clipper output — nested lists, multiline values.
    md = """---
title: "Some Article"
source: "https://youtube.com/watch?v=abc"
author:
  - "[[YouTube]]"
tags:
  - "clippings"
---

Article body."""
    page = md_to_blocks(md, {}, None)
    code = page["children"][0]
    assert code["type"] == "code"
    yaml_text = code["data"]["delta"][0]["insert"]
    assert "https://youtube.com/watch?v=abc" in yaml_text
    assert "clippings" in yaml_text


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


def test_inline_underscore_ignores_snake_case() -> None:
    # snake_case identifiers must not be partially italicised
    ops = parse_inline("some_variable_name")
    text = "".join(op["insert"] for op in ops)
    assert text == "some_variable_name"
    assert not any(op.get("attributes", {}).get("italic") for op in ops)


def test_build_image_index_duplicate_warns(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    d = tmp_path / "sub"
    d.mkdir()
    (tmp_path / "x.png").write_bytes(b"a")
    (d / "x.png").write_bytes(b"b")
    build_image_index(tmp_path)
    err = capsys.readouterr().err
    assert "duplicate" in err.lower()


# ── Headings ──────────────────────────────────────────────────────────────────

def test_heading_level_3() -> None:
    page = md_to_blocks("### Section", {}, None)
    h = page["children"][0]
    assert h["type"] == "heading"
    assert h["data"]["level"] == 3


# ── Numbered list ─────────────────────────────────────────────────────────────

def test_numbered_list() -> None:
    page = md_to_blocks("1. first\n2. second", {}, None)
    items = [c for c in page["children"] if c["type"] == "numbered_list"]
    assert len(items) == 2
    text = "".join(op["insert"] for op in items[0]["data"]["delta"])
    assert text == "first"


def test_numbered_list_nested() -> None:
    page = md_to_blocks("1. a\n   1. b", {}, None)
    items = [c for c in page["children"] if c["type"] == "numbered_list"]
    assert len(items) == 1
    assert "children" in items[0]
    assert items[0]["children"][0]["type"] == "numbered_list"


# ── Inline formatting ─────────────────────────────────────────────────────────

def test_inline_italic() -> None:
    ops = parse_inline("*hello*")
    assert ops[0].get("attributes", {}).get("italic") is True
    assert ops[0]["insert"] == "hello"


def test_inline_strikethrough() -> None:
    ops = parse_inline("~~gone~~")
    assert ops[0].get("attributes", {}).get("strikethrough") is True
    assert ops[0]["insert"] == "gone"


def test_inline_highlight() -> None:
    ops = parse_inline("==marked==")
    assert ops[0]["insert"] == "marked"
    assert ops[0].get("attributes", {}).get("bg_color") == "0x4dffeb3b"


def test_inline_highlight_does_not_affect_single_equals() -> None:
    ops = parse_inline("x=5 and y=10")
    text = "".join(op["insert"] for op in ops)
    assert text == "x=5 and y=10"
    assert not any(op.get("attributes", {}).get("bg_color") for op in ops)


def test_inline_code() -> None:
    ops = parse_inline("`snippet`")
    assert ops[0].get("attributes", {}).get("code") is True
    assert ops[0]["insert"] == "snippet"


def test_inline_link() -> None:
    ops = parse_inline("[OpenAI](https://openai.com)")
    assert ops[0]["insert"] == "OpenAI"
    assert ops[0].get("attributes", {}).get("href") == "https://openai.com"


def test_inline_link_inside_surrounding_text() -> None:
    # Regression: plain text used to swallow "[link](" because '[' wasn't
    # excluded, so the markdown link was never detected when preceded by prose.
    ops = parse_inline("see [OpenAI](https://openai.com) for details")
    href_ops = [op for op in ops if op.get("attributes", {}).get("href")]
    assert len(href_ops) == 1
    assert href_ops[0]["insert"] == "OpenAI"
    assert href_ops[0]["attributes"]["href"] == "https://openai.com"
    text = "".join(op["insert"] for op in ops)
    assert text == "see OpenAI for details"


def test_list_item_with_link_inside_text() -> None:
    # Same regression manifested in list items (the screenshot bug).
    page = md_to_blocks("- Item with a [link](https://example.com)", {}, None)
    bullet = page["children"][0]
    assert bullet["type"] == "bulleted_list"
    href_ops = [op for op in bullet["data"]["delta"] if op.get("attributes", {}).get("href")]
    assert len(href_ops) == 1
    assert href_ops[0]["insert"] == "link"
    assert href_ops[0]["attributes"]["href"] == "https://example.com"


def test_bare_url_becomes_link() -> None:
    ops = parse_inline("see https://example.com for details")
    url_op = next(op for op in ops if op.get("attributes", {}).get("href"))
    assert url_op["insert"] == "https://example.com"
    assert url_op["attributes"]["href"] == "https://example.com"


# ── Wikilinks ─────────────────────────────────────────────────────────────────

def test_wikilink_no_alias() -> None:
    page = md_to_blocks("See [[My Note]] here.", {}, None)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    text = "".join(op["insert"] for op in para["data"]["delta"])
    assert "My Note" in text
    assert "[[" not in text


def test_wikilink_becomes_mention_when_page_known() -> None:
    page_ids = {"my note": "abc-123"}
    page = md_to_blocks("See [[My Note]] here.", {}, None, page_ids=page_ids)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    mention_ops = [op for op in para["data"]["delta"] if op.get("attributes", {}).get("mention")]
    assert len(mention_ops) == 1
    assert mention_ops[0]["insert"] == "$"
    assert mention_ops[0]["attributes"]["mention"]["page_id"] == "abc-123"
    assert mention_ops[0]["attributes"]["mention"]["type"] == "page"


def test_wikilink_alias_becomes_mention_when_page_known() -> None:
    page_ids = {"my note": "abc-123"}
    page = md_to_blocks("See [[My Note|Alias]] here.", {}, None, page_ids=page_ids)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    mention_ops = [op for op in para["data"]["delta"] if op.get("attributes", {}).get("mention")]
    assert len(mention_ops) == 1
    assert mention_ops[0]["attributes"]["mention"]["page_id"] == "abc-123"


def test_wikilink_unknown_page_stays_plain_text() -> None:
    page_ids = {"other note": "xyz-999"}
    page = md_to_blocks("See [[Missing Page]] here.", {}, None, page_ids=page_ids)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    text = "".join(op["insert"] for op in para["data"]["delta"])
    assert "Missing Page" in text
    assert not any(op.get("attributes", {}).get("mention") for op in para["data"]["delta"])


def test_wikilink_with_subfolder_resolves() -> None:
    # Obsidian allows [[Folder/Note]] — we ignore the folder prefix and match by stem.
    page_ids = {"my note": "abc-123"}
    page = md_to_blocks("See [[Folder/My Note]] here.", {}, None, page_ids=page_ids)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    mention_ops = [op for op in para["data"]["delta"] if op.get("attributes", {}).get("mention")]
    assert len(mention_ops) == 1
    assert mention_ops[0]["attributes"]["mention"]["page_id"] == "abc-123"


def test_wikilink_with_section_anchor_resolves() -> None:
    # [[Note#Section]] resolves to Note (section info is dropped).
    page_ids = {"my note": "abc-123"}
    page = md_to_blocks("See [[My Note#Heading]] here.", {}, None, page_ids=page_ids)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    mention_ops = [op for op in para["data"]["delta"] if op.get("attributes", {}).get("mention")]
    assert len(mention_ops) == 1
    assert mention_ops[0]["attributes"]["mention"]["page_id"] == "abc-123"


def test_wikilink_with_block_anchor_resolves() -> None:
    # [[Note^block-id]] block references resolve to the page.
    page_ids = {"my note": "abc-123"}
    page = md_to_blocks("See [[My Note^para-7]] here.", {}, None, page_ids=page_ids)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    mention_ops = [op for op in para["data"]["delta"] if op.get("attributes", {}).get("mention")]
    assert len(mention_ops) == 1
    assert mention_ops[0]["attributes"]["mention"]["page_id"] == "abc-123"


def test_wikilink_subfolder_and_anchor_display_when_unknown() -> None:
    # Unknown page: display strips the folder prefix and anchor.
    page = md_to_blocks("See [[Folder/Missing#Section]] here.", {}, None)
    para = next(c for c in page["children"] if c["type"] == "paragraph")
    text = "".join(op["insert"] for op in para["data"]["delta"])
    assert "Missing" in text
    assert "Folder/" not in text
    assert "#Section" not in text


def test_image_upload_failure_is_reported(tmp_path: Path) -> None:
    # If the uploader returns "" (e.g. transient HTTP error), the image must
    # show up in missing_images so the user knows something went wrong.
    (tmp_path / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    idx = build_image_index(tmp_path)

    def failing_upload(path: Path) -> str:
        return ""

    miss: list[str] = []
    page = md_to_blocks("![[photo.png]]", idx, failing_upload, missing_images=miss)
    assert any("upload failed" in m for m in miss)
    assert not any(c["type"] == "image" for c in page["children"])


# ── Code block ────────────────────────────────────────────────────────────────

def test_code_block_no_language() -> None:
    page = md_to_blocks("```\nsome code\n```", {}, None)
    code = page["children"][0]
    assert code["type"] == "code"
    assert code["data"]["language"] == "plain text"


# ── Images ────────────────────────────────────────────────────────────────────

def test_image_block_created_with_uploader(tmp_path: Path) -> None:
    (tmp_path / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    idx = build_image_index(tmp_path)
    uploaded: list[Path] = []

    def fake_upload(path: Path) -> str:
        uploaded.append(path)
        return "https://cdn.example.com/photo.png"

    page = md_to_blocks("![[photo.png]]", idx, fake_upload)
    assert len(uploaded) == 1
    images = [c for c in page["children"] if c["type"] == "image"]
    assert len(images) == 1
    assert images[0]["data"]["url"] == "https://cdn.example.com/photo.png"


def test_md_image_missing_reported() -> None:
    miss: list[str] = []
    md_to_blocks("![alt](missing.png)", {}, None, missing_images=miss)
    assert any("missing.png" in m for m in miss)


def test_task_unchecked() -> None:
    page = md_to_blocks("- [ ] buy milk", {}, None)
    block = page["children"][0]
    assert block["type"] == "todo_list"
    assert block["data"]["checked"] is False
    assert "".join(op["insert"] for op in block["data"]["delta"]) == "buy milk"


def test_task_checked() -> None:
    page = md_to_blocks("- [x] done", {}, None)
    block = page["children"][0]
    assert block["type"] == "todo_list"
    assert block["data"]["checked"] is True


def test_bracket_not_dropped_in_plain_text() -> None:
    ops = parse_inline("see [Section 1] for details")
    text = "".join(op["insert"] for op in ops)
    assert text == "see [Section 1] for details"


def test_wiki_image_escaped_pipe(tmp_path: Path) -> None:
    # Obsidian sometimes escapes the alias pipe as \| — must still resolve
    (tmp_path / "1 2.jpg").write_bytes(b"img")
    idx = build_image_index(tmp_path)
    miss: list[str] = []
    md_to_blocks(r"![[1 2.jpg\|1 2.jpg]]", idx, None, missing_images=miss)
    assert not miss


def test_external_url_image_becomes_block(tmp_path: Path) -> None:
    # External URLs should become image blocks directly, not reported as missing
    miss: list[str] = []
    url = "https://example.com/photo.gif"

    def fake_upload(path: Path) -> str:
        return ""

    page = md_to_blocks(f"![]({url})", {}, fake_upload, missing_images=miss)
    assert not miss
    images = [c for c in page["children"] if c["type"] == "image"]
    assert len(images) == 1
    assert images[0]["data"]["url"] == url


def test_external_non_image_url_becomes_link_not_image() -> None:
    # ![](youtube-url) shouldn't become an image block — AppFlowy would
    # spin forever trying to load HTML as a JPEG. Preserve as a link.
    def fake_upload(path: Path) -> str:
        return ""

    page = md_to_blocks("![](https://www.youtube.com/watch?v=abc123)", {}, fake_upload)
    assert not any(c["type"] == "image" for c in page["children"])
    href_ops = [op for c in page["children"] if c["type"] == "paragraph"
                for op in c["data"]["delta"] if op.get("attributes", {}).get("href")]
    assert len(href_ops) == 1
    assert href_ops[0]["attributes"]["href"] == "https://www.youtube.com/watch?v=abc123"


def test_image_url_with_query_string_still_detected() -> None:
    # CDN URLs often have ?w=...&h=... query strings — extension is before the ?.
    def fake_upload(path: Path) -> str:
        return ""

    page = md_to_blocks("![](https://cdn.example.com/photo.png?w=800&h=600)", {}, fake_upload)
    images = [c for c in page["children"] if c["type"] == "image"]
    assert len(images) == 1


# ── Table structure ───────────────────────────────────────────────────────────

def test_table_structure() -> None:
    md = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n"
    page = md_to_blocks(md, {}, None)
    table = page["children"][0]
    assert table["type"] == "simple_table"
    rows = table["children"]
    assert len(rows) == 2  # header + data row; separator stripped
    assert rows[0]["type"] == "simple_table_row"
    cells = rows[0]["children"]
    assert len(cells) == 2
    assert cells[0]["type"] == "simple_table_cell"
    name_text = "".join(op["insert"] for op in cells[0]["children"][0]["data"]["delta"])
    assert name_text == "Name"


# ── Inline HTML tags ──────────────────────────────────────────────────────────

def _attrs_of(ops: list, text: str) -> dict:
    """Find the op matching `text` and return its attributes (empty if none)."""
    for op in ops:
        if op["insert"] == text:
            return op.get("attributes", {})
    raise AssertionError(f"no op with insert={text!r}; got {ops!r}")


def test_html_u_becomes_underline() -> None:
    ops = parse_inline("a <u>under</u> b")
    assert _attrs_of(ops, "under") == {"underline": True}


def test_html_b_and_strong_become_bold() -> None:
    assert _attrs_of(parse_inline("<b>x</b>"), "x") == {"bold": True}
    assert _attrs_of(parse_inline("<strong>y</strong>"), "y") == {"bold": True}


def test_html_i_and_em_become_italic() -> None:
    assert _attrs_of(parse_inline("<i>x</i>"), "x") == {"italic": True}
    assert _attrs_of(parse_inline("<em>y</em>"), "y") == {"italic": True}


def test_html_s_strike_del_become_strikethrough() -> None:
    assert _attrs_of(parse_inline("<s>x</s>"), "x") == {"strikethrough": True}
    assert _attrs_of(parse_inline("<strike>y</strike>"), "y") == {"strikethrough": True}
    assert _attrs_of(parse_inline("<del>z</del>"), "z") == {"strikethrough": True}


def test_html_mark_becomes_highlight() -> None:
    attrs = _attrs_of(parse_inline("<mark>yellow</mark>"), "yellow")
    assert attrs.get("bg_color") == "0x4dffeb3b"


def test_html_code_becomes_code_attribute() -> None:
    assert _attrs_of(parse_inline("<code>snippet</code>"), "snippet") == {"code": True}


def test_html_a_becomes_link_with_href() -> None:
    ops = parse_inline('see <a href="https://example.com">site</a>')
    assert _attrs_of(ops, "site") == {"href": "https://example.com"}


def test_html_a_without_href_strips_tag() -> None:
    # <a> without href becomes a no-op wrapper — content kept as plain text.
    ops = parse_inline("<a>just text</a>")
    text = "".join(op["insert"] for op in ops)
    assert text == "just text"
    assert all("href" not in op.get("attributes", {}) for op in ops)


def test_html_br_becomes_space() -> None:
    text = "".join(op["insert"] for op in parse_inline("line one<br>line two"))
    assert text == "line one line two"


def test_html_br_self_closing_variants() -> None:
    # <br>, <br/>, <br /> should all behave the same.
    for variant in ("<br>", "<br/>", "<br />"):
        text = "".join(op["insert"] for op in parse_inline(f"a{variant}b"))
        assert text == "a b", f"failed for variant {variant!r}"


def test_html_nested_tags_combine_attributes() -> None:
    ops = parse_inline("<b><i>both</i></b>")
    attrs = _attrs_of(ops, "both")
    assert attrs.get("bold") is True
    assert attrs.get("italic") is True


def test_html_case_insensitive() -> None:
    assert _attrs_of(parse_inline("<U>x</U>"), "x") == {"underline": True}
    assert _attrs_of(parse_inline("<B>x</B>"), "x") == {"bold": True}


def test_html_tag_with_extra_attributes_still_parses() -> None:
    # Real-world clipper output has class/style/etc on tags.
    ops = parse_inline('<a href="https://x.com" class="external" target="_blank">link</a>')
    assert _attrs_of(ops, "link") == {"href": "https://x.com"}


def test_markdown_outside_html_is_still_parsed() -> None:
    ops = parse_inline("**bold** <u>under</u> *italic*")
    assert _attrs_of(ops, "bold") == {"bold": True}
    assert _attrs_of(ops, "under") == {"underline": True}
    assert _attrs_of(ops, "italic") == {"italic": True}


def test_markdown_inside_html_stays_literal() -> None:
    # Obsidian semantic: markdown does not render inside HTML elements.
    ops = parse_inline("<u>**not bold**</u>")
    text = "".join(op["insert"] for op in ops)
    assert "**" in text  # the asterisks are preserved as literal characters
    assert "not bold" in text


def test_unknown_html_tag_preserves_content() -> None:
    # <sup>, <details>, etc. — strip the tag, keep the text.
    ops = parse_inline("E = mc<sup>2</sup>")
    text = "".join(op["insert"] for op in ops)
    assert text == "E = mc2"


def test_text_with_less_than_but_no_tag_works() -> None:
    # Inequality `<` that isn't a tag start should not break parsing.
    ops = parse_inline("if x < y then ok")
    text = "".join(op["insert"] for op in ops)
    assert text == "if x < y then ok"


def test_html_underline_in_list_item() -> None:
    # The original bug report: <u>...</u> inside a list item.
    page = md_to_blocks("- a <u>дальше</u> b", {}, None)
    bullet = page["children"][0]
    assert bullet["type"] == "bulleted_list"
    assert _attrs_of(bullet["data"]["delta"], "дальше") == {"underline": True}
