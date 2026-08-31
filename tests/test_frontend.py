import unittest
from pathlib import Path


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.frontend = Path(__file__).resolve().parents[1] / "app" / "frontend"

    def test_interface_assets_are_present_and_connected(self):
        html = (self.frontend / "index.html").read_text(encoding="utf-8")
        css = (self.frontend / "styles.css").read_text(encoding="utf-8")
        javascript = (self.frontend / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="search-form"', html)
        self.assertIn('id="language-mode"', html)
        self.assertIn('id="identity-panel"', html)
        self.assertIn('id="identity-confirm"', html)
        self.assertIn('id="manual-source-form"', html)
        self.assertIn('id="settings-dialog"', html)
        self.assertIn('id="brave-key"', html)
        self.assertIn('id="deepseek-key"', html)
        self.assertIn('id="progress-panel"', html)
        self.assertIn('id="result-profiles"', html)
        self.assertIn('id="portrait-section"', html)
        self.assertIn('id="result-images"', html)
        self.assertIn('id="result-accomplishments"', html)
        self.assertIn('id="result-viewpoints"', html)
        self.assertIn('id="ask-form"', html)
        self.assertIn('id="ask-question"', html)
        self.assertIn('id="ask-answer"', html)
        self.assertIn('id="ask-status"', html)
        self.assertIn('id="ask-answer-meta"', html)
        self.assertIn("必要时自动补充检索", html)
        self.assertIn('id="download-link"', html)
        self.assertIn('href="#search-form"', html)
        self.assertIn('href="#recent-title"', html)
        self.assertIn('href="#source-section"', html)
        self.assertIn('href="#viewpoints-section"', html)
        self.assertIn('href="#ask-section"', html)
        self.assertIn('API 设置', html)
        self.assertIn('Brave Search 负责检索，DeepSeek 负责整理和问询', html)
        self.assertIn('Obsidian 知识库包（Markdown）', html)
        self.assertNotIn('class="search-options"', html)
        self.assertNotIn('<details class="manual-source-block"', html)
        self.assertIn("/assets/styles.css", html)
        self.assertIn("/assets/app.js", html)
        self.assertIn("/assets/favicon.svg", html)
        self.assertIn("@media (max-width: 560px)", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn('request("/api/config")', javascript)
        self.assertIn('request("/api/persons")', javascript)
        self.assertIn("/prepare`,", javascript)
        self.assertIn("/build`,", javascript)
        self.assertIn("/api/build-jobs/", javascript)
        self.assertIn("/report", javascript)
        self.assertIn("/images/refresh", javascript)
        self.assertIn("/ask`,", javascript)
        self.assertIn("/export", javascript)


if __name__ == "__main__":
    unittest.main()
