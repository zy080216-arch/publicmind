import tempfile
import unittest
import zipfile
import re
from pathlib import Path
from unittest.mock import patch

from app.backend.api import create_app
from app.backend.connectors import ConnectorRegistry, SourceConnector
from app.backend.connectors.web import WebConnector
from app.backend.discovery.base import SearchHit
from app.backend.discovery.wikipedia import WikipediaSearchProvider
from app.backend.models import RawDocument

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependencies are not installed")
class ApiTests(unittest.TestCase):
    def test_question_gap_triggers_targeted_search_and_persists_new_source(self):
        search_queries = []

        class FakeSearchProvider:
            name = "fixture-search"

            def search(self, query, count=10):
                search_queries.append(query)
                if "seventeen" in query.casefold() or "site:x.com/paulg" in query.casefold():
                    return [
                        SearchHit(
                            "https://x.com/paulg/status/17",
                            "Paul Graham on what to do at seventeen",
                            "Paul Graham gives direct advice to people who are 17.",
                        )
                    ]
                return [
                    SearchHit(
                        "https://paulgraham.example/about",
                        "Paul Graham official profile",
                        "Paul Graham is an essayist and Y Combinator co-founder.",
                    )
                ]

        class FakeConnector(SourceConnector):
            platform = "fixture"

            def can_handle(self, url):
                return True

            async def fetch(self, url):
                if "/status/17" in url:
                    text = (
                        "Paul Graham wrote that at 17, you should explore widely, "
                        "learn to make things, and avoid optimizing too early for prestige."
                    )
                    title = "What to do at seventeen"
                else:
                    text = "Paul Graham co-founded Y Combinator and writes essays about startups."
                    title = "Paul Graham profile"
                return RawDocument(
                    source_url=url,
                    source_type="article",
                    title=title,
                    author="Paul Graham",
                    published_at="2026-08-30",
                    raw_text=text,
                )

        class FakeLLMProvider:
            name = "fixture-llm"

            def generate_json(self, system, prompt):
                if "用户问题：" in prompt:
                    if "https://x.com/paulg/status/17" in prompt:
                        return {
                            "answer": "他建议 17 岁时广泛探索、学习创造，不要过早追逐声望。",
                            "source_urls": ["https://x.com/paulg/status/17"],
                            "insufficient_knowledge": False,
                            "search_queries": [],
                        }
                    return {
                        "answer": "现有人物库没有收录他对 17 岁年轻人的直接建议。",
                        "source_urls": [],
                        "insufficient_knowledge": True,
                        "search_queries": ["site:x.com/paulg seventeen advice"],
                    }
                return {
                    "title": "Paul Graham 人物全景",
                    "overview": "Paul Graham 是 Y Combinator 联合创始人和随笔作者。",
                    "identity": ["Y Combinator 联合创始人", "随笔作者"],
                    "accomplishments": [],
                    "viewpoint_topics": [],
                    "viewpoint_evolution": [],
                    "timeline": [],
                    "external_views": [],
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                str(root / "publicmind.db"),
                str(root / "exports"),
                search_provider=FakeSearchProvider(),
                llm_provider=FakeLLMProvider(),
                connector_registry=ConnectorRegistry([FakeConnector()]),
            )
            with TestClient(app) as client:
                person = client.post("/api/persons", json={"name": "Paul Graham"}).json()
                started = client.post(
                    "/api/persons/%s/build" % person["id"],
                    json={"anchors": ["Y Combinator"], "language_mode": "zh"},
                ).json()
                job = client.get("/api/build-jobs/%s" % started["id"]).json()
                self.assertEqual(job["status"], "completed")

                answer = client.post(
                    "/api/persons/%s/ask" % person["id"],
                    json={"question": "他认为 17 岁该做什么？"},
                )
                self.assertEqual(answer.status_code, 200)
                payload = answer.json()
                self.assertTrue(payload["research"]["triggered"])
                self.assertEqual(payload["research"]["status"], "expanded")
                self.assertEqual(payload["research"]["new_documents"], 1)
                self.assertIn("广泛探索", payload["answer"])
                self.assertEqual(
                    payload["sources"][0]["url"], "https://x.com/paulg/status/17"
                )
                self.assertTrue(any("site:x.com/paulg" in query for query in search_queries))

                documents = client.get(
                    "/api/persons/%s/documents" % person["id"]
                ).json()
                self.assertEqual(len(documents), 2)
                report = client.get(
                    "/api/persons/%s/report" % person["id"]
                ).json()["content"]
                self.assertTrue(
                    any(
                        source["url"] == "https://x.com/paulg/status/17"
                        for source in report["public_sources"]
                    )
                )

    def test_wikipedia_correction_and_reference_identity_baseline(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        payloads = [
            {"query": {"searchinfo": {"suggestion": "rafa nadal"}, "search": []}},
            {"query": {"searchinfo": {"suggestion": "rafael nadal"}, "search": []}},
            {
                "query": {
                    "searchinfo": {},
                    "search": [
                        {
                            "title": "Rafael Nadal",
                            "snippet": "Spanish former professional tennis player",
                            "timestamp": "2026-08-26T00:00:00Z",
                        }
                    ],
                }
            },
        ]
        with patch(
            "app.backend.discovery.wikipedia.httpx.get",
            side_effect=[FakeResponse(payload) for payload in payloads],
        ):
            hits = WikipediaSearchProvider().search("rafa nadel", count=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].title, "Rafael Nadal — Wikipedia")
        self.assertEqual(hits[0].url, "https://en.wikipedia.org/wiki/Rafael_Nadal")

        class WeakSearchProvider:
            name = "weak-search"

            def search(self, query, count=10):
                return [
                    SearchHit(
                        "https://www.linkedin.com/in/rafa-nadel-example",
                        "Rafa Nadel professional profile",
                        "A similarly named person",
                    )
                ]

        class ReferenceProvider:
            name = "wikipedia"

            def search(self, query, count=10):
                return hits

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                str(root / "publicmind.db"),
                str(root / "exports"),
                search_provider=WeakSearchProvider(),
                reference_provider=ReferenceProvider(),
            )
            with TestClient(app) as client:
                person = client.post("/api/persons", json={"name": "rafa nadel"}).json()
                preview = client.post(
                    "/api/persons/%s/prepare" % person["id"], json={"anchors": []}
                ).json()
                self.assertEqual(preview["primary_source"]["platform"], "Wikipedia")
                self.assertEqual(
                    preview["primary_source"]["url"],
                    "https://en.wikipedia.org/wiki/Rafael_Nadal",
                )

    def test_one_click_build_creates_reader_facing_obsidian_vault(self):
        prompts = []
        class FakeSearchProvider:
            name = "fixture-search"

            def search(self, query, count=10):
                if "official" in query:
                    return [SearchHit("https://alice.example/about", "Alice Chen official", "Alice Chen robotics founder")]
                if "interview" in query:
                    return [SearchHit("https://pod.example/alice", "Interview with Alice Chen", "Alice Chen discusses robotics")]
                return [SearchHit("https://news.example/alice", "Analysis of Alice Chen", "Critical commentary about Alice Chen")]

        class FakeConnector(SourceConnector):
            platform = "fixture"

            def can_handle(self, url):
                return True

            async def fetch(self, url):
                host = url.split("/")[2]
                return RawDocument(
                    source_url=url,
                    source_type="article",
                    title="Source from %s" % host,
                    author="Fixture author",
                    published_at="2026-08-30",
                    raw_text=(
                        "Alice Chen 创办了 Example Robotics，并长期研究具身智能。\n\n"
                        "她在访谈中主张，机器人需要在真实环境中学习。\n\n"
                        "媒体评价认为，这一路线工程价值高，但实验成本也更高。"
                    ),
                    metadata={"platform": host},
                )

        class FakeLLMProvider:
            name = "fixture-llm"

            def generate_json(self, system, prompt):
                prompts.append(prompt)
                if "用户问题：" in prompt:
                    return {
                        "answer": "她认为机器人需要在真实环境中学习。",
                        "source_urls": ["https://pod.example/alice"],
                        "insufficient_knowledge": False,
                    }
                return {
                    "title": "Alice Chen 人物全景",
                    "overview": "Alice Chen 是机器人研究者与创业者。她关注真实环境中的学习。",
                    "identity": ["机器人研究者", "Example Robotics 创办者"],
                    "accomplishments": [{
                        "title": "创办 Example Robotics",
                        "description": "推动具身智能系统走向真实环境。",
                        "period": "2026 年前后",
                        "source_urls": ["https://alice.example/about", "https://invented.example/not-allowed"],
                    }],
                    "viewpoint_topics": [{
                        "name": "真实环境学习",
                        "summary": "她把环境反馈视为机器人学习的重要部分。",
                        "points": [{
                            "statement": "机器人需要在真实环境中学习",
                            "explanation": "这能让系统接触离线数据集没有覆盖的反馈。",
                            "source_urls": ["https://pod.example/alice"],
                        }],
                    }],
                    "viewpoint_evolution": [],
                    "timeline": [{"date": "2026", "event": "持续推进具身智能研究", "source_urls": ["https://alice.example/about"]}],
                    "external_views": [{"summary": "媒体认为其路线工程价值高但成本较高。", "source_urls": ["https://news.example/alice"]}],
                }

        class FakeImageProvider:
            def discover(self, person_name, reference_urls, limit=4):
                return [{
                    "url": "https://upload.wikimedia.org/alice-portrait.jpg",
                    "full_url": "https://upload.wikimedia.org/alice-portrait-original.jpg",
                    "caption": "Alice Chen portrait",
                    "source_url": "https://commons.wikimedia.org/wiki/File:Alice_Chen.jpg",
                    "source_label": "Wikimedia Commons",
                    "author": "Fixture photographer",
                    "license": "CC BY 4.0",
                }]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                str(root / "publicmind.db"),
                str(root / "exports"),
                search_provider=FakeSearchProvider(),
                llm_provider=FakeLLMProvider(),
                image_provider=FakeImageProvider(),
                connector_registry=ConnectorRegistry([FakeConnector()]),
            )
            with TestClient(app) as client:
                person = client.post("/api/persons", json={"name": "Alice Chen"}).json()
                started = client.post(
                    "/api/persons/%s/build" % person["id"],
                    json={"anchors": ["robotics"], "language_mode": "bilingual"},
                )
                self.assertEqual(started.status_code, 200)
                job = client.get("/api/build-jobs/%s" % started.json()["id"]).json()
                self.assertEqual(job["status"], "completed")
                self.assertTrue(job["download_url"])

                report = client.get("/api/persons/%s/report" % person["id"]).json()["content"]
                self.assertEqual(report["language_mode"], "bilingual")
                self.assertEqual(report["translation_scope"], "structured_report_only")
                self.assertIn("先写简体中文", prompts[0])
                self.assertEqual(len(report["images"]), 1)
                self.assertEqual(report["images"][0]["license"], "CC BY 4.0")
                self.assertTrue(report["public_profiles"])
                self.assertEqual(len(report["public_sources"]), 3)
                self.assertEqual(len(report["accomplishments"][0]["source_urls"]), 1)
                self.assertNotIn("invented.example", str(report))

                answer = client.post(
                    "/api/persons/%s/ask" % person["id"],
                    json={"question": "她如何看待机器人学习？"},
                )
                self.assertEqual(answer.status_code, 200)
                self.assertIn("真实环境", answer.json()["answer"])
                self.assertEqual(answer.json()["sources"][0]["url"], "https://pod.example/alice")
                self.assertNotIn("source_urls", answer.json())

                archive = client.get(job["download_url"])
                self.assertEqual(archive.status_code, 200)
                archive_path = root / "vault.zip"
                archive_path.write_bytes(archive.content)
                with zipfile.ZipFile(archive_path) as zf:
                    names = zf.namelist()
                    home_name = next(name for name in names if name.endswith("/00 人物全景.md"))
                    home = zf.read(home_name).decode("utf-8")
                    self.assertTrue(any(name.endswith("/公开信息源.md") for name in names))
                    self.assertTrue(any("/观点/真实环境学习.md" in name for name in names))
                    self.assertTrue(any("/来源/" in name for name in names))
                    self.assertIn("他做过什么", home)
                    self.assertIn("他的核心观点", home)
                    self.assertIn("## 人物影像", home)
                    self.assertIn("![Alice Chen portrait]", home)
                    self.assertIn("https://alice.example/about", home)
                    self.assertLess(home.index("## 公开主页与信息源"), home.index("## 一句话认识"))
                    self.assertNotIn("资料：[[", home)
                    self.assertNotIn("置信度", home)
                    self.assertNotIn("审核", home)
                    self.assertNotIn("claim_type", home)
                    root_prefix = home_name.rsplit("/", 1)[0] + "/"
                    markdown_targets = {
                        name[len(root_prefix) : -3] for name in names
                        if name.startswith(root_prefix) and name.endswith(".md")
                    }
                    for name in names:
                        if not name.startswith(root_prefix) or not name.endswith(".md"):
                            continue
                        text = zf.read(name).decode("utf-8")
                        for match in re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", text):
                            self.assertIn(match, markdown_targets, "%s has broken link %s" % (name, match))

    def test_web_app_flow_without_listening_on_a_socket(self):
        html = b"<html><head><title>API fixture</title></head><body><main><p>Traceable content.</p></main></body></html>"

        def opener(url, timeout):
            return html, {"content-type": "text/html; charset=utf-8"}, url

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(str(root / "publicmind.db"), str(root / "exports"))
            with patch.object(WebConnector, "_open", staticmethod(opener)):
                with TestClient(app) as client:
                    index = client.get("/")
                    self.assertEqual(index.status_code, 200)
                    self.assertIn("PublicMind", index.text)
                    self.assertEqual(client.get("/assets/styles.css").status_code, 200)

                    created = client.post(
                        "/api/persons",
                        json={"name": "API Person", "description": "Fixture archive"},
                    )
                    self.assertEqual(created.status_code, 200)
                    person = created.json()

                    invalid = client.post(
                        "/api/persons/%s/sources" % person["id"],
                        json={"url": "not-a-public-url"},
                    )
                    self.assertEqual(invalid.status_code, 422)

                    added = client.post(
                        "/api/persons/%s/sources" % person["id"],
                        json={"url": "https://example.com/article"},
                    )
                    self.assertEqual(added.status_code, 200)
                    source = added.json()

                    started = client.post("/api/sources/%s/crawl" % source["id"])
                    self.assertEqual(started.status_code, 200)
                    job = client.get("/api/jobs/%s" % started.json()["id"]).json()
                    self.assertEqual(job["status"], "completed")

                    sources = client.get("/api/persons/%s/sources" % person["id"]).json()
                    self.assertEqual(sources[0]["status"], "completed")
                    documents = client.get("/api/persons/%s/documents" % person["id"]).json()
                    self.assertEqual(len(documents), 1)
                    self.assertEqual(documents[0]["title"], "API fixture")

                    archive = client.post("/api/persons/%s/export" % person["id"])
                    self.assertEqual(archive.status_code, 200)
                    self.assertEqual(archive.headers["content-type"], "application/zip")
                    self.assertGreater(len(archive.content), 100)

    def test_discovery_separates_subject_voice_from_external_commentary(self):
        class FakeSearchProvider:
            name = "fixture-search"

            def search(self, query, count=10):
                if "official" in query:
                    return [
                        SearchHit(
                            "https://x.com/alicechen",
                            "Alice Chen (@alicechen)",
                            "Alice Chen robotics researcher at Example Lab",
                        )
                    ]
                if "interview" in query:
                    return [
                        SearchHit(
                            "https://example.org/interview/alice-chen",
                            "Interview with Alice Chen",
                            "Alice Chen discusses robotics and embodied AI",
                        )
                    ]
                return [
                    SearchHit(
                        "https://news.example.com/alice-chen-analysis?utm_source=test",
                        "Analysis: Alice Chen's robotics thesis",
                        "A critical review and commentary on Alice Chen's work",
                    )
                ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                str(root / "publicmind.db"),
                str(root / "exports"),
                search_provider=FakeSearchProvider(),
            )
            with TestClient(app) as client:
                person = client.post(
                    "/api/persons",
                    json={"name": "Alice Chen", "description": "Robotics researcher"},
                ).json()
                prepared = client.post(
                    "/api/persons/%s/prepare" % person["id"],
                    json={"anchors": ["robotics", "Example Lab"]},
                )
                self.assertEqual(prepared.status_code, 200)
                preview = prepared.json()
                self.assertEqual(preview["primary_source"]["platform"], "X")
                self.assertEqual(preview["primary_source"]["url"], "https://x.com/alicechen")
                self.assertTrue(any(item["platform"] == "X" for item in preview["platform_links"]))
                response = client.post(
                    "/api/persons/%s/discover" % person["id"],
                    json={"anchors": ["robotics", "Example Lab"]},
                )
                self.assertEqual(response.status_code, 200)
                candidates = response.json()
                self.assertEqual(len(candidates), 3)

                commentary = next(
                    item for item in candidates if item["source_role"] == "third_party_commentary"
                )
                self.assertNotIn("utm_source", commentary["url"])
                self.assertTrue(any("外部" in reason for reason in commentary["reasons"]))

                accepted = client.post(
                    "/api/candidates/%s/accept" % commentary["id"]
                ).json()
                self.assertEqual(accepted["status"], "accepted")
                sources = client.get(
                    "/api/persons/%s/sources" % person["id"]
                ).json()
                self.assertEqual(sources[0]["source_role"], "third_party_commentary")

                rejected_target = next(
                    item for item in candidates if item["source_role"] == "subject_interview"
                )
                rejected = client.post(
                    "/api/candidates/%s/reject" % rejected_target["id"]
                ).json()
                self.assertEqual(rejected["status"], "rejected")

    def test_claim_candidates_keep_verbatim_evidence_and_require_review(self):
        html = """
        <html><head><title>External analysis</title></head><body><main>
        <p>评论者认为，Alice Chen 的机器人路线重视真实环境中的反馈，而不是只依赖离线数据集。</p>
        <p>文章还指出，这种工程取向可能提高系统可靠性，但也显著增加了实验成本和复现难度。</p>
        </main></body></html>
        """.encode("utf-8")

        def opener(url, timeout):
            return html, {"content-type": "text/html; charset=utf-8"}, url

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(str(root / "publicmind.db"), str(root / "exports"))
            with patch.object(WebConnector, "_open", staticmethod(opener)):
                with TestClient(app) as client:
                    person = client.post("/api/persons", json={"name": "Alice Chen"}).json()
                    source = client.post(
                        "/api/persons/%s/sources" % person["id"],
                        json={
                            "url": "https://example.com/commentary",
                            "source_role": "third_party_commentary",
                        },
                    ).json()
                    started = client.post("/api/sources/%s/crawl" % source["id"])
                    self.assertEqual(started.status_code, 200)

                    claims = client.get("/api/persons/%s/claims" % person["id"]).json()
                    self.assertGreaterEqual(len(claims), 1)
                    claim = claims[0]
                    original_quote = claim["evidence_quote"]
                    self.assertEqual(claim["claim_type"], "external_evaluation")
                    self.assertEqual(claim["speaker"], "外部评论者")
                    self.assertEqual(claim["status"], "pending")
                    self.assertIn("Alice Chen", original_quote)

                    accepted = client.post(
                        "/api/claims/%s/accept" % claim["id"],
                        json={
                            "statement": "该评论认为 Alice Chen 重视真实环境反馈。",
                            "claim_type": "external_evaluation",
                            "speaker": "文章评论者",
                        },
                    )
                    self.assertEqual(accepted.status_code, 200)
                    reviewed = accepted.json()
                    self.assertEqual(reviewed["status"], "accepted")
                    self.assertEqual(reviewed["speaker"], "文章评论者")
                    self.assertEqual(reviewed["evidence_quote"], original_quote)

                    reproposed = client.post(
                        "/api/documents/%s/claims/propose" % claim["document_id"]
                    ).json()
                    self.assertEqual(len(reproposed), len(claims))
                    accepted_again = next(item for item in reproposed if item["id"] == claim["id"])
                    self.assertEqual(accepted_again["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
