from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


RUNTIME_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "s14-operation-diagnosis"
    / "runtime"
)
sys.path.insert(0, str(RUNTIME_DIR))

import feishu_adapter  # noqa: E402
import router  # noqa: E402
import source_flow  # noqa: E402


class S14SourceSelectionFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_state_file = source_flow.STATE_FILE
        source_flow.STATE_FILE = Path(self.temp_dir.name) / "state.json"

    def tearDown(self) -> None:
        source_flow.STATE_FILE = self.old_state_file
        self.temp_dir.cleanup()

    def test_trigger_asks_only_for_database_or_excel(self) -> None:
        card = feishu_adapter.handle_feishu_text_message_card(
            "@机器人 S14诊断",
            chat_id="chat-1",
            sender_id="user-1",
        )
        self.assertEqual(card["msg_type"], "interactive")
        actions = card["card"]["elements"][1]["actions"]
        labels = [action["text"]["content"] for action in actions]
        self.assertEqual(labels, ["数据库", "上传Excel"])
        text = str(card)
        self.assertNotIn("携程 / 美团", text)
        self.assertEqual(
            source_flow.get_state(chat_id="chat-1", sender_id="user-1")["state"],
            "awaiting_source",
        )

    def test_excel_choice_waits_for_same_user_attachment(self) -> None:
        feishu_adapter.handle_feishu_text_message_card(
            "S14诊断",
            chat_id="chat-1",
            sender_id="user-1",
        )
        wait_card = feishu_adapter.handle_source_choice_card(
            "excel",
            chat_id="chat-1",
            sender_id="user-1",
        )
        self.assertIn("无需再次@机器人", str(wait_card))
        self.assertTrue(
            source_flow.is_waiting_excel(chat_id="chat-1", sender_id="user-1")
        )
        self.assertFalse(
            source_flow.is_waiting_excel(chat_id="chat-1", sender_id="user-2")
        )

    def test_database_choice_runs_current_unified_report(self) -> None:
        result = {
            "hotel_name": "璞悦",
            "period_start": "2026-06-16",
            "period_end": "2026-07-15",
            "report_url": "http://example.test/report.html",
            "visual_diagnosis": {"normalized_score": 78.0},
        }
        feishu_adapter.handle_feishu_text_message_card(
            "S14诊断",
            chat_id="chat-1",
            sender_id="user-1",
        )
        with patch.object(feishu_adapter, "_run_current_report", return_value=result) as runner:
            card = feishu_adapter.handle_source_choice_card(
                "database",
                chat_id="chat-1",
                sender_id="user-1",
            )
        runner.assert_called_once_with("database")
        content = card["card"]["elements"][0]["text"]["content"]
        self.assertIn("数据来源：** 数据库", content)
        self.assertIsNone(
            source_flow.get_state(chat_id="chat-1", sender_id="user-1")
        )

    def test_router_is_always_multi_and_defaults_to_30_days(self) -> None:
        inputs = router.build_control_inputs("美团诊断")
        self.assertEqual(inputs["platform"], "multi")
        self.assertEqual(inputs["channel_source"], "整体诊断")
        start = __import__("datetime").date.fromisoformat(inputs["period_start"])
        end = __import__("datetime").date.fromisoformat(inputs["period_end"])
        self.assertEqual((end - start).days + 1, 30)


if __name__ == "__main__":
    unittest.main()
