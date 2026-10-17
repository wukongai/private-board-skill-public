"""Actual isolated public CLI runs; no LLM/utility claim."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]

class PortableSmoke(unittest.TestCase):
    def test_public_only_recording_and_approved_extension(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            skill = root / "isolated-skill"
            shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("__pycache__"))
            self.assertFalse((skill / "vendor").exists())
            self.assertFalse((skill / "scripts/dependency.py").exists())
            self.assertTrue((skill / "references/business-framework.md").is_file())
            out = root / "case"
            out.mkdir()
            data = dict(round=0, budget=2, status="in_progress", goal="核定近期交付行动",
                summary="等待现金责任确认", decisions=[], actions=[], open_items=["责任未确认"],
                parked=[], event="案主批准2轮预算和保存", backend_notes="合成案例，无外部证据")
            snapshot = out / "input.json"
            meeting, backend = out / "meeting.md", out / "backend.md"
            def run():
                snapshot.write_text(json.dumps(data, ensure_ascii=False))
                return subprocess.run([sys.executable, "-I", "-B", str(skill / "scripts/meeting_record.py"),
                    "--input", str(snapshot), "--meeting", str(meeting), "--backend", str(backend)],
                    cwd=root, env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
                    text=True, capture_output=True)
            first = run()
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(json.loads(first.stdout)["readback_verified"])
            data.update(round=1, budget=4, budget_approval="案主明确同意再加2轮，总4轮，已用1轮不变",
                summary="首步已认领，待执行后取证", decisions=["案主负责现金检查"], open_items=[],
                actions=[dict(owner="案主，有权暂停新增承诺", step="建立本周现金表", when="本周末前",
                    stop="余额低于案主约定底线即暂停新增承诺并复核")], event="责任与停损已确认")
            second = run()
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("1 / 4", meeting.read_text())
            self.assertNotIn("责任未确认", meeting.read_text())
            data.update(round=2, status="closed", summary="已足够行动，提前收束", event="案主确认阶段结果")
            closed = run()
            self.assertEqual(closed.returncode, 0, closed.stderr)
            self.assertIn("讨论已收束", meeting.read_text())
            before = meeting.read_text() + "\n作者新增修订"
            meeting.write_text(before)
            rejected = run()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("外部修改", rejected.stderr)
            self.assertEqual(meeting.read_text(), before)

if __name__ == "__main__":
    unittest.main()
