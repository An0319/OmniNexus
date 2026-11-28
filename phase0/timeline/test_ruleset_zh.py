"""rules_v2-zh.4 的最小测试：载体闸门、R3 ②/④、③ 归属。

覆盖用户在 2026-11-28 裁决里写死的三条：
1. 载体不核时 is_event 不被否决（只改 data_quality）；
2. R3 ②/④ 缺失时判不了，而不是判不是；
3. ③ 归属不在代码里，不影响 is_event。
"""

import datetime as dt
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import timeline  # noqa: E402


def make_item(title, url_kind="publisher"):
    return {
        "title": title,
        "link": "https://example.com/item",
        "url_kind": url_kind,
        "date": "2026-11-28T10:00:00Z",
        "excerpt": title,
        "source_name": "test",
        "fetched_at_utc": "2026-11-28T10:00:01Z",
    }


START = dt.date(2026, 11, 27)
END = dt.date(2026, 11, 28)


class CarrierGateTest(unittest.TestCase):
    def test_carrier_unverified_does_not_veto_is_event(self):
        """载体只写 data_quality；聚合跳转页仍应产出事件。"""
        ev, code = timeline.build_event(make_item("央行宣布降准降息", "aggregator"), START, END)
        self.assertIsNone(code, f"载体未核不应否决事件，实际 code={code}")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["data_quality"], "unverified")

    def test_official_carrier_is_full(self):
        ev, code = timeline.build_event(make_item("央行宣布降准降息", "official"), START, END)
        self.assertIsNone(code)
        self.assertEqual(ev["data_quality"], "full")


class R3ExceptionTest(unittest.TestCase):
    def test_missing_time_or_unit_is_undecidable_not_reject(self):
        """①过、②缺 → 判不了（zh_aggregate_unverifiable），不是不是。"""
        _ev, code = timeline.build_event(make_item("光伏协会发布装机数据"), START, END)
        self.assertEqual(code, "zh_aggregate_unverifiable")

    def test_missing_scope_is_undecidable_not_reject(self):
        """①过、②过、④缺 → 判不了。"""
        _ev, code = timeline.build_event(make_item("多家企业协会发布10月数据"), START, END)
        self.assertEqual(code, "zh_aggregate_unverifiable")

    def test_no_publisher_is_not_event(self):
        """①不过 → 不算（zh_generalized_subject）。"""
        _ev, code = timeline.build_event(make_item("我国光伏装机发布数据"), START, END)
        self.assertEqual(code, "zh_generalized_subject")

    def test_all_three_conditions_pass(self):
        """①②④齐备 → 例外成立，产出事件。"""
        ev, code = timeline.build_event(
            make_item("我国光伏装机发布8000万千瓦数据，协会统计"), START, END
        )
        self.assertIsNone(code, f"R3 例外应通过，实际 code={code}")
        self.assertIsNotNone(ev)


class AttributionTest(unittest.TestCase):
    def test_attribution_has_no_code_path_and_does_not_change_is_event(self):
        """③ 归属无分池可落：输出无 pool/attribution，且地区词不改变 is_event。"""
        ev1, code1 = timeline.build_event(
            make_item("云南能投签署合同收购光伏项目"), START, END
        )
        ev2, code2 = timeline.build_event(
            make_item("能投股份签署合同收购光伏项目"), START, END
        )
        self.assertIsNone(code1)
        self.assertIsNone(code2)
        self.assertIsNotNone(ev1)
        self.assertIsNotNone(ev2)
        for ev in (ev1, ev2):
            self.assertNotIn("pool", ev)
            self.assertNotIn("attribution", ev)


class FutureCommitmentTest(unittest.TestCase):
    """D1（用户裁决）：具名主体的未来承诺算事件，future=true；集体/调度类不算。"""

    def test_future_commitment_is_event(self):
        ev, code = timeline.build_event(
            make_item("中铝国际拟收购几内亚氧化铝项目"), START, END
        )
        self.assertIsNone(code, f"未来承诺应算事件，实际 code={code}")
        self.assertIsNotNone(ev)
        self.assertTrue(ev["future"])
        self.assertNotIn("tracking", ev)  # 追踪属应用层，不进判定输出

    def test_future_price_guidance_is_event(self):
        ev, code = timeline.build_event(make_item("苹果将涨价"), START, END)
        self.assertIsNone(code)
        self.assertTrue(ev["future"])

    def test_collective_future_is_not_event(self):
        ev, code = timeline.build_event(make_item("我国光伏将新增装机"), START, END)
        self.assertIsNone(ev)
        self.assertEqual(code, "zh_future_not_happened")

    def test_scheduled_meeting_is_not_commitment(self):
        ev, _code = timeline.build_event(
            make_item("中国石化将于11月28日召开股东大会"), START, END
        )
        self.assertIsNone(ev)


class TrackingStateTest(unittest.TestCase):
    """追踪是应用层状态：默认关、不写进规则集、不存在即关。"""

    def test_tracking_state_schema_and_default(self):
        path = os.path.join(HERE, "..", "..", "data", "tracking_state.json")
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["version"], 1)
        self.assertEqual(state["layer"], "application")
        self.assertFalse(state["default_tracking"])
        self.assertEqual(state["items"], {})
        self.assertFalse(state["items"].get("not-exist", {}).get("tracking", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
