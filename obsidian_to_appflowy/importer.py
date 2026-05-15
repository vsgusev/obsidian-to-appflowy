"""
AppFlowy Cloud API client and vault import orchestration.

Public entry point:  run_import(...)  -> exit code (0 = success)
"""

import sys
import time
import uuid
from pathlib import Path

import requests

from .converter import build_image_index, md_to_blocks

_SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__"}
_REQUEST_TIMEOUT = 30  # seconds
_MAX_IMAGE_BYTES = 50 * 1024 * 1024  # 50 MB

# AppFlowy Cloud API payload enums (values defined by the server contract).
_PAGE_LAYOUT_DOCUMENT = 0
_SPACE_PERMISSION_DEFAULT = 1
_SPACE_ICON_DEFAULT = "2"  # icon index in AppFlowy's built-in icon set

_RETRYABLE_HTTP = (429, 500, 502, 503, 504)
_SLEEP_AFTER_FOLDER = 0.08  # avoid hammering the API
_SLEEP_AFTER_PAGE   = 0.05

# Explicit MIME map — mimetypes.guess_type is unreliable on Windows
# (often None for .svg/.webp, which previously fell back to image/png and
# made AppFlowy reject the upload).
_MIME_BY_EXT = {
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".svg":  "image/svg+xml",
    ".bmp":  "image/bmp",
}


# ── HTTP with retry ───────────────────────────────────────────────────────────

def _request(method: str, url: str, **kwargs) -> requests.Response:
    """HTTP request with retries: network failures, then 429 / 5xx."""
    delay = 2.0
    for attempt in range(4):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.RequestException as e:
            if attempt == 3:
                raise
            wait = delay * (2 ** attempt)
            print(f"  [network] {type(e).__name__}: {e}; retrying in {wait:.0f}s ...")
            time.sleep(wait)
            continue
        if resp.status_code in _RETRYABLE_HTTP and attempt < 3:
            wait = delay * (2 ** attempt)
            print(f"  [{resp.status_code}] retrying in {wait:.0f}s ...")
            time.sleep(wait)
            continue
        return resp
    raise RuntimeError("_request: unreachable")


def _get(url: str, **kw) -> requests.Response:
    return _request("GET", url, **kw)

def _post(url: str, **kw) -> requests.Response:
    return _request("POST", url, **kw)

def _put(url: str, **kw) -> requests.Response:
    return _request("PUT", url, **kw)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_token(url: str, email: str, password: str) -> str:
    resp = _post(
        f"{url}/gotrue/token?grant_type=password",
        json={"email": email, "password": password},
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _hdrs(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── Workspace ─────────────────────────────────────────────────────────────────

def _get_workspace_id(url: str, token: str) -> str:
    resp = _get(
        f"{url}/api/workspace",
        headers=_hdrs(token),
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    workspaces = resp.json().get("data", [])
    if not workspaces:
        raise RuntimeError("No workspaces found for this account.")
    return workspaces[0]["workspace_id"]


# ── Cleanup ───────────────────────────────────────────────────────────────────

def _find_old_spaces(url: str, token: str, workspace_id: str, space_name: str) -> list[str]:
    """Return view_ids of existing spaces matching space_name.

    Raises HTTPError on failure — silently returning [] used to cause duplicate
    spaces when the lookup failed transiently.
    """
    resp = _get(
        f"{url}/api/workspace/{workspace_id}/folder",
        headers=_hdrs(token),
        params={"depth": 1},
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return [
        child["view_id"]
        for child in resp.json().get("data", {}).get("children", [])
        if child.get("name") == space_name
    ]


def _trash_spaces(url: str, token: str, workspace_id: str, view_ids: list[str]) -> None:
    for view_id in view_ids:
        r = _post(
            f"{url}/api/workspace/{workspace_id}/page-view/{view_id}/move-to-trash",
            headers=_hdrs(token),
            timeout=_REQUEST_TIMEOUT,
        )
        if r.ok:
            print(f"  Moved space {view_id} to trash.")


# ── Space / page creation ─────────────────────────────────────────────────────

def _create_space(url: str, token: str, workspace_id: str,
                  name: str, color: str) -> str:
    resp = _post(
        f"{url}/api/workspace/{workspace_id}/space",
        headers=_hdrs(token),
        json={
            "space_permission": _SPACE_PERMISSION_DEFAULT,
            "name": name,
            "space_icon": _SPACE_ICON_DEFAULT,
            "space_icon_color": color,
            "view_id": None,
        },
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    view_id = resp.json()["data"]["view_id"]
    print(f"Created space '{name}' ({view_id})")
    return view_id


def _create_page(url: str, token: str, workspace_id: str,
                 parent_view_id: str, name: str,
                 page_data: dict | None,
                 view_id: str | None = None) -> str:
    resp = _post(
        f"{url}/api/workspace/{workspace_id}/page-view",
        headers=_hdrs(token),
        json={
            "parent_view_id": parent_view_id,
            "layout": _PAGE_LAYOUT_DOCUMENT,
            "name": name,
            "page_data": page_data,
            "view_id": view_id,
            "collab_id": view_id,  # must match view_id so AppFlowy can locate the document
        },
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["data"]["view_id"]


# ── Image upload ──────────────────────────────────────────────────────────────

def _upload_image(
    url: str,
    token: str,
    workspace_id: str,
    path: Path,
    cache: dict[str, str],
) -> str:
    key = str(path.resolve())
    if key in cache:
        return cache[key]

    size = path.stat().st_size
    if size > _MAX_IMAGE_BYTES:
        print(
            f"  Warning: skipping {path.name} (too large, {size // 1024 // 1024} MB)",
            file=sys.stderr,
        )
        return ""

    mime = _MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
    data = path.read_bytes()
    file_id = str(uuid.uuid4())
    resp = _put(
        f"{url}/api/file_storage/{workspace_id}/blob/{file_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": mime,
            "Content-Length": str(len(data)),
        },
        data=data,
        timeout=_REQUEST_TIMEOUT,
    )
    if not resp.ok:
        print(
            f"  Warning: upload failed for {path.name}: HTTP {resp.status_code}",
            file=sys.stderr,
        )
        return ""
    img_url = f"{url}/api/file_storage/{workspace_id}/blob/{file_id}"
    cache[key] = img_url
    return img_url


# ── Page pre-scan (for wikilink resolution) ───────────────────────────────────

def _prescan_vault(vault: Path) -> dict[str, str]:
    """Walk vault and assign a stable UUID to every .md page (stem.lower() → uuid).

    Called before the import so wikilinks [[Note]] can be turned into AppFlowy
    mention ops that point to the correct page_id.  Duplicate stems keep the
    first UUID found (mirrors Obsidian's shortest-path resolution).
    """
    page_ids: dict[str, str] = {}
    for p in vault.rglob("*.md"):
        parts = p.relative_to(vault).parts
        if any(part in _SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        stem = p.stem.lower()
        if stem not in page_ids:
            page_ids[stem] = str(uuid.uuid4())
    return page_ids


# ── Progress counter ──────────────────────────────────────────────────────────

def _count_md_files(vault: Path) -> int:
    count = 0
    for p in vault.rglob("*.md"):
        if not any(part in _SKIP_DIRS or part.startswith(".")
                   for part in p.relative_to(vault).parts):
            count += 1
    return count


# ── Recursive import ──────────────────────────────────────────────────────────

def _import_dir(
    url: str,
    token: str,
    workspace_id: str,
    dir_path: Path,
    parent_view_id: str,
    image_index: dict[str, Path],
    skip_images: bool,
    dry_run: bool,
    image_cache: dict[str, str],
    counter: list[int],  # [current, total]
    vault_root: Path,
    image_issues: list[str],
    page_ids: dict[str, str] | None = None,
    depth: int = 0,
) -> int:
    """Returns number of pages that failed to create (HTTP errors)."""
    page_errors = 0
    indent = "  " * depth
    entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))

    for entry in entries:
        if entry.name in _SKIP_DIRS or entry.name.startswith("."):
            continue

        if entry.is_dir():
            print(f"{indent}[folder] {entry.name}")
            if not dry_run:
                folder_id = _create_page(url, token, workspace_id,
                                         parent_view_id, entry.name, None)
                time.sleep(_SLEEP_AFTER_FOLDER)
            else:
                folder_id = "dry-run"
            page_errors += _import_dir(url, token, workspace_id, entry, folder_id,
                                        image_index, skip_images, dry_run, image_cache,
                                        counter, vault_root, image_issues, page_ids, depth + 1)

        elif entry.suffix.lower() == ".md":
            name = entry.stem
            text = entry.read_text(encoding="utf-8", errors="replace")
            counter[0] += 1
            prefix = f"[{counter[0]}/{counter[1]}]"

            miss: list[str] = []
            if dry_run:
                page_data = md_to_blocks(text, image_index, None, missing_images=miss,
                                         page_ids=page_ids)
                block_count = len(page_data["children"])
                img_count = sum(1 for b in page_data["children"] if b["type"] == "image")
                print(f"{prefix} {indent}[page] {name}  ({block_count} blocks"
                      + (f", {img_count} imgs" if img_count else "") + ")")
                rel = entry.relative_to(vault_root).as_posix()
                for m in miss:
                    image_issues.append(f"{rel}: unresolved {m}")
                continue

            def _uploader(path: Path) -> str:
                return _upload_image(url, token, workspace_id, path, image_cache)

            uploader = None if skip_images else _uploader
            page_data = md_to_blocks(text, image_index, uploader, missing_images=miss,
                                     page_ids=page_ids)
            rel = entry.relative_to(vault_root).as_posix()
            for m in miss:
                image_issues.append(f"{rel}: unresolved {m}")

            img_count = sum(1 for b in page_data["children"] if b["type"] == "image")
            print(f"{prefix} {indent}[page] {name}"
                  + (f"  ({img_count} imgs)" if img_count else ""))
            assigned_id = (page_ids or {}).get(entry.stem.lower())
            try:
                _create_page(url, token, workspace_id,
                             parent_view_id, name, page_data, view_id=assigned_id)
                time.sleep(_SLEEP_AFTER_PAGE)
            except requests.HTTPError as e:
                page_errors += 1
                print(f"{indent}  ERROR: {e.response.status_code} "
                      f"{e.response.text[:200]}")

    return page_errors


def _n(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _next_space_name(base: str, existing: set[str]) -> str:
    """Return 'base 2', 'base 3', … — first name not in existing."""
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


def _confirm_conflict(space_name: str) -> str:
    """Return 'trash', 'keep', or 'abort'."""
    print("  [r] Replace it (move old space to trash)")
    print("  [k] Keep it and create another space")
    print("  [a] Abort")
    answer = input("Choice: ").strip().lower()
    if answer == "r":
        return "trash"
    if answer == "k":
        return "keep"
    return "abort"


# ── Public entry point ────────────────────────────────────────────────────────

def run_import(
    vault: Path,
    url: str,
    email: str,
    password: str,
    space_name: str,
    space_color: str,
    skip_images: bool,
    dry_run: bool,
) -> int:
    """
    Returns a process exit code: 0 success, 1 user abort, failed page uploads,
    or unresolved image references during a real import.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except AttributeError:
        pass

    image_issues: list[str] = []

    if dry_run:
        print("[DRY RUN] No API calls; nothing is sent to AppFlowy.\n")
        print(f"Building image index from {vault} ...")
        image_index = build_image_index(vault)
        page_ids = _prescan_vault(vault)
        total = _count_md_files(vault)
        print(f"  {_n(len(image_index), 'image')}, {_n(total, 'page')} found.\n")
        print("Vault structure preview:\n")
        _import_dir("", "", "", vault, "", image_index, skip_images,
                    dry_run=True, image_cache={}, counter=[0, total],
                    vault_root=vault, image_issues=image_issues, page_ids=page_ids)
        if image_issues:
            print("\nImage references not found in the vault (fix paths or add files):")
            for line in sorted(set(image_issues)):
                print(f"  - {line}")
            print()
        return 0

    print(f"Authenticating to {url} ...")
    token = _get_token(url, email, password)
    print("OK\n")

    print("Fetching workspace ...")
    workspace_id = _get_workspace_id(url, token)
    print(f"  Workspace: {workspace_id}\n")

    old_spaces = _find_old_spaces(url, token, workspace_id, space_name)
    if old_spaces:
        print(f"Found {len(old_spaces)} existing space(s) named '{space_name}'.")
        action = _confirm_conflict(space_name)
        if action == "abort":
            print("Aborted.")
            return 1
        if action == "trash":
            _trash_spaces(url, token, workspace_id, old_spaces)
        else:
            all_names = {
                child["name"]
                for child in _get(
                    f"{url}/api/workspace/{workspace_id}/folder",
                    headers=_hdrs(token),
                    params={"depth": 1},
                    timeout=_REQUEST_TIMEOUT,
                ).json().get("data", {}).get("children", [])
            }
            space_name = _next_space_name(space_name, all_names)
            print(f"  Will create '{space_name}' instead.")
        print()

    print(f"Building image index from {vault} ...")
    image_index = build_image_index(vault)
    page_ids = _prescan_vault(vault)
    total = _count_md_files(vault)
    print(f"  {_n(len(image_index), 'image')}, {_n(total, 'page')} found.\n")

    print(f"Creating space '{space_name}' ...")
    space_id = _create_space(url, token, workspace_id, space_name, space_color)

    image_cache: dict[str, str] = {}
    print(f"\nImporting {vault} ...\n")
    page_errors = _import_dir(url, token, workspace_id, vault, space_id,
                              image_index, skip_images, dry_run=False,
                              image_cache=image_cache, counter=[0, total],
                              vault_root=vault, image_issues=image_issues,
                              page_ids=page_ids)

    print(f"\nDone!  Uploaded {_n(len(image_cache), 'unique image')}.")
    print(f"Open AppFlowy → find the '{space_name}' space in the left sidebar.")

    exit_code = 0
    if image_issues:
        print("\nImage issues (pages were still created):")
        for line in sorted(set(image_issues)):
            print(f"  - {line}")
        exit_code = 1
    if page_errors:
        print(
            f"\n{page_errors} page(s) failed to upload (see ERROR lines above). "
            "Fix the issue and run again, or create those pages manually."
        )
        exit_code = 1
    return exit_code
