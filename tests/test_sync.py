import unittest
from unittest.mock import patch
import sys
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import sync_repos

SAMPLE_HTML = """<!DOCTYPE html>
<html>
<body>
  <div class="container">
    <!-- MENU START -->
      <div class="menu">
        <div class="item">
          <div class="label">
            <div class="name">My Custom App</div>
            <div class="desc">Handcrafted custom description</div>
          </div>
          <div class="actions">
            <a href="https://polerix.github.io/my-custom-app/" target="_blank" rel="noopener noreferrer"><button type="button">OPEN</button></a>
            <a href="https://github.com/polerix/my-custom-app" target="_blank" rel="noopener noreferrer"><button type="button">REPO</button></a>
          </div>
        </div>
      </div>
      <!-- MENU END -->
  </div>
</body>
</html>
"""

class TestSyncRepos(unittest.TestCase):

    def test_html_escaping(self):
        """Test that HTML entities are properly escaped."""
        raw = 'X & Y <tag> "quote"'
        escaped = sync_repos.esc(raw)
        self.assertEqual(escaped, "X &amp; Y &lt;tag&gt; &quot;quote&quot;")

    def test_parse_existing(self):
        """Test parsing existing items from HTML sentinel block."""
        existing = sync_repos.parse_existing(SAMPLE_HTML)
        self.assertIn("my-custom-app", existing)
        self.assertEqual(existing["my-custom-app"]["name"], "My Custom App")
        self.assertEqual(existing["my-custom-app"]["desc"], "Handcrafted custom description")
        self.assertEqual(existing["my-custom-app"]["open_url"], "https://polerix.github.io/my-custom-app/")

    def test_preserved_description(self):
        """Test that custom name and description from existing index are preserved."""
        existing = sync_repos.parse_existing(SAMPLE_HTML)
        repos = [
            {"name": "my-custom-app", "description": "GitHub default description", "pushed_at": "2026-01-01T00:00:00Z"}
        ]
        items = sync_repos.build_repo_items(repos, existing, user="polerix")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "My Custom App")
        self.assertEqual(items[0]["desc"], "Handcrafted custom description")

    def test_sentinel_replacement(self):
        """Test updating the HTML sentinel block correctly."""
        new_items = [
            {
                "name": "New App",
                "desc": "Freshly added app",
                "open_url": "https://polerix.github.io/new-app/",
                "repo_url": "https://github.com/polerix/new-app"
            }
        ]
        new_menu = sync_repos.generate_menu(new_items)
        new_html, changed = sync_repos.update_html(SAMPLE_HTML, new_menu)
        self.assertTrue(changed)
        self.assertIn("New App", new_html)
        self.assertIn("Freshly added app", new_html)
        self.assertIn(sync_repos.SENTINEL_START, new_html)
        self.assertIn(sync_repos.SENTINEL_END, new_html)

    def test_unchanged_output_noop(self):
        """Test that unchanged menu produces changed=False."""
        existing = sync_repos.parse_existing(SAMPLE_HTML)
        repos = [
            {"name": "my-custom-app", "description": "Handcrafted custom description", "pushed_at": "2026-01-01T00:00:00Z"}
        ]
        items = sync_repos.build_repo_items(repos, existing, user="polerix")
        menu = sync_repos.generate_menu(items)
        new_html, changed = sync_repos.update_html(SAMPLE_HTML, menu)
        new_html2, changed2 = sync_repos.update_html(new_html, menu)
        self.assertFalse(changed2)

    @patch("sync_repos.gh_get")
    def test_pagination_mock(self, mock_gh):
        """Test API pagination stops when batch is empty."""
        mock_gh.side_effect = [
            [{"name": "repo1", "pushed_at": "2026-01-01"}],
            [{"name": "repo2", "pushed_at": "2026-01-02"}],
            []
        ]
        repos = sync_repos.discover_repos(user="testuser")
        self.assertEqual(len(repos), 2)
        self.assertEqual(repos[0]["name"], "repo1")
        self.assertEqual(repos[1]["name"], "repo2")
        self.assertEqual(mock_gh.call_count, 3)

if __name__ == "__main__":
    unittest.main()
