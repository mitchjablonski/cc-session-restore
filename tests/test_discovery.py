import os
import unittest
from unittest.mock import patch

from fixtures import Fixture, load_app

DAY = 86400
NOW = 1800000000


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.app = load_app()
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        for name, value in (("PROJECTS", self.fx.config / "projects"),
                            ("REGISTRY", self.fx.registry), ("TEMP_DIRS", set())):
            p = patch.object(self.app, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("boot_time", NOW), ("is_alive", False)):
            p = patch.object(self.app, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_title_priority(self):
        custom = {"type": "custom-title", "customTitle": "Custom"}
        ai = [{"type": "ai-title", "aiTitle": "Earlier AI"},
              {"type": "ai-title", "aiTitle": "Latest AI"}]
        cases = [("user", [custom] + ai, "User", "user", "User"),
                 ("custom", [custom] + ai, "Derived", "auto", "Custom"),
                 ("ai", ai, "Derived", "auto", "Latest AI"),
                 ("derived", [], "Derived", "auto", "Derived"),
                 ("folder", [], None, None, self.fx.cwd.name)]
        for sid, lines, name, source, expected in cases:
            self.fx.transcript(sid, NOW, lines)
            if name:
                self.fx.session(sid, NOW, name=name, nameSource=source)
        found = {s["id"]: s["title"] for s in self.app.recent_sessions()}
        self.assertEqual(found, {row[0]: row[-1] for row in cases})

    def test_noninteractive_and_missing_folders_skipped(self):
        self.fx.transcript("sdk", NOW, entrypoint="sdk")
        self.fx.transcript("background", NOW, entrypoint="background")
        self.fx.transcript("missing", NOW, cwd=self.fx.root / "absent")
        self.fx.transcript("temporary", NOW)
        self.assertEqual([s["id"] for s in self.app.recent_sessions()], ["temporary"])
        with patch.object(self.app, "TEMP_DIRS", {os.path.normcase(str(self.fx.cwd))}):
            self.assertEqual(self.app.recent_sessions(), [])

    def test_registry_background_not_prechecked_and_running_wins(self):
        self.fx.transcript("background", NOW)
        self.fx.session("background", NOW, kind="background")
        self.fx.transcript("running", NOW)
        self.fx.session("running", NOW)
        with patch.object(self.app, "is_alive", side_effect=lambda d: d["sessionId"] == "running"):
            sessions = {s["id"]: s for s in self.app.recent_sessions()}
        self.assertFalse(sessions["background"]["was_open"])
        self.assertTrue(sessions["running"]["running"])
        self.assertEqual(self.app.precheck(list(sessions.values())), set())

    def test_transcript_reuse_one_hour_boundary(self):
        self.fx.session("boundary", NOW)
        self.fx.transcript("boundary", NOW + 3600)
        self.fx.session("reused", NOW)
        self.fx.transcript("reused", NOW + 3601)
        found = {s["id"]: s for s in self.app.recent_sessions()}
        self.assertTrue(found["boundary"]["was_open"])
        self.assertFalse(found["reused"]["was_open"])

    def test_precheck_seven_day_boundary(self):
        rows = [self.row("new", NOW), self.row("edge", NOW - 7 * DAY),
                self.row("old", NOW - 7 * DAY - 1)]
        self.assertEqual(self.app.precheck(rows), {"new", "edge"})

    def test_precheck_fourteen_day_boundary(self):
        rows = [self.row("new", NOW - 10 * DAY), self.row("edge", NOW - 14 * DAY),
                self.row("old", NOW - 14 * DAY - 1)]
        self.assertEqual(self.app.precheck(rows), {"new", "edge"})

    def test_limit_keeps_running_and_prechecked_beyond_count(self):
        rows = [self.row("first", NOW), self.row("second", NOW),
                self.row("keep", NOW), self.row("running", NOW, running=True)]
        self.assertEqual([s["id"] for s in self.app.limit(rows, 1, {"keep"})],
                         ["first", "keep", "running"])
        self.assertEqual(len(self.app.limit(rows, 0, {"keep"})), 2)

    def test_malformed_registry_and_transcript_lines(self):
        (self.fx.registry / "broken.json").write_text("{", encoding="utf-8")
        (self.fx.registry / "array.json").write_text("[]", encoding="utf-8")
        path = self.fx.transcript("valid", NOW, [{"type": "ai-title", "aiTitle": "Good"}])
        with path.open("a", encoding="utf-8") as stream:
            stream.write('{"cwd":broken\n["cwd"]\n{"type":"ai-title",\n')
        self.assertEqual([(s["id"], s["title"]) for s in self.app.recent_sessions()],
                         [("valid", "Good")])

    def test_malformed_or_no_cwd_transcripts_are_skipped(self):
        (self.fx.projects / "broken.jsonl").write_text(
            '{"cwd":broken\n["cwd"]\n{"type":"ai-title",\n', encoding="utf-8")
        (self.fx.projects / "no-cwd.jsonl").write_text(
            '{"type":"ai-title","aiTitle":"No working directory"}\n', encoding="utf-8")
        self.assertEqual(self.app.recent_sessions(), [])

    @staticmethod
    def row(sid, seen, running=False):
        return {"id": sid, "seen": seen, "was_open": True, "running": running}


if __name__ == "__main__":
    unittest.main()
