import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_index", ROOT / "scripts" / "build_index.py")
bi = importlib.util.module_from_spec(spec)
sys.modules["build_index"] = bi
spec.loader.exec_module(bi)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def iso(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo(name, pushed=100, created=400, **kw):
    r = {"name": name, "description": "desc " + name, "fork": False, "archived": False, "size": 10, "has_pages": True,
         "homepage": None, "language": "JavaScript", "stargazers_count": 0, "topics": [], "visibility": "public",
         "pushed_at": iso(pushed), "created_at": iso(created)}
    r.update(kw)
    return r


def url(name):
    return f"https://polerix.github.io/{name}/"


CFG = dict(bi.DEFAULTS, pin_limit=2, pin_min_score=60)


def run(repos, live=None, cfg=CFG, shots=frozenset()):
    live = {url(r["name"]) for r in repos} if live is None else live
    return bi.plan(repos, {u: True for u in live}, NOW, cfg, set(shots))


class Sections(unittest.TestCase):
    def test_each_repo_lands_in_exactly_one_section(self):
        repos = [repo("a", pushed=1), repo("b", created=5, pushed=200), repo("c"), repo("d", has_pages=False), repo("e", fork=True), repo("f", archived=True)]
        secs, _ = run(repos)
        names = [e["name"] for k in secs for e in secs[k]]
        self.assertEqual(sorted(names), sorted(r["name"] for r in repos))
        self.assertEqual(len(names), len(set(names)))

    def test_new_and_recent_go_to_changed(self):
        secs, _ = run([repo("newish", created=5, pushed=50), repo("hot", pushed=2, created=500), repo("old", pushed=300)], cfg=dict(CFG, pin_limit=0))
        self.assertEqual({e["name"] for e in secs["changed"]}, {"newish", "hot"})
        self.assertEqual([e["name"] for e in secs["whatever"]], ["old"])

    def test_forks_non_web_dead_and_archived_are_at_the_bottom_forks_last(self):
        repos = [repo("fork1", fork=True, pushed=1), repo("cli", has_pages=False, pushed=10), repo("dead", pushed=20), repo("arch", archived=True), repo("ok", pushed=200)]
        secs, rep = run(repos, live={url("ok"), url("fork1")}, cfg=dict(CFG, pin_limit=0))
        legacy = [e["name"] for e in secs["legacy"]]
        self.assertEqual(legacy[-1], "fork1")
        self.assertEqual(set(legacy), {"fork1", "cli", "dead", "arch"})
        self.assertIn("dead", rep["site_down"])
        self.assertEqual([e["name"] for e in secs["whatever"]], ["ok"])

    def test_empty_and_private_repos_are_never_listed_but_empties_are_reported(self):
        secs, rep = run([repo("full"), repo("hollow", size=0), repo("secret", private=True, visibility="private")])
        names = [e["name"] for k in secs for e in secs[k]]
        self.assertEqual(names, ["full"])
        self.assertEqual(rep["empty"], ["hollow"])

    def test_hidden_repos_are_skipped(self):
        secs, _ = run([repo("keep"), repo("Skip")], cfg=dict(CFG, hidden=["skip"]))
        self.assertEqual([e["name"] for k in secs for e in secs[k]], ["keep"])


class Pinning(unittest.TestCase):
    def test_needs_a_working_site(self):
        secs, _ = run([repo("nosite", has_pages=False, pushed=1, stargazers_count=10)])
        self.assertEqual(secs["pinned"], [])

    def test_activity_and_polish_earn_pins_up_to_the_limit(self):
        repos = [repo("hot", pushed=1, stargazers_count=5), repo("warm", pushed=20), repo("cold", pushed=400, description=""), repo("hot2", pushed=2)]
        secs, rep = run(repos, cfg=dict(CFG, pin_limit=2))
        self.assertEqual(len(secs["pinned"]), 2)
        self.assertEqual(secs["pinned"][0]["name"], "hot")
        self.assertNotIn("cold", rep["pinned"])

    def test_below_min_score_is_not_pinned_and_prefer_helps(self):
        cold = repo("cold", pushed=400, description="")
        secs, _ = run([cold], cfg=dict(CFG, pin_limit=5))
        self.assertEqual(secs["pinned"], [])
        secs, _ = run([cold], cfg=dict(CFG, pin_limit=5, pin_min_score=40, pin_prefer=["cold"]))
        self.assertEqual([e["name"] for e in secs["pinned"]], ["cold"])

    def test_lock_always_wins_and_exclude_never(self):
        repos = [repo("star", pushed=1, stargazers_count=10), repo("locked", pushed=400, description="")]
        secs, _ = run(repos, cfg=dict(CFG, pin_limit=1, pin_lock=["locked"]))
        self.assertEqual([e["name"] for e in secs["pinned"]], ["locked"])
        secs, _ = run(repos, cfg=dict(CFG, pin_limit=2, pin_exclude=["star"]))
        self.assertNotIn("star", [e["name"] for e in secs["pinned"]])

    def test_forks_and_archived_cannot_be_pinned(self):
        secs, _ = run([repo("f", fork=True, pushed=1), repo("a", archived=True, pushed=1)])
        self.assertEqual(secs["pinned"], [])

    def test_extras_are_listed_by_url_without_a_repo_link(self):
        cfg = dict(CFG, extras=[{"name": "private-site", "url": "https://polerix.github.io/private-site/", "desc": "d"}], pin_limit=0)
        secs, _ = run([], live={"https://polerix.github.io/private-site/"}, cfg=cfg)
        block = bi.render_block(secs)
        self.assertIn("private-site", block)
        self.assertIn("EXECUTE", block)
        self.assertNotIn("REPOS", block)


class Rendering(unittest.TestCase):
    def test_untrusted_text_is_escaped(self):
        evil = repo("x", description='<img src=x onerror=alert(1)> "quote"', homepage="javascript:alert(1)")
        secs, _ = run([evil])
        block = bi.render_block(secs)
        self.assertNotIn("<img", block)
        self.assertNotIn("javascript:", block)
        self.assertIn("&lt;img", block)

    def test_only_http_urls_are_allowed(self):
        self.assertIsNone(bi.safe_url("javascript:alert(1)"))
        self.assertIsNone(bi.safe_url("data:text/html,x"))
        self.assertIsNone(bi.safe_url("//evil"))
        self.assertEqual(bi.safe_url("https://a.b/c"), "https://a.b/c")

    def test_replace_block_touches_only_the_marked_region(self):
        html = "HEAD\n      <!-- MENU START -->\nSTALE-CONTENT\n<!-- MENU END -->\nTAIL\n"
        secs, _ = run([repo("a")])
        out = bi.replace_block(html, bi.render_block(secs))
        self.assertTrue(out.startswith("HEAD\n"))
        self.assertTrue(out.endswith("\nTAIL\n"))
        self.assertNotIn("STALE-CONTENT", out)
        self.assertEqual(out.count(bi.START), 1)

    def test_replace_block_is_idempotent(self):
        html = "H\n      <!-- MENU START -->\nSTALE-CONTENT\n<!-- MENU END -->\nT\n"
        secs, _ = run([repo("a"), repo("b", pushed=1)])
        once = bi.replace_block(html, bi.render_block(secs))
        twice = bi.replace_block(once, bi.render_block(secs))
        self.assertEqual(once, twice)

    def test_missing_or_duplicate_markers_are_rejected(self):
        for bad in ("no markers", f"{bi.START} {bi.START} {bi.END}", f"{bi.END} {bi.START}"):
            with self.assertRaises(ValueError):
                bi.replace_block(bad, "x")

    def test_section_ids_and_categories_match_the_page_filters(self):
        secs, _ = run([repo("a")])
        block = bi.render_block(secs)
        for needle in ('id="grid-pinned"', 'id="grid-business"', 'id="grid-games"', 'id="grid-toys"',
                       'id="sec-business"', 'id="sec-games"', 'id="sec-toys"',
                       "01 // PINNED SITES", "02 // NEWLY CHANGED", "03 // WHATEVER", "04 // LEGACY HOLDING GRID"):
            self.assertIn(needle, block)

    def test_real_page_has_exactly_one_marker_pair_and_the_new_tag_css(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count(bi.START), 1)
        self.assertEqual(html.count(bi.END), 1)
        self.assertIn(".tag-new", html)

    def test_card_count(self):
        secs, _ = run([repo("a"), repo("b", has_pages=False), repo("c", fork=True)])
        self.assertEqual(bi.count_cards(bi.render_block(secs)), 3)


class Housekeeping(unittest.TestCase):
    def commit(self, msg, days, login="polerix"):
        return {"commit": {"message": msg, "committer": {"date": iso(days)}}, "author": {"login": login}}

    def test_steward_dependabot_and_bot_commits_do_not_count_as_updates(self):
        commits = [self.commit("chore: steward housekeeping (#3)", 0), self.commit("Bump vite from 5 to 6", 1, "dependabot[bot]"),
                   self.commit("chore(steward): license-missing (#2)", 2), self.commit("feat: add level 3", 40)]
        self.assertEqual(bi.meaningful_date(commits), bi.parse_ts(iso(40)))

    def test_falls_back_to_the_oldest_seen_when_everything_is_housekeeping(self):
        commits = [self.commit("chore: steward housekeeping", 0), self.commit("chore(steward): x", 5)]
        self.assertEqual(bi.meaningful_date(commits), bi.parse_ts(iso(5)))

    def test_empty_history_gives_none(self):
        self.assertIsNone(bi.meaningful_date([]))

    def test_updated_date_overrides_pushed_at_so_housekeeping_pushes_are_not_recent(self):
        r = repo("quiet", pushed=0)            # pushed today (by a bot)...
        r["_updated"] = bi.parse_ts(iso(200))  # ...but last real work was 200 days ago
        secs, _ = run([r], cfg=dict(CFG, pin_limit=0))
        self.assertEqual(secs["changed"], [])
        self.assertEqual([e["name"] for e in secs["whatever"]], ["quiet"])

    def test_forks_reporting_size_zero_are_not_called_empty(self):
        secs, rep = run([repo("fork0", size=0, fork=True)])
        self.assertEqual(rep["empty"], [])


class Curation(unittest.TestCase):
    def test_slug_matching_ignores_case_and_punctuation(self):
        self.assertEqual(bi.slug("SquareWatch"), bi.slug("squarewatch"))
        self.assertEqual(bi.slug("ESPER machine"), "esper-machine")
        self.assertEqual(bi.slug("  Voigt-Kampff_Empathy-Test "), "voigt-kampff-empathy-test")

    def test_hidden_matches_by_slug(self):
        secs, _ = run([repo("Voigt-Kampff_Empathy-Test"), repo("keep")], cfg=dict(CFG, hidden=["voigt-kampff-empathy-test"]))
        self.assertEqual([e["name"] for k in secs for e in secs[k]], ["keep"])

    def test_no_execute_goes_to_the_bottom_as_repo_only_and_is_never_pinned(self):
        r = repo("Broken-Game", pushed=1, stargazers_count=10)
        secs, rep = run([r], cfg=dict(CFG, no_execute=["broken-game"], pin_limit=5))
        self.assertEqual(secs["pinned"], [])
        self.assertEqual([e["name"] for e in secs["legacy"]], ["Broken-Game"])
        block = bi.render_block(secs)
        self.assertIn("REPO ONLY", block)
        self.assertNotIn("EXECUTE", block)
        self.assertIn("REPOS", block)
        self.assertEqual(rep["repo_only"], ["Broken-Game"])

    def test_hand_written_description_and_title_beat_the_api(self):
        secs, _ = run([repo("Squarewatch", description="api text")],
                      cfg=dict(CFG, pin_limit=0, descriptions={"squarewatch": "Hand written."}, titles={"squarewatch": "SquareWatch"}))
        block = bi.render_block(secs)
        self.assertIn("Hand written.", block)
        self.assertNotIn("api text", block)
        self.assertIn('<div class="name">SquareWatch</div>', block)
        self.assertIn('data-name="squarewatch"', block)

    def test_section_headers_show_node_counts(self):
        secs, _ = run([repo("a"), repo("b")], cfg=dict(CFG, pin_limit=0))
        block = bi.render_block(secs)
        self.assertIn("03 // WHATEVER (2 NODES)", block)
        self.assertIn("01 // PINNED SITES (0 NODES)", block)

    def test_prefer_matches_by_slug(self):
        cold = repo("ButterPass-95", pushed=400, description="")
        secs, _ = run([cold], cfg=dict(CFG, pin_limit=5, pin_min_score=40, pin_prefer=["butterpass-95"]))
        self.assertEqual([e["name"] for e in secs["pinned"]], ["ButterPass-95"])


class Config(unittest.TestCase):
    def test_committed_config_is_valid(self):
        cfg = bi.load_config(ROOT / "config" / "index.json")
        self.assertGreaterEqual(cfg["pin_limit"], 1)
        for x in cfg["extras"]:
            self.assertTrue(bi.safe_url(x["url"]))


if __name__ == "__main__":
    unittest.main()
