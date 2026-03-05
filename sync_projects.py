#!/usr/bin/env python3
"""
Big0Time Project Sync Script

Scans the GitHub projects directory and updates the BIG0TIME index.html with:
- Projects sorted by modification date (newest first)
- Grayed out text for projects without landing pages
- Fire icon (🔥) for recently active projects (modified in last 7 days)
- Copies under-construction.html to projects without landing pages
"""

import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# Configuration
GITHUB_DIR = Path("/Users/polerixsys/Documents/GitHub")
BIG0TIME_DIR = GITHUB_DIR / "BIG0TIME"
UNDER_CONSTRUCTION = BIG0TIME_DIR / "under-construction.html"
INDEX_HTML = BIG0TIME_DIR / "index.html"
RECENT_DAYS = 7  # Projects modified within this many days get fire icon

# Landing page patterns to check (in order of preference)
LANDING_PAGES = [
    "index.html",
    "index.htm",
    "README.html",
    "main.html",
    "app.html",
]


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
    for landing in LANDING_PAGES:
        if (project_dir / landing).exists():
            return True
    return False


def copy_under_construction(project_name: str) -> str:
    """Copy under-construction.html to a project directory"""
    project_dir = GITHUB_DIR / project_name
    dest = project_dir / "under-construction.html"

    if not dest.exists():
        shutil.copy2(UNDER_CONSTRUCTION, dest)
        print(f"  Copied under-construction.html to {project_name}")

    return "under-construction.html"


def generate_project_html(project_name: str, project_dir: Path) -> str:
    """Generate HTML for a single project entry"""

    has_landing = has_landing_page(project_dir)
    is_recent = is_recently_modified(project_dir)
    description = get_project_description(project_dir)

    # Determine the open URL
    if has_landing:
        open_url = get_deployed_url(project_name)
    else:
        # Copy under-construction and link to it
        copy_under_construction(project_name)
        open_url = f"https://polerix.github.io/{project_name}/under-construction.html"

    github_url = get_github_url(project_name)

    # Generate the HTML
    fire_icon = "🔥 " if is_recent else ""
    gray_style = 'style="opacity: 0.5;"' if not has_landing else ""
    name_class = 'class="name"' if has_landing else 'class="name muted"'

    html = f'''        <div class="item">
          <div class="label">
            <div {name_class}>{fire_icon}{project_name}</div>
            <div class="desc">{description}</div>
          </div>
          <div class="actions">
            <a href="{open_url}" target="_blank" rel="noopener noreferrer"><button type="button">OPEN</button></a>
            <a href="{github_url}" target="_blank" rel="noopener noreferrer"><button type="button">REPO</button></a>
          </div>
        </div>'''

    return html


def get_all_projects() -> list[tuple[Path, datetime]]:
    """Get all project directories sorted by modification date"""
    projects = []

    for item in GITHUB_DIR.iterdir():
        if not item.is_dir():
            continue
        # Skip hidden directories and special dirs
        if item.name.startswith('.') or item.name.startswith('clawd'):
            continue
        # Skip BIG0TIME itself
        if item.name == "BIG0TIME":
            continue

        mod_date = get_project_modification_date(item)
        projects.append((item, mod_date))

    # Sort by modification date (newest first)
    projects.sort(key=lambda x: x[1], reverse=True)

    return projects


def update_index_html():
    """Update the index.html with current project list"""

    print("Scanning projects...")
    projects = get_all_projects()

    print(f"Found {len(projects)} projects")

    # Generate project HTML entries
    project_entries = []
    for project_dir, mod_date in projects:
        project_name = project_dir.name
        print(f"  {project_name}: {mod_date.strftime('%Y-%m-%d')}", end="")

        has_landing = has_landing_page(project_dir)
        is_recent = is_recently_modified(project_dir)

        if not has_landing:
            print(" [no landing]", end="")
        if is_recent:
            print(" [recent]", end="")

        print()

        html = generate_project_html(project_name, project_dir)
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

    # Build new template
    new_template = (
        template[:start_idx + len(menu_start)] +
        '\n' +
        '\n'.join(project_entries) +
        '\n' +
        template[end_idx:]
    )

    # Update the index
    INDEX_HTML.write_text(new_template, encoding='utf-8')

    print(f"\nUpdated {INDEX_HTML}")


def main():
    """Main entry point"""
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

    update_index_html()

    print("\nSync complete!")


if __name__ == "__main__":
    main()
