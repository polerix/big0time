# big0time

*A Big0Time Project*: the LCARS project directory at [big0time.net](https://big0time.net).

## How the catalogue is kept up to date

`.github/workflows/index.yml` runs **every 4 hours** (and on demand from the Actions tab) and rebuilds the
catalogue in `index.html` from GitHub's public data with `scripts/build_index.py` (standard library only).
Nobody edits the cards by hand any more; edit `config/index.json` instead.

| Section | What earns a place |
| --- | --- |
| 01 // PINNED SITES | Working site, recent real work, a description, stars and screenshots. Scored, top 14 |
| 02 // NEWLY CHANGED | Working sites created in the last 30 days (NEW) or with real commits in the last 7 (RECENT) |
| 03 // WHATEVER | Every other repo whose website answers |
| 04 // LEGACY HOLDING GRID | Bottom of the page: non-web repos, dead sites, archived repos, then forks |

Rules the runner follows:
- "Updated" means a real commit. Steward, Dependabot and licence housekeeping commits are ignored.
- Only **public** repos are listed. Private repos never appear (sites of private repos can be listed by URL under `extras`).
- **Empty repos are never listed**; they are reported in the run summary so you can delete or fill them.
- It refuses to write if the result would drop more than half of the existing cards (protects against a partial API answer).
- It only rewrites the block between `<!-- MENU START -->` and `<!-- MENU END -->`.
- The tests run first; a failing test stops the run.

`config/index.json` keys: `pin_lock` (always pinned), `pin_prefer` (small bonus), `pin_exclude`, `hidden` (never listed),
`no_execute` (site known broken: bottom of the page, REPOS only), `descriptions` and `titles` (hand-written text beats
GitHub's), `extras` (sites of private repos, by URL), `pin_limit`, `new_days`, `recent_days`.
Names match case- and punctuation-insensitively.

```bash
python3 scripts/build_index.py --dry-run     # see what would change
python3 -m unittest discover -s tests        # tests
```

`sync_projects.py`, `sync_projects_portable.py` and `sync_cron.sh` are the old local-disk scripts. They are superseded by the runner
(they also copy files into other projects' folders); do not run them together with it.
