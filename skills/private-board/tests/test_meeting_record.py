import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "meeting_record.py"

class MeetingRecordTests(unittest.TestCase):
    def test_writer_exists(self):
        self.assertTrue(SCRIPT.is_file(), "缺少结构化会议记录器，旧当前摘要无法由写入边界保证")

    def setUp(self):
        if not SCRIPT.exists() and self._testMethodName != "test_writer_exists":
            self.skipTest("记录器尚未实现")
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location("meeting_record", SCRIPT)
            self.writer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.writer)

    def sample(self, **updates):
        data = dict(round=0, budget=4, status="in_progress", goal="选择近期经营行动",
                    summary="先核现金", decisions=[], actions=[], open_items=["现金责任待确认"],
                    parked=[], event="开场", backend_notes="INV-14 仅后台")
        data.update(updates)
        return data

    def test_current_replaced_history_separated_and_readback(self):
        with tempfile.TemporaryDirectory() as d:
            m, b = Path(d)/"meeting.md", Path(d)/"host-record.md"
            self.writer.save(self.sample(), m, b)
            self.writer.save(self.sample(round=1, summary="现金动作已确认",
                decisions=["案主负责现金"], open_items=[], event="认领现金责任",
                actions=[dict(owner="案主", step="本周建现金表", when="本周",
                              stop="预测触线即停新增")]), m, b)
            front = m.read_text()
            self.assertIn("1 / 4", front)
            self.assertNotIn("现金责任待确认", front)
            self.assertNotIn("INV-14", front)
            back = b.read_text()
            self.assertIn("历史事件", back)
            self.assertIn("INV-14", back)
            self.assertTrue(list((Path(d)/".meeting-history").glob("*")))
            state = json.loads((Path(d)/".meeting.record.json").read_text())
            self.assertEqual(state["current"]["round"], 1)
            self.assertEqual(len(state["history"]), 1)
            self.assertEqual(state["current"]["open_items"], [])

    def test_external_edit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            m, b = Path(d)/"meeting.md", Path(d)/"host-record.md"
            self.writer.save(self.sample(), m, b)
            m.write_text(m.read_text()+"\n案主手工修改")
            with self.assertRaises(ValueError):
                self.writer.save(self.sample(round=1), m, b)
            self.assertIn("案主手工修改", m.read_text())

    def test_invalid_state_and_internal_id_never_written(self):
        with tempfile.TemporaryDirectory() as d:
            m, b = Path(d)/"meeting.md", Path(d)/"host-record.md"
            for data in [self.sample(round=5), self.sample(summary="参考 INV-14"),
                         self.sample(actions=[dict(owner="案主")])]:
                with self.assertRaises(ValueError):
                    self.writer.save(data, m, b)
                self.assertFalse(m.exists())

    def test_extension_requires_recorded_approval_and_keeps_count(self):
        with tempfile.TemporaryDirectory() as d:
            m, b = Path(d)/"meeting.md", Path(d)/"host-record.md"
            self.writer.save(self.sample(round=2), m, b)
            with self.assertRaises(ValueError):
                self.writer.save(self.sample(round=2, budget=6), m, b)
            self.writer.save(self.sample(round=2, budget=6,
                budget_approval="案主明确同意增加2答，总6，已用2不变"), m, b)
            self.assertIn("2 / 6", m.read_text())
            with self.assertRaises(ValueError):
                self.writer.save(self.sample(round=0, budget=6), m, b)

    def test_partial_write_failure_restores_then_can_retry(self):
        with tempfile.TemporaryDirectory() as d:
            m, b = Path(d)/"meeting.md", Path(d)/"host-record.md"
            self.writer.save(self.sample(), m, b)
            before = (m.read_bytes(), b.read_bytes())
            real_replace = self.writer.os.replace
            calls = []
            def fail_second(src, dest):
                calls.append(str(dest))
                if len(calls) == 2:
                    raise OSError("模拟第二文件写入失败")
                return real_replace(src, dest)
            with patch.object(self.writer.os, "replace", side_effect=fail_second):
                with self.assertRaises(OSError):
                    self.writer.save(self.sample(round=1), m, b)
            self.assertEqual(before, (m.read_bytes(), b.read_bytes()))
            self.writer.save(self.sample(round=1), m, b)
            self.assertIn("1 / 4", m.read_text())

    def test_edit_during_render_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            m, b = Path(d)/"meeting.md", Path(d)/"host-record.md"
            self.writer.save(self.sample(), m, b)
            render = self.writer.render_front
            def edit_then_render(data, events):
                m.write_text(m.read_text()+"\n外部作者新修改")
                return render(data, events)
            with patch.object(self.writer, "render_front", side_effect=edit_then_render):
                with self.assertRaises(ValueError):
                    self.writer.save(self.sample(round=1), m, b)
            self.assertIn("外部作者新修改", m.read_text())

    def test_active_writer_lock_is_respected(self):
        with tempfile.TemporaryDirectory() as d:
            m, b = Path(d)/"meeting.md", Path(d)/"host-record.md"
            (Path(d)/".meeting.write-lock").mkdir()
            with self.assertRaises(ValueError):
                self.writer.save(self.sample(), m, b)
            self.assertFalse(m.exists())

if __name__ == "__main__":
    unittest.main()
