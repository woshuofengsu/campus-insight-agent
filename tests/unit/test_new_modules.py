# -*- coding: utf-8 -*-
"""新模块核心闭环单元测试 — 报修/提案/通知/政策问答/老年端/天气/疾病预防。

覆盖 7 个按需求文档新增模块的核心状态机与关键规则，防止后续改动回归。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _init_test_db():
    db_path = os.path.join(os.path.dirname(__file__), "_test_new_modules.db")
    from data.database import init_db
    init_db(db_path)
    return db_path


def _cleanup_test_db(db_path):
    try:
        os.unlink(db_path)
    except Exception:
        pass


class TestRepairFlow(unittest.TestCase):
    """报修：完整状态机闭环 + 特殊情况 + 校验。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_full_closed_loop(self):
        from data import db_repair as r
        iid, msg = r.submit_issue(
            "楼道灯坏", "设施维修", "室外", "3号楼2单元",
            "楼道灯忽明忽暗需要尽快维修", "一般", "王阿姨", "13800138000", reporter_id=1,
        )
        self.assertGreater(iid, 0, msg)
        self.assertTrue(r.audit_issue(iid, True)[0])
        self.assertTrue(r.dispatch_issue(iid, "李师傅", "13900139000")[0])
        self.assertTrue(r.start_process(iid)[0])
        self.assertTrue(r.resolve_issue(iid, "已更换灯泡", no_photo_reason="现场不便拍照")[0])
        self.assertTrue(r.feedback_issue(iid, True)[0])
        self.assertEqual(r.get_issue(iid)["status"], "处理结束")
        self.assertGreaterEqual(len(r.get_issue_timeline(iid)), 5)

    def test_safety_and_phone_validation(self):
        from data import db_repair as r
        iid, msg = r.submit_issue(
            "燃气泄漏", "设施维修", "室内", "1号楼101",
            "家里燃气泄漏闻到煤气味", "紧急", "张大爷", "13800138001", reporter_id=2,
        )
        self.assertEqual(iid, 0)
        self.assertEqual(msg, "safety")  # 安全提醒不生成工单
        iid2, _ = r.submit_issue(
            "灯坏", "设施维修", "室外", "某处",
            "楼道灯坏了需要维修", "一般", "测试", "123", reporter_id=1,
        )
        self.assertEqual(iid2, 0)  # 手机号格式校验

    def test_unsatisfied_returns_to_processing(self):
        from data import db_repair as r
        iid, _ = r.submit_issue(
            "水管漏水", "设施维修", "室内", "5号楼101",
            "厨房水管严重漏水需要处理", "紧急", "李叔", "13800138002", reporter_id=1,
        )
        r.audit_issue(iid, True)
        r.dispatch_issue(iid, "李师傅", "13900139000")
        r.start_process(iid)
        r.resolve_issue(iid, "已更换水管", no_photo_reason="现场不便拍照")
        ok, _ = r.feedback_issue(iid, False, "维修质量不行，还漏水")
        self.assertTrue(ok)
        self.assertEqual(r.get_issue(iid)["status"], "处理中")


class TestProposalVote(unittest.TestCase):
    """提案：审核 → 确认公开 → 匿名投票 → 统计。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_anonymous_voting(self):
        import sqlite3
        from data import db_proposal as p
        pid, msg = p.submit_proposal(
            "加装充电桩", "建议在小区公共区域加装电动车充电桩方便居民充电",
            "公共设施", "王阿姨", "13800138000", 1, reporter_id=2,
        )
        self.assertGreater(pid, 0, msg)
        self.assertTrue(p.audit_proposal(pid, True)[0])
        self.assertTrue(p.confirm_visibility(pid, 1)[0])
        self.assertTrue(p.vote_proposal(pid, 3, 4)[0])
        self.assertTrue(p.vote_proposal(pid, 4, 5)[0])
        stats = p.get_proposal_vote_stats(pid)
        self.assertEqual(stats["vote_count"], 2)
        self.assertEqual(stats["avg_score"], 4.5)
        # 匿名铁律：proposal_votes 表无 user_id 列
        c = sqlite3.connect(self._db_path)
        cols = [r[1] for r in c.execute("PRAGMA table_info(proposal_votes)")]
        c.close()
        self.assertNotIn("user_id", cols)

    def test_vote_validation(self):
        from data import db_proposal as p
        pid, _ = p.submit_proposal(
            "绿化改造", "建议重新规划中心花园绿化增加活动区", "环境卫生",
            "孙女士", "13800138003", 1, reporter_id=2,
        )
        p.audit_proposal(pid, True)
        p.confirm_visibility(pid, 1)
        # 非法分数被拦截
        ok, msg = p.vote_proposal(pid, 3, 9)
        self.assertFalse(ok)


class TestNoticePublish(unittest.TestCase):
    """通知：创建 → 发布 → 已读统计。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_publish_and_read_stats(self):
        from data import db_notice as n
        nid = n.create_notice("停水通知", "停水停电通知", "全体居民", "明早8点停水检修")
        self.assertGreater(nid, 0)
        ok, _ = n.publish_notice(nid, 2, "负责人")
        self.assertTrue(ok)
        marked = n.mark_notice_read(nid, "resident", 2)
        self.assertTrue(marked)
        stats = n.get_notice_read_stats(nid)
        # 统计结构正确（测试库无用户，范围外不计入总量，只验证结构）
        self.assertIn("resident_read", stats)
        self.assertIn("resident_total", stats)
        self.assertIn("elderly_total", stats)


class TestPolicyQA(unittest.TestCase):
    """政策问答：知识库审核 → 自动回答 → 转人工 → 回复 → 反馈。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_full_qa_loop(self):
        from data import db_policy as k
        kid, _ = k.create_knowledge(
            "居住证办理", "办事指引", "携带身份证和房产证到社区服务中心办理",
            "社区整理", "居住证 办理 流程", "2026-01-01", actor="张三",
        )
        self.assertGreater(kid, 0)
        k.submit_review(kid, auditor="李四")
        self.assertTrue(k.audit_knowledge(kid, True, actor="李四")[0])
        r = k.ask_question(2, "居住证怎么办理")
        self.assertTrue(r.get("matched"))
        qid = r["question_id"]
        ok, _, _ = k.transfer_to_human(qid)
        self.assertTrue(ok)
        ok, _, _ = k.reply_question(qid, "请携带身份证到社区服务中心一楼窗口办理", actor="负责人")
        self.assertTrue(ok)
        ok, _, _ = k.feedback_question(qid, True)
        self.assertTrue(ok)
        self.assertEqual(k.get_question(qid)["status"], "已结束")


class TestElderlyCare(unittest.TestCase):
    """老年端：用药提醒审核 + 紧急求助闭环。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_medication_and_sos(self):
        from data import db_elderly_care as e
        mid, _ = e.add_medication_reminder(
            2, "张大爷", "降压药", "1片", ["08:00"], start_date="2026-08-01", setter_id=1,
        )
        self.assertGreater(mid, 0)
        self.assertTrue(e.audit_medication(mid, True, actor="负责人")[0])
        cid, _ = e.add_emergency_contact(2, "张小明", "13800138000", "儿子", setter_id=1)
        self.assertGreater(cid, 0)
        self.assertTrue(e.audit_emergency_contact(cid, True, actor="负责人")[0])
        sid, _ = e.trigger_sos(2)
        self.assertGreater(sid, 0)
        self.assertTrue(e.respond_sos(sid, actor="负责人")[0])
        self.assertTrue(e.end_sos(sid, "已上门查看，老人无碍", actor="负责人")[0])


class TestWeatherCheck(unittest.TestCase):
    """天气：检查任务创建 → 确认。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_check_task_flow(self):
        from data import db_weather as w
        task_id = w.create_check_task(1, "暴雨", "黄色")
        self.assertIsNotNone(task_id)
        # 用默认清单逐项确认
        items = [{"item": "检查排水口", "status": "已检查", "note": ""}]
        ok, _ = w.confirm_check_task(task_id, "刘网格员", items)
        self.assertTrue(ok)


class TestHealthContent(unittest.TestCase):
    """疾病预防：内容审核 + 健康咨询闭环。"""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_content_and_consult(self):
        from data import db_health_content as h
        cid, _ = h.create_content(
            "流感预防指南", "季节性疾病预防", "勤洗手、开窗通风、接种疫苗",
            "国家疾控中心", "张三", auditor="李四",
        )
        self.assertGreater(cid, 0)
        self.assertTrue(h.submit_for_review(cid, auditor="李四")[0])
        self.assertTrue(h.review_content(cid, True, actor="李四")[0])
        qid, _, _ = h.submit_consult(2, "王阿姨", "13800138000", "疾病症状", "最近咳嗽厉害要不要紧")
        self.assertGreater(qid, 0)
        self.assertTrue(h.reply_consult(qid, "建议多喝水观察，必要时就医", actor="负责人")[0])
        self.assertTrue(h.feedback_consult(qid, 2, True)[0])


if __name__ == "__main__":
    unittest.main()
