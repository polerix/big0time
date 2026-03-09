#!/usr/bin/env python3
"""
Big0Time Project Sync Script

Scans the GitHub projects directory and updates the BIG0TIME index.html with:
- Pinned projects at the top
- Projects sorted by modification date (newest first)
- Grayed out text for projects without landing pages
- Fire icon (🔥) for recently active projects (modified in last 7 days)
- Copies under-construction.html to projects without landing pages
- Captures screenshots for pinned projects and uses them as blurred backgrounds
"""

import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# Configuration
SCRIPT_DIR = Path(__file__).resolve().parent
BIG0TIME_DIR = SCRIPT_DIR
GITHUB_DIR = BIG0TIME_DIR.parent
UNDER_CONSTRUCTION = BIG0TIME_DIR / "under-construction.html"
INDEX_HTML = BIG0TIME_DIR / "index.html"
SCREENSHOT_DIR = BIG0TIME_DIR / "resources" / "screenshots"
RECENT_DAYS = 7  # Projects modified within this many days get fire icon
SCREENSHOT_EXPIRY_SECONDS = 24 * 60 * 60  # Screenshots expire after 24 hours

# Pinned projects
PINNED_PROJECTS = [
    "SecurityAdventure",
    "VAX_Console_Sim",
    "KraemerverseWiki",
    "TornadoCones",
    "satans_spreadsheet",
    "HackersTeam",
    "sandrineportfolio",
]

# Custom URLs for specific projects
CUSTOM_URLS = {
    "HackersTeam": "https://polerix.github.io/HackersTeam/frontend/",
    "sandrineportfolio": "https://polerix.github.io/sandrineportfolio/",
}

# Landing page patterns to check (in order of preference)
LANDING_PAGES = [
    "index.html",
    "index.htm",
    "README.html",
    "main.html",
    "app.html",
]


def capture_screenshot(url: str, output_path: Path, force: bool = False):
    """Capture a website screenshot using headless Chrome, with expiry and force options"""
    if not url:
        return

    if output_path.exists() and not force:
        # Check if screenshot is expired
        modified_time = datetime.fromtimestamp(output_path.stat().st_mtime)
        if (datetime.now() - modified_time).total_seconds() < SCREENSHOT_EXPIRY_SECONDS:
            print(f"    Skipping screenshot for {url} (fresh enough).")
            return

    print(f"    Capturing screenshot of {url}...")
    try:
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not Path(chrome_path).exists():
            print("    Google Chrome not found, skipping screenshot.")
            return

        subprocess.run(
            [
                chrome_path,
                "--headless",
                f"--screenshot={output_path}",
                "--window-size=1280,800",
                url,
            ],
            timeout=120,
            capture_output=True,
        )
        print(f"    Screenshot saved to {output_path}")
    except Exception as e:
        print(f"    Failed to capture screenshot for {url}: {e}")


def get_project_description(project_dir: Path) -> str:
    """Extract project description from README.md or package.json"""
    readme = project_dir / "README.md"
    if readme.exists():
        try:
            content = readme.read_text(encoding='utf-8', errors='ignore')
            lines = content.strip().split('\n')
            # Skip title line (# prefix) and get first non-empty line
            for line in lines[1:]:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Clean up the description
                    desc = line.strip().lstrip('- ').lstrip('* ')
                    if len(desc) > 60:
                        desc = desc[:57] + "..."
                    return desc
        except Exception:
            pass

    # Try package.json
    pkg_json = project_dir / "package.json"
    if pkg_json.exists():
        try:
            import json
            pkg = json.loads(pkg_json.read_text(encoding='utf-8', errors='ignore'))
            desc = pkg.get("description", "")
            if desc and len(desc) > 60:
                desc = desc[:57] + "..."
            return desc
        except Exception:
            pass

    return ""


def get_github_url(project_name: str) -> str:
    """Generate GitHub URL from project name"""
    return f"https://github.com/polerix/{project_name}"


def get_deployed_url(project_name: str) -> str | None:
    """Generate GitHub Pages URL if deployed, None otherwise"""
    if project_name in CUSTOM_URLS:
        return CUSTOM_URLS[project_name]

    # Common patterns for GitHub Pages
    base_url = f"https://polerix.github.io/{project_name}"

    project_dir = GITHUB_DIR / project_name

    # Check if any of the landing pages exist
    for landing in LANDING_PAGES:
        landing_path = project_dir / landing
        if landing_path.exists():
            if landing == "index.html" or landing == "index.htm":
                return base_url + "/"
            return f"{base_url}/{landing}"

    return None


def get_project_modification_date(project_dir: Path) -> datetime:
    """Get the most recent modification date of any file in the project"""
    latest_date = datetime(1970, 1, 1)

    # Check .git for commit dates
    git_dir = project_dir / ".git"
    if git_dir.exists():
        try:
            # Get most recent commit date
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                timestamp = int(result.stdout.strip())
                commit_date = datetime.fromtimestamp(timestamp)
                latest_date = max(latest_date, commit_date)
        except Exception:
            pass

    # Also check file modification times as fallback
    try:
        for item in project_dir.rglob("*"):
            if item.is_file() and not item.name.startswith('.'):
                # Skip large files
                if item.stat().st_size > 10_000_000:
                    continue
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                latest_date = max(latest_date, mtime)
    except Exception:
        pass

    return latest_date


def is_recently_modified(project_dir: Path) -> bool:
    """Check if project was modified in the last RECENT_DAYS days"""
    mod_date = get_project_modification_date(project_dir)
    return datetime.now() - mod_date < timedelta(days=RECENT_DAYS)


def has_landing_page(project_dir: Path) -> bool:
    """Check if project has a landing page"""
    if project_dir.name in CUSTOM_URLS:
        return True
    for landing in LANDING_PAGES:
        if (project_dir / landing).exists():
            return True
    return False


def copy_under_construction(project_name: str) -> str:
    """Copy under-construction.html to a project directory"""
    project_dir = GITHUB_DIR / project_name
    dest = project_dir / "under-construction.html"

    if not dest.exists():
        os.makedirs(project_dir, exist_ok=True) # Ensure the project directory exists
        shutil.copy2(UNDER_CONSTRUCTION, dest)
        print(f"  Copied under-construction.html to {project_name}")

    return "under-construction.html"


def generate_project_html(project_name: str, project_dir: Path, pinned: bool = False, force_screenshot: bool = False) -> str:
    """Generate HTML for a single project entry"""

    has_landing = has_landing_page(project_dir)
    is_recent = is_recently_modified(project_dir)
    description = get_project_description(project_dir)

    # Strip HTML tags from description for clean display
    import re
    description = re.sub(r'<[^>]+>', '', description)
    # Clean up common artifacts
    description = description.replace('**', '').replace('\\u', '').strip()
    if len(description) > 80:
        description = description[:77] + '...'

    # Determine the open URL
    if has_landing:
        open_url = get_deployed_url(project_name)
    else:
        # Copy under-construction and link to it
        copy_under_construction(project_name)
        open_url = f"https://polerix.github.io/{project_name}/under-construction.html"

    github_url = get_github_url(project_name)
    
    style = ""
    if pinned:
        screenshot_path = SCREENSHOT_DIR / f"{project_name}.png"
        capture_screenshot(open_url, screenshot_path, force=force_screenshot)
        if screenshot_path.exists():
            style = f'style="--bg-image: url(resources/screenshots/{project_name}.png);"'


    # Generate the HTML (bubble style)
    fire_icon = "🔥 " if is_recent else ""
    muted_class = " muted" if not has_landing else ""
    pinned_class = " pinned" if pinned else ""

    html = f'''      <div class="bubble{muted_class}{pinned_class}" data-name="{project_name}" {style}>
        <div class="inner-glow" style="z-index: 1;"></div>
        <div class="name" style="z-index: 2;">{fire_icon}{project_name}</div>
        <div class="desc" style="z-index: 2;">{description}</div>
        <div class="actions" style="z-index: 2;">
          <a href="{open_url}" target="_blank" rel="noopener noreferrer"><button>Open</button></a>
          <a href="{github_url}" target="_blank" rel="noopener noreferrer"><button>Repo</button></a>
        </div>
      </div>'''
