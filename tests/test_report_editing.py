import unittest

from app.backend.report_editing import prune_report_by_source


class ReportEditingTests(unittest.TestCase):
    def test_removing_source_prunes_only_items_that_lose_their_last_source(self):
        removed = "https://wrong.example/profile"
        other = "https://right.example/profile"
        content = {
            "overview": "错误概览",
            "overview_source_urls": [removed],
            "identity": ["错误身份", "正确身份"],
            "identity_source_urls": [
                {"text": "错误身份", "source_urls": [removed]},
                {"text": "正确身份", "source_urls": [removed, other]},
            ],
            "biography": [
                {"narrative": "错误生平", "source_urls": [removed]},
                {"narrative": "多源生平", "source_urls": [removed, other]},
                {"narrative": "无关生平", "source_urls": [other]},
            ],
            "accomplishments": [],
            "viewpoint_topics": [{
                "name": "主题",
                "summary": "主题概述",
                "summary_source_urls": [removed],
                "points": [
                    {"statement": "错误观点", "source_urls": [removed]},
                    {"statement": "正确观点", "source_urls": [removed, other]},
                ],
            }],
            "viewpoint_evolution": [],
            "external_views": [],
            "timeline": [{"event": "无关事件", "source_urls": [other]}],
            "images": [
                {"url": "wrong.jpg", "source_url": removed},
                {"url": "right.jpg", "source_url": other},
            ],
            "public_sources": [{"url": removed}, {"url": other}],
            "public_profiles": [{"url": removed}, {"url": other}],
        }

        result, count = prune_report_by_source(content, removed)

        self.assertEqual(result["overview"], "")
        self.assertEqual(result["identity"], ["正确身份"])
        self.assertEqual([item["narrative"] for item in result["biography"]], ["多源生平", "无关生平"])
        self.assertEqual(result["biography"][0]["source_urls"], [other])
        self.assertEqual(result["viewpoint_topics"][0]["summary"], "")
        self.assertEqual(
            [item["statement"] for item in result["viewpoint_topics"][0]["points"]],
            ["正确观点"],
        )
        self.assertEqual(result["timeline"][0]["event"], "无关事件")
        self.assertEqual(result["images"], [{"url": "right.jpg", "source_url": other}])
        self.assertEqual(result["public_sources"], [{"url": other}])
        self.assertGreaterEqual(count, 4)

    def test_legacy_unsourced_summary_is_removed_but_detailed_items_remain(self):
        removed = "https://wrong.example/profile"
        other = "https://right.example/interview"
        result, count = prune_report_by_source({
            "overview": "旧版概览没有保存逐条来源",
            "identity": ["旧版身份摘要"],
            "biography": [{"narrative": "有独立正确来源的生平", "source_urls": [other]}],
            "accomplishments": [],
            "viewpoint_topics": [],
            "viewpoint_evolution": [],
            "external_views": [],
            "timeline": [],
            "images": [],
            "public_sources": [{"url": removed}, {"url": other}],
            "public_profiles": [],
        }, removed)

        self.assertEqual(result["overview"], "")
        self.assertEqual(result["identity"], [])
        self.assertEqual(result["biography"][0]["narrative"], "有独立正确来源的生平")
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
