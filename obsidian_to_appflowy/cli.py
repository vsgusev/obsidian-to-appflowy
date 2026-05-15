"""Command-line entry point."""

import argparse
import getpass
import os
import sys
from pathlib import Path

import requests

from .importer import run_import


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="obsidian-to-appflowy",
        description="Migrate an Obsidian vault into AppFlowy (self-hosted or Cloud).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Credentials can also be supplied via environment variables to avoid
exposing them in shell history:

  export APPFLOWY_EMAIL=me@example.com
  export APPFLOWY_PASSWORD=secret

Typical flow:
  1) Preview locally (no account, no network):
       obsidian-to-appflowy --vault /path/to/Vault --dry-run
  2) Import to AppFlowy Cloud:
       obsidian-to-appflowy --vault /path/to/Vault \\
         --url https://cloud.appflowy.io --email me@example.com

Examples:
  # Self-hosted AppFlowy Cloud
  obsidian-to-appflowy \\
    --vault ~/Documents/MyVault \\
    --url http://192.168.1.10:8800 \\
    --email me@example.com

  # AppFlowy Cloud
  obsidian-to-appflowy \\
    --vault ~/Documents/MyVault \\
    --url https://cloud.appflowy.io \\
    --email me@example.com \\
    --space "My Notes"
""",
    )

    parser.add_argument(
        "--vault", required=True, type=Path,
        help="Path to the root of your Obsidian vault.",
    )
    parser.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help="AppFlowy Cloud API base URL (e.g. https://cloud.appflowy.io). "
             "Omit with --dry-run.",
    )
    parser.add_argument(
        "--email", default=os.environ.get("APPFLOWY_EMAIL"),
        help="AppFlowy account e-mail ($APPFLOWY_EMAIL). Not used with --dry-run.",
    )
    parser.add_argument(
        "--password", default=os.environ.get("APPFLOWY_PASSWORD"),
        help="AppFlowy account password. Falls back to $APPFLOWY_PASSWORD. "
             "If omitted, you will be prompted interactively.",
    )
    parser.add_argument(
        "--space", default="Obsidian",
        help="Name of the Space to create in AppFlowy (default: Obsidian).",
    )
    parser.add_argument(
        "--space-color", default="#00BCF0",
        help="Hex color for the new space (default: #00BCF0).",
    )
    parser.add_argument(
        "--skip-images", action="store_true",
        help="Do not upload images (faster, text-only import).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse the vault and print what would be imported, without calling the API.",
    )

    args = parser.parse_args()
    args.vault = args.vault.expanduser().resolve()

    if not args.vault.exists():
        print(f"Error: vault path does not exist: {args.vault}", file=sys.stderr)
        sys.exit(1)

    url = (args.url or "").rstrip("/")
    if not args.dry_run:
        if not url:
            print(
                "Error: --url is required for import (e.g. https://cloud.appflowy.io). "
                "Use --dry-run to preview without a URL.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not args.email:
            print(
                "Error: --email is required (or set $APPFLOWY_EMAIL).",
                file=sys.stderr,
            )
            sys.exit(1)

    password = args.password
    if not password and not args.dry_run:
        password = getpass.getpass(f"Password for {args.email}: ")

    try:
        code = run_import(
            vault=args.vault,
            url=url,
            email=args.email or "",
            password=password or "",
            space_name=args.space,
            space_color=args.space_color,
            skip_images=args.skip_images,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
    except requests.HTTPError as e:
        resp = e.response
        print("Error: AppFlowy returned an HTTP error.", file=sys.stderr)
        if resp is not None:
            print(f"  {resp.status_code} {resp.reason}", file=sys.stderr)
            body = (resp.text or "").strip()
            if body:
                print(body[:800], file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"Error: could not reach AppFlowy ({e}). Check --url and your network.", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(code)


if __name__ == "__main__":
    main()
