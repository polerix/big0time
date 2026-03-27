#!/usr/bin/env python3
"""
sync_repos.py – big0time portal auto-updater
=============================================
No external dependencies – uses only Python stdlib.

What it does
------------
1. Fetches all public repos for GITHUB_USER via the GitHub API.
2. For each repo, checks whether a github.io Pages site responds (HTTP 200/301/302)
   using a lightweight HEAD request.  Repos already listed in index.html are
   always kept without re-checking.
3. Sorts the combined list newest → oldest by pushed_at.
4. Rewrites only the <!-- MENU START --> … <!-- MENU END --> block in index.html,
   preserving every custom name, description, and OPEN URL already there.

Setup
-----
  Optional: set env var GITHUB_TOKEN for 5 000 req/hr instead of 60 req/hr.

Run manually
------------
  python3 scripts/sync_repos.py

Cron example (daily at 03:00 local time):
  0 3 * * * cd /Users/yourname/Documents/GitHub/big0time && python3 scripts/sync_repos.py >> /tmp/sync_repos.log 2>&1
"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

GITHUB_USER = "polerix"
INDEX_HTML  = Path(__file__).parent.parent / "index.html"
PAGES_BASE  = f"https://{GITHUB_USER}.github.io"
REPO_BASE   = f"https://github.com/{GITHUB_USER}"
API_BASE    = "https://api.github.com"

# Override the OPEN URL for specific repos.
# Items already listed in index.html keep their saved OPEN URL automatically.
# Add entries here only to force a particular path for NEW, not-yet-listed repos.
CUSTOM_OPEN_URLS: dict = {
    # "my-repo": f"{PAGES_BASE}/my-repo/special/path.html",
}

# ── GitHub API helpers ───────────────────────────────────────────────────────

def _gh_headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def gh_get(path: str, params: dict = None):
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers=_gh_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def all_repos() -> list:
    repos, page = [], 1
    while True:
        batch = gh_get(f"/users/{GITHUB_USER}/repos", {
            "type": "public", "per_page": "100",
            "page": str(page), "sort": "pushed",
        })
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos


def pages_live(repo_name: str) -> bool:
    """Return True if polerix.github.io/<repo>/ responds with a success or redirect."""
    url = f"{PAGES_BASE}/{repo_name}/"
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "big0time-sync/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as e:
        return e.code < 400   # 301/302 also count
    except Exception:
        return False


# ── HTML helpers ─────────────────────────────────────────────────────────────

SENTINEL_START = "<!-- MENU START -->"
SENTINEL_END   = "<!-- MENU END -->"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


def build_menu_block(items: list) -> str:
    parts = "\n\n".join(item_html(**it) for it in items)
    return (
        f"{SENTINEL_START}\n"
        f'      <div class="menu">\n'
        f"{parts}\n"
        f"      </div>\n"
        f"      {SENTINEL_END}"
    )


# ── Existing-entry parser ────────────────────────────────────────────────────
# Simple patterns that work on individual item chunks (no nested-div ambiguity).
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

    # Split on item boundaries – avoids nested </div> ambiguity entirely
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


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Reading {INDEX_HTML}")
    original_html = INDEX_HTML.read_text(encoding="utf-8")
    existing      = parse_existing(original_html)
    print(f"  Existing entries ({len(existing)}): {', '.join(existing)}")

    print(f"\nFetching repos for @{GITHUB_USER} via GitHub API …")
    all_r    = all_repos()
    included = []

    for repo in all_r:
        name = repo["name"]
        if name == "big0time":
            continue
        if name in existing:
            included.append(repo)          # already listed → always keep
        elif pages_live(name):
            included.append(repo)
            print(f"  + New live Pages site found: {name}")

    # Sort newest-first by last push date
    included.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    print(f"\n  Rendering {len(included)} item(s) …")

    items = []
    for repo in included:
        name = repo["name"]
        ex   = existing.get(name, {})
        if name in CUSTOM_OPEN_URLS:
            open_url = CUSTOM_OPEN_URLS[name]
        elif ex.get("open_url"):
            open_url = ex["open_url"]
        else:
            open_url = f"{PAGES_BASE}/{name}/"
        items.append({
            "name":     ex.get("name") or name,
            "desc":     ex.get("desc") or repo.get("description") or "",
            "open_url": open_url,
            "repo_url": f"{REPO_BASE}/{name}",
        })

    new_menu = build_menu_block(items)

    if SENTINEL_START in original_html and SENTINEL_END in original_html:
        new_html = re.sub(
            re.escape(SENTINEL_START) + r".*?" + re.escape(SENTINEL_END),
            new_menu,
            original_html,
            flags=re.DOTALL,
        )
    else:
        print("ERROR: sentinel comments not found in index.html – aborting.")
        return

    if new_html == original_html:
        print("\nNo changes – index.html is already up to date.")
        return

    INDEX_HTML.write_text(new_html, encoding="utf-8")
    print(f"\nDone. Wrote {INDEX_HTML} with {len(items)} item(s).")

    print("\nCommitting and pushing changes to GitHub…")
    repo_root = INDEX_HTML.parent
    commit_msg = f"Auto-sync: Update {len(items)} repository items"
    try:
        subprocess.run(["git", "add", str(INDEX_HTML)], cwd=repo_root, check=True)
        # The commit may fail if there are no changes, so we don't check=True
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_root)
        subprocess.run(["git", "push"], cwd=repo_root, check=True)
        print("  Successfully pushed to remote.")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  ERROR: Git operation failed: {e}")
        print("  Please ensure 'git' is in your PATH and that this script has push access.")


if __name__ == "__main__":
    main()
