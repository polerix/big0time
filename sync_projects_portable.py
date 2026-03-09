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

    return html


def get_all_projects() -> tuple[list[tuple[Path, datetime]], list[tuple[Path, datetime]]]:
    """Get all project directories, separating pinned projects"""
    pinned_projects = []
    other_projects = []

    for item in GITHUB_DIR.iterdir():
        if not item.is_dir():
            continue
        # Skip hidden directories and special dirs
        if item.name.startswith('.') or item.name.startswith('clawd') or item.name == 'BIG0TIME_broken':
            continue
        # Skip BIG0TIME itself
        if item.name == "BIG0TIME":
            continue

        mod_date = get_project_modification_date(item)
        if item.name in PINNED_PROJECTS:
            pinned_projects.append((item, mod_date))
        else:
            other_projects.append((item, mod_date))

    # Sort other projects by modification date (newest first)
    other_projects.sort(key=lambda x: x[1], reverse=True)
    
    # Sort pinned projects by the order in PINNED_PROJECTS
    pinned_projects.sort(key=lambda x: PINNED_PROJECTS.index(x[0].name))

    return pinned_projects, other_projects


def update_index_html(force_screenshot: bool = False):
    """Update the index.html with current project list"""
    print("Scanning projects...")
    pinned_projects, other_projects = get_all_projects()
    print(f"Found {len(pinned_projects)} pinned projects and {len(other_projects)} other projects.")
    # Create screenshot directory if it doesn't exist
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    # Generate project HTML entries
    project_entries = []
    if pinned_projects:
        project_entries.append('      <h2 class="grid-title">Pinned Projects</h2>')
        for project_dir, mod_date in pinned_projects:
            project_name = project_dir.name
            print(f"  (Pinned) {project_name}: {mod_date.strftime('%Y-%m-%d')}", end="")
            html = generate_project_html(project_name, project_dir, pinned=True, force_screenshot=force_screenshot)
            project_entries.append(html)
            print()
    if other_projects:
        project_entries.append('      <h2 class="grid-title">All Projects</h2>')
        for project_dir, mod_date in other_projects:
            project_name = project_dir.name
            print(f"  {project_name}: {mod_date.strftime('%Y-%m-%d')}", end="")
            has_landing = has_landing_page(project_dir)
            is_recent = is_recently_modified(project_dir)
            if not has_landing:
                print(" [no landing]", end="")
            if is_recent:
                print(" [recent]", end="")
            print()
            html = generate_project_html(project_name, project_dir, force_screenshot=force_screenshot)
            project_entries.append(html)
    # Read the template
    template = INDEX_HTML.read_text(encoding='utf-8')
    # Find the menu start and end markers
    menu_start = '<!-- MENU START -->'
    menu_end = '<!-- MENU END -->'
    start_idx = template.find(menu_start)
    end_idx = template.find(menu_end)
    if start_idx == -1 or end_idx == -1:
        print("ERROR: Could not find menu markers in index.html")
        return
    # Build new template (bubble grid style)
    new_template = (
        template[:start_idx + len(menu_start)] +
        '\n    <div class="grid">' +
        '\n'.join(project_entries) +
        '\n    </div>' +
        template[end_idx:]
    )
    # Update the index
    INDEX_HTML.write_text(new_template, encoding='utf-8')
    print(f"\nUpdated {INDEX_HTML}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Big0Time Project Sync Script")
    parser.add_argument("--force-screenshot", action="store_true", help="Force new screenshots to be captured, even if recent.")
    args = parser.parse_args()

    print("=" * 50)
    print("Big0Time Project Sync")
    print("=" * 50)

    # Verify paths exist
    if not GITHUB_DIR.exists():
        print(f"ERROR: GitHub directory not found: {GITHUB_DIR}")
        return

    if not BIG0TIME_DIR.exists():
        print(f"ERROR: BIG0TIME directory not found: {BIG0TIME_DIR}")
        return

    if not UNDER_CONSTRUCTION.exists():
        print(f"ERROR: under-construction.html not found: {UNDER_CONSTRUCTION}")
        return

    update_index_html(force_screenshot=args.force_screenshot)

    print("\nSync complete!")


if __name__ == "__main__":
    main()
