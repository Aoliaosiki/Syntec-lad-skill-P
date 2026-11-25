from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from syntec_lad.cloud import (
    OFFLINE_NOTE,
    cloud_status,
    compare_with_ladder,
    parse_snapshot,
    render_cloud_status,
    scan_snapshots,
)

SNAPSHOT = """# 潤滑規格

| 項 | 值 |
|---|---|
| page id | `123456789` |
| version | `6` |
| lastModified | 2026-11-22T16:34:22.676Z |
| 拉取 | `getConfluenceContent` markdown / full |

## 點位

- 打油輸出 O50
- 液位檢測 I30
- 打油時長 R81
- 累計次數 R200
"""


class CloudStatusTests(unittest.TestCase):
    def test_parse_snapshot_reads_header_and_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "123456789.md"
            path.write_text(SNAPSHOT, encoding="utf-8")
            parsed = parse_snapshot(path)
        self.assertEqual(parsed["page_id"], "123456789")
        self.assertEqual(parsed["version"], "6")
        self.assertEqual(parsed["last_modified"], "2026-11-22T16:34:22.676Z")
        self.assertIn("O50", parsed["addresses"])
        self.assertIn("R81", parsed["registers"])
        self.assertIn("R200", parsed["registers"])

    def test_scan_skips_readme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "1.md").write_text(SNAPSHOT, encoding="utf-8")
            (root / "README.md").write_text("# index", encoding="utf-8")
            self.assertEqual(len(scan_snapshots(root)), 1)

    def test_offline_status_says_no_cloud_verification(self) -> None:
        status = cloud_status([])
        self.assertEqual(status["level"], "L1")
        self.assertFalse(status["online"])
        self.assertEqual(status["note"], OFFLINE_NOTE)
        self.assertIn("未联网云端验证", render_cloud_status(status))

    def test_snapshot_only_is_l1_plus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "123456789.md"
            path.write_text(SNAPSHOT, encoding="utf-8")
            status = cloud_status(scan_snapshots(tmp))
        self.assertEqual(status["level"], "L1+")
        self.assertEqual(status["snapshots"][0]["page_id"], "123456789")

    def test_online_flag_is_explicit(self) -> None:
        status = cloud_status([], online=True)
        self.assertEqual(status["level"], "L2")
        self.assertTrue(status["online"])

    def test_compare_reports_documented_but_unused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "123456789.md"
            path.write_text(SNAPSHOT, encoding="utf-8")
            snapshots = scan_snapshots(tmp)
        findings = compare_with_ladder(
            {"O50"},
            {"R81"},
            snapshots,
        )
        self.assertEqual(len(findings), 1)
        addresses = findings[0]["addresses"]
        self.assertIn("I30", addresses)
        self.assertNotIn("O50", addresses)
        self.assertNotIn("R81", addresses)


if __name__ == "__main__":
    unittest.main()
