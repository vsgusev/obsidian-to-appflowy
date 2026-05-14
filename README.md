<div align="center">

# obsidian-to-appflowy

[![PyPI version](https://img.shields.io/pypi/v/obsidian-to-appflowy?color=ffcb47&labelColor=black&style=flat-square)](https://pypi.org/project/obsidian-to-appflowy/)
[![Python](https://img.shields.io/badge/python-3.11+-ffcb47?labelColor=black&style=flat-square)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-ffcb47?labelColor=black&style=flat-square)](LICENSE)

Move your [Obsidian](https://obsidian.md) vault into [AppFlowy](https://appflowy.io) in one command.

</div>

---

Unofficial one-time migration tool. Not affiliated with Obsidian or AppFlowy. Works well for standard markdown vaults — no promises on plugins or exotic syntax. Your vault is never modified.

## Before you start

1. **Python 3.11+** — `pip install obsidian-to-appflowy`
2. An **AppFlowy account** on [AppFlowy Cloud](https://appflowy.io) or your own deployment
3. Your **vault folder** path (the one with `.obsidian` inside)

Run `--dry-run` first to preview without touching anything.

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
| **bold**, *italic*, ~~strike~~, `code`, [links] | Inline formatting |
| Frontmatter `--- ... ---` | Stripped |
| Wikilinks `[[Note]]` / `[[Note\|Alias]]` | Plain text |
| `![[img.png]]`, `![alt](path)` | Uploaded image blocks |

## Usage

Preview locally (no account needed):

```bash
obsidian-to-appflowy --vault ~/Documents/MyVault --dry-run
```

Import to AppFlowy Cloud:

```bash
obsidian-to-appflowy \
  --vault ~/Documents/MyVault \
  --url https://cloud.appflowy.io \
  --email you@example.com
```

Self-hosted: replace the URL with your gateway, e.g. `http://192.168.1.10:8800`.

Password is prompted if not passed via `--password` or `$APPFLOWY_PASSWORD`.

### Options

| Flag | Default | |
|---|---|---|
| `--vault PATH` | required | Obsidian vault root |
| `--url URL` | required | AppFlowy API base URL |
| `--email EMAIL` | `$APPFLOWY_EMAIL` | Account email |
| `--password PASS` | prompt | Account password |
| `--space NAME` | `Obsidian` | Space name in AppFlowy |
| `--space-color HEX` | `#00BCF0` | Space icon color |
| `--skip-images` | off | Text-only import, no uploads |
| `--dry-run` | off | Preview without API calls |

## Limitations

- **Wikilinks** — `[[Note]]` becomes plain text, no cross-page links
- **Tags** — `#tag` stays as plain text
- **Callouts** — `> [!NOTE]` becomes a plain quote block
- **Tasks** — `- [ ]` becomes a regular list item
- **Plugins** — Dataview, Kanban, Excalidraw and other plugin syntax appear as plain text
- **Scale** — tested on ~200 pages / ~400 images; large vaults are unknown territory
- **Duplicate image filenames** — if two images share a name, only one is used; a warning prints to stderr

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Contributing

Open an issue before sending a PR. No AI-generated PRs.

## License

[MIT](LICENSE)
