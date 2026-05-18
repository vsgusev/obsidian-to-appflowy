<div align="center">

# obsidian-to-appflowy

[![PyPI version](https://img.shields.io/pypi/v/obsidian-to-appflowy?color=ffcb47&labelColor=black&style=flat-square)](https://pypi.org/project/obsidian-to-appflowy/)
[![Python](https://img.shields.io/badge/python-3.11+-ffcb47?labelColor=black&style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-ffcb47?labelColor=black&style=flat-square)](LICENSE)

Move your [Obsidian](https://obsidian.md) vault into [AppFlowy](https://appflowy.io) in one command.

</div>

---

A CLI tool for migrating Obsidian vaults into AppFlowy. It walks your vault,
converts markdown to AppFlowy blocks, and uploads everything through
the AppFlowy API — folders become nested pages, images get re-hosted, wikilinks
become page links.

Built for one-time migrations. Your Obsidian files are never modified.

## Before you start

1. **Python 3.11+** — `pip install obsidian-to-appflowy`
2. An **AppFlowy account** on [AppFlowy Cloud](https://appflowy.io) or your own deployment
3. Your **vault folder** — the directory you opened in Obsidian

> ⚠️ Run `--dry-run` first to preview without touching anything.

## What gets migrated

| Obsidian | AppFlowy |
|---|---|
| Folders | Nested pages |
| Headings `#` `##` … | Heading blocks (levels 1–6) |
| Bullet and numbered lists (nested) | List blocks with children |
| Blockquotes `>` | Quote blocks |
| Fenced code blocks | Code blocks with language |
| Horizontal rules `---` | Divider blocks |
| Markdown tables | `simple_table` blocks |
| **bold**, *italic*, ~~strike~~, `code`, ==highlight==, [links] | Inline formatting |
| HTML inline tags `<u>`, `<b>`, `<i>`, `<s>`, `<mark>`, `<a href>`, `<br>` | Mapped to AppFlowy formatting (underline / bold / italic / strikethrough / highlight / link / space) |
| Frontmatter `--- ... ---` | Preserved as a YAML code block at the top |
| Wikilinks `[[Note]]` / `[[Note\|Alias]]` | Page links (clicking navigates to the page) |
| `![[img.png]]`, `![alt](path)` | Uploaded image blocks |
| `- [ ]` / `- [x]` tasks | Todo blocks (checked state preserved) |

## Try the example vault first

Not sure what to expect? Clone the repo and run try a dry-run on the included vault — it covers every supported block type (headings, lists, tables, code, images, wikilinks, tasks…):

```bash
git clone https://github.com/vsgusev/obsidian-to-appflowy
cd obsidian-to-appflowy
obsidian-to-appflowy --vault example_vault --dry-run
```

Or import it to AppFlowy to see the real result before touching your own notes:

```bash
obsidian-to-appflowy --vault example_vault --url https://cloud.appflowy.io --email you@example.com
```

## Usage

Preview locally (no account needed):

```bash
# replace ~/Documents/MyVault with the absolute path to your vault
obsidian-to-appflowy --vault ~/Documents/MyVault --dry-run
```

Import to AppFlowy Cloud:

```bash
# for self-hosted, swap --url for your gateway, e.g. http://192.168.1.10:8800
obsidian-to-appflowy --vault ~/Documents/MyVault --url https://cloud.appflowy.io --email you@example.com
```

Password is prompted if not passed via `--password` or `$APPFLOWY_PASSWORD`.

### Options

| Flag | Default | |
|---|---|---|
| `--vault PATH` | required | Obsidian vault root |
| `--url URL` | required for import | AppFlowy API base URL |
| `--email EMAIL` | `$APPFLOWY_EMAIL` | Account email |
| `--password PASS` | `$APPFLOWY_PASSWORD` / prompt | Account password |
| `--space NAME` | `Obsidian` | Space name in AppFlowy |
| `--space-color HEX` | `#00BCF0` | Space icon color |
| `--skip-images` | off | Text-only import, no uploads |
| `--dry-run` | off | Preview without API calls |

## Limitations

- **Tags** — `#tag` stays as plain text
- **Callouts** — `> [!NOTE]` becomes a plain quote block
- **Plugins** — Dataview, Kanban, Excalidraw and other plugin syntax appear as plain text
- **HTML** — only inline tags listed in the migration table are mapped; block-level HTML (`<details>`, `<table>`, `<iframe>`, etc.) and unsupported inline tags (`<sup>`, `<sub>`, `<span>`) keep their content but lose styling
- **Duplicate image filenames** — if two images share a name, only one is used; a warning prints to stderr
- **Edge cases:**
  - Duplicate page names — wikilinks resolve by filename stem, so `[[Note]]` is ambiguous if two `Note.md` exist in different folders (the first one wins)
  - `[[Note#Section]]` and `[[Note^block]]` link to the page itself; the section/block target is dropped
  - YAML frontmatter with a `---` line inside a value may be only partially captured
  - Fenced code indented under a list bullet is not detected as a code block

## License

[MIT](LICENSE)
