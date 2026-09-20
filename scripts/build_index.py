#!/usr/bin/env python3
"""
build_index.py: rebuild the catalogue block of index.html from GitHub's public data.

Runs unattended every 4 hours (see .github/workflows/index.yml). Standard library only.
It rewrites ONLY the text between <!-- MENU START --> and <!-- MENU END -->, leaving the
rest of the page (styles, nav, scripts) untouched.

Sections (they map onto the existing page sections and nav filters):
  01 // PINNED SITES         repos that EARN a pin: working site + activity + polish (score, see score())
  02 // NEWLY CHANGED        working sites created recently (NEW) or pushed recently (RECENT)
  03 // WHATEVER             every other repo with a working website
  04 // LEGACY HOLDING GRID   at the bottom: non-web repos, dead sites, archived, then forks

Never lists empty repos (they are only reported), never lists private repos (the API sees
public data only), and refuses to write if the result would drop most of the existing cards
(guards against a partial API answer wiping the page).

  python3 scripts/build_index.py                  rewrite index.html
  python3 scripts/build_index.py --dry-run        print the report, change nothing
  python3 scripts/build_index.py --report FILE    append a markdown report (e.g. $GITHUB_STEP_SUMMARY)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- MENU START -->", "<!-- MENU END -->"
API = "https://api.github.com"

DEFAULTS = {
    "user": "polerix",
    "pin_limit": 14,
    "pin_min_score": 60,
    "pin_prefer": [],          # GitHub repo names that get a small bonus (keeps curated pins from churning)
    "pin_lock": [],            # always pinned
    "pin_exclude": [],         # never pinned
    "hidden": [],              # never listed
    "new_days": 30,
    "recent_days": 7,
    "extras": [],              # sites whose repos are private/other: {"name","url","desc"}
    "no_execute": [],          # repos whose site is known not to work: listed at the bottom with REPOS only
    "descriptions": {},        # slug -> hand-written description (beats the GitHub one)
    "titles": {},              # slug -> display name
    "min_keep_ratio": 0.5,     # refuse to write if fewer than this share of existing cards survive
}


# ── helpers ──────────────────────────────────────────────────────────────────

def esc(s) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def safe_url(u):
    """Only http(s) URLs with a host are ever placed in an href."""
    try:
        p = urlparse(str(u or "").strip())
    except ValueError:
        return None
    return p.geturl() if p.scheme in ("http", "https") and p.netloc else None


def slug(v) -> str:
    """Case/punctuation-insensitive key: 'SquareWatch' == 'squarewatch', 'ESPER machine' == 'esper-machine'."""
    return re.sub(r"[^a-z0-9]+", "-", str(v or "").strip().lower()).strip("-")


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def days_ago(ts, now):
    return (now - ts).total_seconds() / 86400 if ts else 1e9


def load_config(path: Path) -> dict:
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    return cfg


# ── GitHub + site checks (the only network code) ─────────────────────────────

def _headers():
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "big0time-index"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return h


def fetch_repos(user: str) -> list:
    repos, page = [], 1
    while True:
        req = urllib.request.Request(f"{API}/users/{user}/repos?type=owner&per_page=100&page={page}", headers=_headers())
        with urllib.request.urlopen(req, timeout=20) as r:
            batch = json.loads(r.read())
        if not batch:
            return repos
        repos.extend(batch)
        page += 1


# Housekeeping commits (steward, Dependabot, bots) must not make a repo look "recently updated".
HOUSEKEEPING = re.compile(r"steward|dependabot|^bump |^build\(deps|^chore\(deps|licen[cs]e|security-policy|^merge pull request", re.I)


def meaningful_date(commits: list):
    """Date of the newest commit that is real work. Falls back to the oldest commit seen."""
    last = None
    for c in commits:
        info = c.get("commit", {})
        last = parse_ts((info.get("committer") or info.get("author") or {}).get("date"))
        author = (c.get("author") or {}).get("login", "") or ""
        first_line = (info.get("message") or "").split("\n", 1)[0]
        if author.endswith("[bot]") or HOUSEKEEPING.search(first_line):
            continue
        return last
    return last


def fetch_updated(user: str, name: str):
    """Newest meaningful commit date, or None if the API refuses (rate limit) so callers fall back to pushed_at."""
    try:
        req = urllib.request.Request(f"{API}/repos/{user}/{quote(name)}/commits?per_page=15", headers=_headers())
        with urllib.request.urlopen(req, timeout=20) as r:
            return meaningful_date(json.loads(r.read()))
    except Exception:
        return None


def check_site(url: str) -> bool:
    """A site works if it answers 2xx/3xx (after redirects) within 10 seconds. One retry."""
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "big0time-index"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status < 400
        except urllib.error.HTTPError as e:
            if e.code < 400:
                return True
            if e.code == 404:
                return False
        except Exception:
            pass
    return False


# ── classification (pure) ────────────────────────────────────────────────────

def site_url(repo: dict, user: str):
    hp = safe_url(repo.get("homepage"))
    if hp:
        return hp
    if repo.get("has_pages"):
        return f"https://{user}.github.io/{quote(repo['name'])}/"
    return None


def score(entry: dict, cfg: dict, now, has_screenshot: bool) -> int:
    """How much a repo earns a pin. Needs a working site (otherwise 0)."""
    if not entry["site_ok"]:
        return 0
    age = days_ago(entry["pushed"], now)
    s = 40
    s += 15 if age <= 30 else 5 if age <= 90 else 0
    s += 10 if age <= cfg["recent_days"] else 0
    s += 10 if entry["desc"] else 0
    s += 5 if entry["custom_site"] or entry["topics"] else 0
    s += min(entry["stars"], 10) * 2
    s += 10 if has_screenshot else 0
    s += 15 if slug(entry["name"]) in {slug(n) for n in cfg["pin_prefer"]} else 0
    return s


def plan(repos, site_ok: dict, now, cfg: dict, screenshots: set):
    """Return (sections, report). site_ok maps a site URL to whether it answered."""
    user = cfg["user"]
    hidden = {slug(h) for h in cfg["hidden"]}
    no_exec = {slug(h) for h in cfg["no_execute"]}
    descs = {slug(k): v for k, v in cfg["descriptions"].items()}
    titles = {slug(k): v for k, v in cfg["titles"].items()}
    entries, empties = [], []
    for r in repos:
        if r.get("private") or (r.get("visibility") not in (None, "public")) or slug(r["name"]) in hidden:
            continue
        if r.get("size", 1) == 0 and not r.get("fork"):   # forks often report size 0 without being empty
            empties.append(r["name"])
            continue
        url = site_url(r, user)
        entries.append({
            "name": r["name"], "title": titles.get(slug(r["name"]), r["name"]), "manual_broken": slug(r["name"]) in no_exec,
            "desc": (descs.get(slug(r["name"])) or r.get("description") or "").strip(), "fork": bool(r.get("fork")),
            "archived": bool(r.get("archived")), "language": r.get("language"), "stars": r.get("stargazers_count", 0),
            "topics": r.get("topics") or [], "pushed": r.get("_updated") or parse_ts(r.get("pushed_at")), "created": parse_ts(r.get("created_at")),
            "url": url, "custom_site": bool(safe_url(r.get("homepage"))), "site_ok": bool(url and site_ok.get(url)),
            "repo_url": f"https://github.com/{user}/{quote(r['name'])}", "extra": False,
        })
    for x in cfg["extras"]:
        u = safe_url(x.get("url"))
        if not u:
            continue
        entries.append({"name": x["name"], "title": titles.get(slug(x["name"]), x["name"]), "manual_broken": False,
                        "desc": descs.get(slug(x["name"])) or x.get("desc", ""), "fork": False, "archived": False, "language": None,
                        "stars": 0, "topics": [], "pushed": parse_ts(x.get("pushed_at")) or now - timedelta(days=45),
                        "created": None, "url": u, "custom_site": True, "site_ok": bool(site_ok.get(u)), "repo_url": None, "extra": True})

    for e in entries:
        if e["manual_broken"]:
            e["site_ok"] = False
    for e in entries:
        e["is_new"] = bool(e["created"]) and days_ago(e["created"], now) <= cfg["new_days"]
        e["is_recent"] = days_ago(e["pushed"], now) <= cfg["recent_days"]
        e["site_down"] = bool(e["url"]) and not e["site_ok"] and not e["manual_broken"]
        e["score"] = score(e, cfg, now, e["name"].lower() in screenshots)

    def eligible(e):
        return e["site_ok"] and not e["fork"] and not e["archived"]

    lock = {slug(n) for n in cfg["pin_lock"]}
    excl = {slug(n) for n in cfg["pin_exclude"]}
    ranked = sorted((e for e in entries if eligible(e) and slug(e["name"]) not in excl and (e["score"] >= cfg["pin_min_score"] or slug(e["name"]) in lock)),
                    key=lambda e: (slug(e["name"]) not in lock, -e["score"], -(e["pushed"].timestamp() if e["pushed"] else 0)))
    pinned = ranked[: cfg["pin_limit"]]
    pinned_names = {e["name"] for e in pinned}
    rest = [e for e in entries if e["name"] not in pinned_names]

    newest = lambda e: -(e["pushed"].timestamp() if e["pushed"] else 0)
    changed = sorted((e for e in rest if eligible(e) and (e["is_new"] or e["is_recent"])), key=newest)
    changed_names = {e["name"] for e in changed}
    whatever = sorted((e for e in rest if eligible(e) and e["name"] not in changed_names), key=newest)
    used = pinned_names | changed_names | {e["name"] for e in whatever}
    legacy_rest = [e for e in rest if e["name"] not in used]
    # bottom of the page: non-web / dead / archived first, forks last
    legacy = sorted((e for e in legacy_rest if not e["fork"]), key=newest) + sorted((e for e in legacy_rest if e["fork"]), key=newest)

    report = {
        "total": len(entries), "pinned": [e["name"] for e in pinned], "changed": len(changed), "whatever": len(whatever),
        "legacy": len(legacy), "forks": sum(1 for e in legacy if e["fork"]), "non_web": sum(1 for e in legacy if not e["fork"] and not e["url"]),
        "empty": sorted(empties), "repo_only": sorted(e["name"] for e in entries if e["manual_broken"] and not e["fork"]), "site_down": sorted(e["name"] for e in entries if e["site_down"] and not e["fork"]),
    }
    return {"pinned": pinned, "changed": changed, "whatever": whatever, "legacy": legacy}, report


# ── rendering ────────────────────────────────────────────────────────────────

def tags(e, section):
    t = []
    if e["site_ok"]:
        t.append('<span class="lcars-tag tag-static">🌐 PAGES</span>')
    if e["is_new"]:
        t.append('<span class="lcars-tag tag-new">✨ NEW</span>')
    if e["is_recent"]:
        t.append('<span class="lcars-tag tag-recent">🔥 RECENT</span>')
    if e["fork"]:
        t.append('<span class="lcars-tag tag-muted">⑂ FORK</span>')
    elif section == "legacy" and e["manual_broken"]:
        t.append('<span class="lcars-tag tag-muted">📦 REPO ONLY</span>')
    elif section == "legacy" and e["site_down"]:
        t.append('<span class="lcars-tag tag-muted">🔧 SITE DOWN</span>')
    elif section == "legacy" and e["archived"]:
        t.append('<span class="lcars-tag tag-muted">🗄 ARCHIVED</span>')
    elif section == "legacy" and not e["url"]:
        t.append('<span class="lcars-tag tag-muted">⌨ NON-WEB</span>')
    return "".join(t)


def card(e, section, idx):
    cat = {"pinned": "pinned", "changed": "business", "whatever": "games", "legacy": "toys"}[section]
    prefix = {"pinned": "PRIORITY", "changed": "NEW", "whatever": "WEB", "legacy": "LEG"}[section]
    name, desc = esc(e["title"]), esc(e["desc"][:140] + ("..." if len(e["desc"]) > 140 else ""))
    search = esc((e["title"] + " " + e["desc"])[:160].lower())
    cls = "bubble pinned" if section == "pinned" else "bubble"
    style = ""
    if section == "pinned":
        shot = f"resources/screenshots/{e['name'].lower()}.png"
        style = f' style="--bg-image: url({esc(shot)});"' if e.get("has_shot") else ""
    head = ('<span class="lcars-tag tag-pinned">🥇 FEATURED</span>' if section == "pinned"
            else f'<div class="card-badges">{tags(e, section)}</div>')
    acts = []
    if e["site_ok"] and e["url"]:
        acts.append(f'<a href="{esc(e["url"])}" target="_blank" rel="noopener noreferrer"><button class="lcars-btn open-btn">EXECUTE</button></a>')
    if e["repo_url"]:
        acts.append(f'<a href="{esc(e["repo_url"])}" target="_blank" rel="noopener noreferrer"><button class="lcars-btn repo-btn">REPOS</button></a>')
    a = "\n            ".join(acts)
    return (f'        <div class="{cls}" data-category="{cat}" data-name="{esc(slug(e["name"]))}" data-search="{search}"{style}>\n'
            f'          <div class="card-header">\n            <span class="sys-id">LCARS-{prefix}-{idx:02d}</span>\n            {head}\n          </div>\n'
            f'          <div class="name">{name}</div>\n          <div class="desc">{desc}</div>\n'
            f'          <div class="actions">\n            {a}\n          </div>\n        </div>')


SECTION_HEAD = {
    "pinned": ('    <!-- SECTION: PINNED SITES -->\n    <div class="lcars-section-header amber">\n      <div class="lcars-elbow-top"></div>\n'
               '      <div class="lcars-header-text">01 // PINNED SITES</div>\n      <div class="lcars-header-bar"></div>\n    </div>\n    <div class="grid" id="grid-pinned">'),
    "changed": ('    <!-- SECTION: NEWLY CHANGED -->\n    <div class="lcars-section-header gold" id="sec-business">\n      <div class="lcars-elbow-top"></div>\n'
                '      <div class="lcars-header-text">02 // NEWLY CHANGED</div>\n      <div class="lcars-header-bar"></div>\n    </div>\n    <div class="grid" id="grid-business">'),
    "whatever": ('    <!-- SECTION: WHATEVER -->\n    <div class="lcars-section-header blue" id="sec-games">\n      <div class="lcars-elbow-top"></div>\n'
                 '      <div class="lcars-header-text">03 // WHATEVER</div>\n      <div class="lcars-header-bar"></div>\n    </div>\n    <div class="grid" id="grid-games">'),
    "legacy": ('    <!-- SECTION: LEGACY HOLDING GRID -->\n    <div class="lcars-section-header purple" id="sec-toys">\n      <div class="lcars-elbow-top"></div>\n'
               '      <div class="lcars-header-text">04 // LEGACY HOLDING GRID</div>\n      <div class="lcars-header-bar"></div>\n    </div>\n    <div class="grid" id="grid-toys">'),
}


def render_block(sections, screenshots=frozenset()):
    parts = []
    for key in ("pinned", "changed", "whatever", "legacy"):
        for e in sections[key]:
            e["has_shot"] = e["name"].lower() in screenshots
        cards = "\n".join(card(e, key, i) for i, e in enumerate(sections[key], 1))
        head = re.sub(r"(<div class=\"lcars-header-text\">[^<]*?)(</div>)", lambda m: f"{m.group(1)} ({len(sections[key])} NODES){m.group(2)}", SECTION_HEAD[key], count=1)
        parts.append(head + ("\n" + cards if cards else "") + "\n    </div>\n")
    return f"{START}\n" + "\n".join(parts) + f"\n{END}"


def replace_block(html: str, block: str) -> str:
    if html.count(START) != 1 or html.count(END) != 1 or html.index(START) > html.index(END):
        raise ValueError("index.html must contain exactly one MENU START and one MENU END, in order")
    i, j = html.index(START), html.index(END) + len(END)
    # keep the original indentation of the START marker line
    line_start = html.rfind("\n", 0, i) + 1
    return html[:line_start] + "      " + block + html[j:]


def count_cards(html: str) -> int:
    if START not in html:
        return 0
    return html[html.index(START): html.index(END)].count('class="bubble')


def markdown_report(rep, changed: bool) -> str:
    lines = ["## Index refresh", "",
             f"- Listed: **{rep['total']}** repos | pinned **{len(rep['pinned'])}** | new/recent **{rep['changed']}** | other web **{rep['whatever']}** | legacy **{rep['legacy']}** ({rep['forks']} forks, {rep['non_web']} non-web)",
             f"- index.html {'**changed**' if changed else 'unchanged'}", "",
             f"**Pinned now:** {', '.join(rep['pinned']) or 'none'}", ""]
    if rep["empty"]:
        lines += [f"**Empty repos (not listed, delete or fill them):** {', '.join(rep['empty'])}", ""]
    if rep.get("repo_only"):
        lines += [f"**Marked repo-only in config (no EXECUTE):** {len(rep['repo_only'])} repos", ""]
    if rep["site_down"]:
        lines += [f"**Sites that are configured but not answering:** {', '.join(rep['site_down'])}", ""]
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="skip the shrink guard")
    ap.add_argument("--report", help="append a markdown report to this file")
    ap.add_argument("--index", default=str(ROOT / "index.html"))
    ap.add_argument("--config", default=str(ROOT / "config" / "index.json"))
    a = ap.parse_args(argv)

    cfg = load_config(Path(a.config))
    now = datetime.now(timezone.utc)
    repos = fetch_repos(cfg["user"])
    urls = {site_url(r, cfg["user"]) for r in repos if (r.get("size", 1) or r.get("fork")) and not r.get("private")} | {safe_url(x.get("url")) for x in cfg["extras"]}
    urls.discard(None)
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        site_ok = dict(zip(sorted(urls), ex.map(check_site, sorted(urls))))
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        live_repos = [r for r in repos if not r.get("private") and (r.get("size", 1) or r.get("fork"))]
        for r, d in zip(live_repos, ex.map(lambda r: fetch_updated(cfg["user"], r["name"]), live_repos)):
            if d:
                r["_updated"] = d
    shots = {p.stem for p in (ROOT / "resources" / "screenshots").glob("*.png")} if (ROOT / "resources" / "screenshots").exists() else set()

    sections, rep = plan(repos, site_ok, now, cfg, shots)
    old = Path(a.index).read_text(encoding="utf-8")
    new = replace_block(old, render_block(sections, shots))
    before, after = count_cards(old), count_cards(new)
    if before and after < before * cfg["min_keep_ratio"] and not a.force:
        print(f"REFUSING to write: {before} cards would shrink to {after} (guard {cfg['min_keep_ratio']}). Use --force if intended.", file=sys.stderr)
        return 2
    changed = new != old
    text = markdown_report(rep, changed)
    print(text)
    if a.report:
        with open(a.report, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    if changed and not a.dry_run:
        Path(a.index).write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
