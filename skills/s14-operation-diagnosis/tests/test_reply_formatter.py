#!/usr/bin/env python3
"""Tests for the locked S14 Feishu reply format.

Three scenarios are covered:

1. 合法 Agent JSON → 必须精确等于 6 段固定模板。
2. 非 JSON 输入（Markdown / 自然语言 / 代码块 / 空字符串 / 缺字段）→
   必须返回 ``诊断结果格式异常，请重新生成。``，绝不能拼自由文本。
3. 任何非固定模板的字符串（截图里那种"飞猪诊断：xx/100 中风险 | ..."）→
   ``assert_strict_feishu_format`` 必须抛 ``ValueError``。

Run with::

    python3 tests/test_reply_formatter.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.feishu_adapter import (  # noqa: E402
    build_feishu_reply,
    build_feishu_reply_from_agent_output,
)
from runtime.reply_formatter import (  # noqa: E402
    FEISHU_TEMPLATE,
    FORMAT_ERROR_TEXT,
    assert_strict_feishu_format,
    format_agent_json_output,
    format_feishu_message,
    risk_label,
)


VALID_PAYLOAD = {
    "hotel_name": "贵阳璞悦·奢电竞酒店",
    "period_start": "2026-06-01",
    "period_end": "2026-06-10",
    "final_score": 68,
    "report_url": "http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html",
}

EXPECTED_TEXT = (
    "【S14 酒店 OTA 诊断报告已生成】\n"
    "\n"
    "酒店：贵阳璞悦·奢电竞酒店\n"
    "周期：2026-06-01 至 2026-06-10\n"
    "综合得分：68 / 100\n"
    "风险等级：中风险\n"
    "\n"
    "报告链接：\n"
    "http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html\n"
    "\n"
    "说明：当前为 S14 测试机器人返回结果，不影响正式酒店 OTA Agent。"
)


def test_valid_json_renders_exact_template() -> None:
    rendered = format_feishu_message(VALID_PAYLOAD)
    assert rendered == EXPECTED_TEXT, (
        f"合法 JSON 渲染结果与固定模板不一致:\n"
        f"  got:      {rendered!r}\n"
        f"  expected: {EXPECTED_TEXT!r}"
    )
    # 模板常量与上面 EXPECTED_TEXT 同步，模板被改坏时会立即失败。
    assert FEISHU_TEMPLATE.format(
        hotel_name="贵阳璞悦·奢电竞酒店",
        period_start="2026-06-01",
        period_end="2026-06-10",
        final_score_int="68",
        risk_text="中风险",
        report_url="http://47.108.200.194:8088/s14-reports/ota_diagnosis_report_demo.html",
    ) == EXPECTED_TEXT


def test_risk_label_derives_from_score() -> None:
    # 验证 risk_text 强制按 final_score 推导，忽略 Agent 传入值。
    payload = dict(VALID_PAYLOAD, final_score=42, risk_text="低风险")
    rendered = format_feishu_message(payload)
    assert "风险等级：高风险" in rendered
    assert "低风险" not in rendered

    payload = dict(VALID_PAYLOAD, final_score=85, risk_text="高风险")
    rendered = format_feishu_message(payload)
    assert "风险等级：低风险" in rendered
    assert "高风险" not in rendered


def test_score_thresholds() -> None:
    for score, expected in [(0, "高风险"), (59, "高风险"), (60, "中风险"),
                            (79, "中风险"), (80, "低风险"), (100, "低风险")]:
        assert risk_label(score) == expected, f"score={score} 应得 {expected}"


def test_missing_fields() -> None:
    for field in ("hotel_name", "period_start", "period_end", "final_score", "report_url"):
        payload = dict(VALID_PAYLOAD)
        payload.pop(field)
        try:
            format_feishu_message(payload)
        except ValueError as exc:
            assert field in str(exc), f"缺 {field} 应被报告，实际: {exc}"
        else:
            raise AssertionError(f"缺 {field} 必须抛 ValueError")


def test_non_json_agent_output_returns_error() -> None:
    # 截图里那种 deepseek 自由拼接的"飞猪诊断：68/100 中风险 | ..."
    freeform = (
        "飞猪诊断：68/100 中风险 | 仅上架 1 房型，M04 房态仅 44%\n"
        "1 ✅ M06 页面 100% ✅ M07 口碑 86%\n"
        "2 🟡 M01 经营 77% 🟡 M02 流量 68%\n"
        "3 🔴 M04 房态 44% 🔴 M05 推广 45%"
    )
    assert format_agent_json_output(freeform) == FORMAT_ERROR_TEXT
    assert build_feishu_reply_from_agent_output(freeform) == FORMAT_ERROR_TEXT

    # 包裹在 Markdown 代码块里
    md_block = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    assert format_agent_json_output(md_block) == FORMAT_ERROR_TEXT

    # 空 / 非字符串 / 自然语言
    for bad in ["", "   ", "hello world", "诊断完成", None, 123, []]:
        assert format_agent_json_output(bad) == FORMAT_ERROR_TEXT, (
            f"非 JSON 输入 {bad!r} 必须返回错误文本"
        )


def test_agent_json_with_extra_fields_still_renders_template() -> None:
    payload = dict(VALID_PAYLOAD, extra="不允许传", risk_text="低风险", modules=[
        {"id": "M01", "score": 77}, {"id": "M04", "score": 44},
    ])
    rendered = format_agent_json_output(json.dumps(payload))
    assert rendered == EXPECTED_TEXT
    # 渲染结果里不出现 Agent 自由拼接的字段
    assert "modules" not in rendered
    assert "M01" not in rendered
    assert "M04" not in rendered
    assert "低风险" not in rendered  # 强制按分数 = 68 → 中风险


def test_invalid_period_format() -> None:
    payload = dict(VALID_PAYLOAD, period_start="2026/06/01")
    try:
        format_feishu_message(payload)
    except ValueError as exc:
        assert "period_start" in str(exc)
    else:
        raise AssertionError("非 YYYY-MM-DD 的 period_start 必须抛 ValueError")


def test_invalid_score_range() -> None:
    for bad_score in [-1, 101, 150, "abc", True, None]:
        payload = dict(VALID_PAYLOAD, final_score=bad_score)
        try:
            format_feishu_message(payload)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError(f"非法 final_score={bad_score!r} 必须抛 ValueError")


def test_strict_format_rejects_freeform() -> None:
    freeform = (
        "飞猪诊断：68/100 中风险\n"
        "1 ✅ M06 页面 100%"
    )
    try:
        assert_strict_feishu_format(freeform)
    except ValueError:
        pass
    else:
        raise AssertionError("自由文本必须被 assert_strict_feishu_format 拒绝")

    try:
        assert_strict_feishu_format(EXPECTED_TEXT)
    except ValueError as exc:
        raise AssertionError(f"标准模板不应被拒绝: {exc}")


def test_build_feishu_reply_ignores_skill_message_field() -> None:
    """``build_feishu_reply`` 必须从原始字段重新渲染，不信任 skill
    自己拼的 ``feishu_message``。
    """

    bad_message = "飞猪诊断：68/100 中风险 | 仅上架 1 房型"
    result = dict(VALID_PAYLOAD, feishu_message=bad_message)
    rendered = build_feishu_reply(result)
    assert rendered == EXPECTED_TEXT
    assert "飞猪诊断：" not in rendered
    assert "仅上架 1 房型" not in rendered


def test_build_feishu_reply_handles_invalid_payload() -> None:
    """字段缺失时必须返回 FORMAT_ERROR_TEXT，不抛异常。"""

    invalid = {"hotel_name": "贵阳璞悦", "final_score": 60}
    assert build_feishu_reply(invalid) == FORMAT_ERROR_TEXT
    assert build_feishu_reply({}) == FORMAT_ERROR_TEXT
    assert build_feishu_reply(None) == FORMAT_ERROR_TEXT  # type: ignore[arg-type]


def main() -> None:
    tests = [
        test_valid_json_renders_exact_template,
        test_risk_label_derives_from_score,
        test_score_thresholds,
        test_missing_fields,
        test_non_json_agent_output_returns_error,
        test_agent_json_with_extra_fields_still_renders_template,
        test_invalid_period_format,
        test_invalid_score_range,
        test_strict_format_rejects_freeform,
        test_build_feishu_reply_ignores_skill_message_field,
        test_build_feishu_reply_handles_invalid_payload,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
        else:
            print(f"PASS  {test.__name__}")
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed")


if __name__ == "__main__":
    main()
