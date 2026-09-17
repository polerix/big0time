#!/usr/bin/env python3
"""
sync_repos.py – big0time portal auto-updater
=============================================
No external dependencies – uses only Python stdlib.

What it does
------------
1. Fetches all public repos for GITHUB_USER via the GitHub API.
2. For each repo, checks whether a github.io Pages site responds (HTTP 200/301/302)
   using a lightweight HEAD request. Repos already listed in index.html are
   always kept without re-checking.
3. Sorts the combined list newest → oldest by pushed_at.
4. Rewrites only the <!-- MENU START --> … <!-- MENU END --> block in index.html,
   preserving every custom name, description, and OPEN URL already there.
5. Operates safely: default execution will not commit or push without explicit flags.

CLI Options
-----------
  --dry-run       Preview changes and show diff without writing to disk
  --commit        Commit changes to git after updating index.html
  --push          Push committed changes to remote repository (requires --commit)
  --html-path     Path to index.html (default: parent directory / index.html)
  --user          GitHub username to sync (default: polerix)
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

GITHUB_USER = "polerix"
DEFAULT_INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"
PAGES_BASE  = f"https://{GITHUB_USER}.github.io"
REPO_BASE   = f"https://github.com/{GITHUB_USER}"
API_BASE    = "https://api.github.com"

# Override the OPEN URL for specific repos.
CUSTOM_OPEN_URLS: dict = {
    # "my-repo": f"{PAGES_BASE}/my-repo/special/path.html",
}

SENTINEL_START = "<!-- MENU START -->"
SENTINEL_END   = "<!-- MENU END -->"

# ── GitHub API helpers ───────────────────────────────────────────────────────

def _gh_headers(token: str = None) -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def gh_get(path: str, params: dict = None, token: str = None):
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers=_gh_headers(token))
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def discover_repos(user: str = GITHUB_USER, token: str = None) -> list:
    """Fetch all public repositories for user via GitHub API with pagination."""
    repos, page = [], 1
    while True:
        batch = gh_get(f"/users/{user}/repos", {
            "type": "public", "per_page": "100",
            "page": str(page), "sort": "pushed",
        }, token=token)
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos


# Backwards compatibility alias
all_repos = discover_repos


def detect_pages(repo_name: str, base_url: str = PAGES_BASE) -> bool:
    """Return True if base_url/<repo>/ responds with a success or redirect."""
    url = f"{base_url}/{repo_name}/"
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "big0time-sync/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as e:
        return e.code < 400   # 301/302 also count
    except Exception:
        return False


# Backwards compatibility alias
pages_live = detect_pages


# ── HTML helpers ─────────────────────────────────────────────────────────────

def esc(s: str) -> str:
    """Escape special HTML characters."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def item_html(name: str, desc: str, open_url: str, repo_url: str) -> str:
    i = "        "   # 8-space indent base
    return (
        f'{i}<div class="item">\n'
        f'{i}  <div class="label">\n'
        f'{i}    <div class="name">{esc(name)}</div>\n'
        f'{i}    <div class="desc">{esc(desc)}</div>\n'
        f'{i}  </div>\n'
        f'{i}  <div class="actions">\n'
        f'{i}    <a href="{open_url}" target="_blank" rel="noopener noreferrer"><button type="button">OPEN</button></a>\n'
        f'{i}    <a href="{repo_url}" target="_blank" rel="noopener noreferrer"><button type="button">REPO</button></a>\n'
        f'{i}  </div>\n'
        f'{i}</div>'
    )


def generate_menu(items: list) -> str:
    """Generate the full menu block surrounded by sentinel comments."""
    parts = "\n\n".join(item_html(**it) for it in items)
    return (
        f"{SENTINEL_START}\n"
        f'      <div class="menu">\n'
        f"{parts}\n"
        f"      </div>\n"
        f"      {SENTINEL_END}"
    )


# Backwards compatibility alias
build_menu_block = generate_menu


# ── Existing-entry parser ────────────────────────────────────────────────────

_NAME_RE = re.compile(r'<div\s+class="name">([^<]*)</div>')
_DESC_RE = re.compile(r'<div\s+class="desc">([^<]*)</div>')
_OPEN_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>[^<]*<button[^>]*>\s*OPEN\s*</button>')
_REPO_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>[^<]*<button[^>]*>\s*REPO\s*</button>')


def parse_existing(html: str) -> dict:
    """Return a dict keyed by repo-name of data already in index.html."""
    existing = {}

    # Narrow to just the sentinel block
    if SENTINEL_START in html and SENTINEL_END in html:
        start = html.index(SENTINEL_START) + len(SENTINEL_START)
        end   = html.index(SENTINEL_END)
        html  = html[start:end]

    chunks = re.split(r'(?=<div\s+class="item">)', html)
    for chunk in chunks:
        rp = _REPO_RE.search(chunk)
        if not rp:
            continue
        repo_url  = rp.group(1).rstrip("/")
        repo_name = repo_url.rsplit("/", 1)[-1]
        nm = _NAME_RE.search(chunk)
        dc = _DESC_RE.search(chunk)
        op = _OPEN_RE.search(chunk)
        existing[repo_name] = {
            "name":     nm.group(1).strip() if nm else repo_name,
            "desc":     dc.group(1).strip() if dc else "",
            "open_url": op.group(1)         if op else f"{PAGES_BASE}/{repo_name}/",
        }
    return existing


def update_html(original_html: str, new_menu: str) -> tuple[str, bool]:
    """Replace sentinel block with new_menu. Returns (new_html, changed)."""
    if SENTINEL_START not in original_html or SENTINEL_END not in original_html:
        raise ValueError("Sentinel comments not found in HTML template")

    pattern = re.escape(SENTINEL_START) + r".*?" + re.escape(SENTINEL_END)
    new_html = re.sub(pattern, new_menu, original_html, flags=re.DOTALL)
    changed = (new_html != original_html)
    return new_html, changed


def diff_output(original: str, new: str, filepath: str = "index.html") -> str:
    """Produce a unified diff string between original and new HTML."""
    orig_lines = original.splitlines(keepends=True)
    new_lines  = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines, new_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    )
    return "".join(diff)


# ── Git safety helpers ───────────────────────────────────────────────────────

def check_worktree(repo_root: Path, target_file: Path = None) -> tuple[bool, str]:
    """
    Check if working tree is clean (excluding target_file if specified).
    Returns (is_clean, status_output).
    """
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root, capture_output=True, text=True, check=True
        )
        lines = [line for line in res.stdout.splitlines() if line.strip()]
        if target_file:
            rel_path = target_file.resolve().relative_to(repo_root.resolve())
            other_changes = [l for l in lines if not l.strip().endswith(str(rel_path))]
            return len(other_changes) == 0, res.stdout
        return len(lines) == 0, res.stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return False, str(e)


def commit_changes(repo_root: Path, html_path: Path, count: int) -> bool:
    """Stage and commit index.html changes."""
    commit_msg = f"Auto-sync: Update {count} repository items"
    try:
        subprocess.run(["git", "add", str(html_path)], cwd=repo_root, check=True)
        res = subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_root, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"  Git commit exited {res.returncode}: {res.stderr.strip()}")
            return False
        print(f"  Committed: {commit_msg}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  ERROR: Git commit failed: {e}")
        return False


def push_changes(repo_root: Path) -> bool:
    """Push commits to remote."""
    try:
        subprocess.run(["git", "push"], cwd=repo_root, check=True)
        print("  Successfully pushed to remote.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  ERROR: Git push failed: {e}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def build_repo_items(included: list, existing: dict, user: str = GITHUB_USER) -> list:
    """Build item dictionaries for menu rendering."""
    items = []
    for repo in included:
        name = repo["name"]
        ex   = existing.get(name, {})
        if name in CUSTOM_OPEN_URLS:
            open_url = CUSTOM_OPEN_URLS[name]
        elif ex.get("open_url"):
            open_url = ex["open_url"]
        else:
            open_url = f"https://{user}.github.io/{name}/"
        items.append({
            "name":     ex.get("name") or name,
            "desc":     ex.get("desc") or repo.get("description") or "",
            "open_url": open_url,
            "repo_url": f"https://github.com/{user}/{name}",
        })
    return items


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize big0time portal index.html with live GitHub repositories."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes and display diff without writing to disk or making git commits."
    )
    parser.add_argument(
        "--commit", action="store_true",
        help="Commit updated index.html to git."
    )
    parser.add_argument(
        "--push", action="store_true",
        help="Push committed changes to remote (requires --commit)."
    )
    parser.add_argument(
        "--html-path", type=Path, default=DEFAULT_INDEX_HTML,
        help=f"Path to index.html (default: {DEFAULT_INDEX_HTML})"
    )
    parser.add_argument(
        "--user", type=str, default=GITHUB_USER,
        help=f"GitHub username (default: {GITHUB_USER})"
    )

    args = parser.parse_args(argv)

    if args.push and not args.commit:
        print("ERROR: --push requires --commit.")
        return 1

    html_file = args.html_path.resolve()
    repo_root = html_file.parent

    if not html_file.exists():
        print(f"ERROR: Target file does not exist: {html_file}")
        return 1

    print(f"Reading {html_file}")
    original_html = html_file.read_text(encoding="utf-8")
    existing = parse_existing(original_html)
    print(f"  Existing entries ({len(existing)}): {', '.join(existing.keys())}")

    print(f"\nFetching repos for @{args.user} via GitHub API …")
    try:
        all_r = discover_repos(user=args.user)
    except Exception as e:
        print(f"ERROR fetching repositories: {e}")
        return 1

    included = []
    for repo in all_r:
        name = repo["name"]
        if name == "big0time":
            continue
        if name in existing:
            included.append(repo)
        elif detect_pages(name, base_url=f"https://{args.user}.github.io"):
            included.append(repo)
            print(f"  + New live Pages site found: {name}")

    included.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    print(f"\n  Rendering {len(included)} item(s) …")

    items = build_repo_items(included, existing, user=args.user)
    new_menu = generate_menu(items)

    try:
        new_html, changed = update_html(original_html, new_menu)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    if not changed:
        print("\nNo changes – index.html is already up to date.")
        return 0

    diff = diff_output(original_html, new_html, filepath=html_file.name)
    print("\n--- Diff Preview ---")
    print(diff)

    if args.dry_run:
        print("\n[DRY RUN] Would update index.html with new menu. No files written.")
        return 0

    html_file.write_text(new_html, encoding="utf-8")
    print(f"\nDone. Wrote {html_file} with {len(items)} item(s).")

    if args.commit:
        clean, status = check_worktree(repo_root, target_file=html_file)
        if not clean:
            print("WARNING: Worktree has other uncommitted changes:\n" + status)
        committed = commit_changes(repo_root, html_file, len(items))
        if not committed:
            return 1

        if args.push:
            pushed = push_changes(repo_root)
            if not pushed:
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
