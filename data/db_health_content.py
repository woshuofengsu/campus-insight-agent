# data/db_health_content.py
"""疾病预防模块数据层 —— 按《04-疾病预防.md》实现内容审核、健康咨询、天气联动闭环。

表（schema v18）：
  health_contents  健康内容发布（草稿/待审核/审核通过/审核不通过/已发布/已下架）
  health_consults  居民健康咨询（待回复/已回复/继续回复/已结束/已关闭/已撤回/超时未回复）

核心规则：
  - 审核人不能与发布人相同；社区自编正文开头必须标注免责声明；
    疫苗接种类必须填写信息更新时间 + 信息有效期，且不允许社区自编。
  - 健康咨询 24 小时回复时限；超时标记"超时未回复"并再次提醒；
    未解决反馈回"继续回复"重新计时；7 天未反馈自动"已结束"；
    待回复可撤回，撤回后可重新打开（可修改一次）。
  - 天气联动：只触发"已发布"且未过期的匹配内容；同一天气事件内不重复触发；
    永久关闭后可重新开启。阈值可配置（仅疾病预防负责人，调整即留痕）。

说明（本轮数据层近似处理，UI 需配合）：
  - "在线负责人"无专门表：通知函数接受 online_user_ids，不传时通知全部 grid 角色。
  - "疾病预防负责人 / 咨询处理人"无配置表：is_disease_prevention_manager 按角色
    （grid/admin/health_mgr）判断，list_consult_handlers 默认返回全部 grid。
  - 联动记录、超时标记、撤回次数等状态统一用 activity_log 留痕承载，
    不额外建表（遵循"不动其他 data/ 文件"约束）。
"""
import json
import logging
import re
from datetime import datetime, timedelta

from data.db_core import get_db
from data.db_notifications import log_activity

_log = logging.getLogger(__name__)

MODULE = "疾病预防"

# ---------- 常量 ----------

CONTENT_TYPES = ["季节性疾病预防", "疫苗接种提醒", "传染病预警", "健康小贴士", "就医指引"]
CONTENT_STATUS_ALL = ["草稿", "待审核", "审核通过", "审核不通过", "已发布", "已下架"]
CONSULT_TYPES = ["疫苗接种", "疾病症状", "就医指引", "健康知识", "其他"]
CONSULT_STATUS_ALL = ["待回复", "已回复", "继续回复", "已结束", "已关闭", "已撤回", "超时未回复"]

REPLY_HOURS = 24                 # 咨询回复时限（小时）
AUTO_CLOSE_DAYS = 7              # 已回复后 7 天未反馈 → 自动已结束
PIN_MAX_DAYS = 7                 # 置顶超过 7 天自动取消
RESUBMIT_REMIND_DAYS = 7         # 审核不通过后 7 天未重新提交 → 提醒一次
CONTENT_MAX_TITLE = 50
CONTENT_MAX_BODY = 5000
CONSULT_MIN_CONTENT = 5
CONSULT_MAX_CONTENT = 500

DISCLAIMER = "本内容由社区整理，仅供参考"
EMERGENCY_HINT = "如出现胸痛、呼吸困难、严重外伤等紧急症状，请立即拨打120，不要仅提交本咨询。"
NO_DIAGNOSIS_HINT = "请勿进行疾病诊断，仅提供一般性建议或就医指引"

# 不允许社区自编的内容类型（必须权威来源）
_AUTHORITY_TYPES = {"疫苗接种提醒", "传染病预警"}
# 权威来源关键词（来源包含这些词视为权威）
_AUTHORITY_KEYWORDS = ["疾控", "卫健委", "卫生局", "政府", "医院", "官方", "国家"]
# 专业信息来源必须为权威机构，不允许社区自编
_SELF_EDIT_SOURCE = "社区自编"

# 联动：天气事件 → 内容 weather_link_json 里的联动键
WEATHER_LINK_KEYS = ["天气转冷", "高温", "暴雨", "台风", "寒潮", "大风", "大雾", "雷电", "冰雹"]
# 联动卡片展示优先级（传染病预警 > 疫苗接种提醒 > 季节性疾病预防 > 健康小贴士 > 就医指引）
LINKAGE_PRIORITY = ["传染病预警", "疫苗接种提醒", "季节性疾病预防", "健康小贴士", "就医指引"]

# 气温联动阈值（可由疾病预防负责人调整，调整即留痕）
_LINKAGE_THRESHOLDS = {"high_temp": 35, "low_temp": 5, "temp_drop": 8}
LINKAGE_TEMP_LABELS = {"high_temp": "高温", "low_temp": "天气转冷", "temp_drop": "天气转冷"}

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


# ---------- 小工具 ----------

def _now() -> datetime:
    return datetime.utcnow()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _validate_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match(phone or ""))


def mask_phone(phone: str) -> str:
    """电话脱敏：138****1234。"""
    if not phone or len(phone) < 7:
        return phone or ""
    return f"{phone[:3]}****{phone[-4:]}"


def _is_authority_source(source: str) -> bool:
    src = source or ""
    if src == _SELF_EDIT_SOURCE:
        return False
    return any(k in src for k in _AUTHORITY_KEYWORDS)


def _log_once(action: str, detail: str, target_type: str = "") -> None:
    """同日同类日志只记一次（提醒/监测类防刷屏）。"""
    today = _fmt(_now())[:10]
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM activity_log WHERE module=? AND action=? "
            "AND substr(created_at,1,10)=? LIMIT 1",
            (MODULE, action, today),
        ).fetchone()
    if row:
        return
    log_activity("系统", action, target_type, module=MODULE, detail=detail)


def _notify_managers(title: str, content: str, related_id: int | None = None,
                     online_user_ids: list[int] | None = None) -> int:
    """通知负责人（默认全部 grid 角色；在线名单由调用方传入）。"""
    try:
        from data.db_notifications import create_notification
        users = []
        if online_user_ids:
            users = [{"id": uid} for uid in online_user_ids]
        else:
            from data.db_user import list_users
            users = list_users(role="grid")
        count = 0
        for u in users:
            try:
                create_notification(u["id"], "health_consult", title, content, related_id)
                count += 1
            except Exception:
                _log.warning("负责人通知发送失败：user_id=%s", u.get("id"), exc_info=True)
        return count
    except Exception:
        _log.warning("负责人通知整体失败", exc_info=True)
        return 0


def _notify_resident(user_id: int, title: str, content: str, related_id: int | None = None) -> None:
    try:
        from data.db_notifications import create_notification
        create_notification(user_id, "health_consult", title, content, related_id)
    except Exception:
        _log.warning("居民通知发送失败：user_id=%s", user_id, exc_info=True)


def is_disease_prevention_manager(user: dict) -> bool:
    """疾病预防负责人判断（本轮按角色近似：grid/admin/health_mgr 均可配置为处理人）。"""
    role = (user or {}).get("role", "")
    return role in ("grid", "admin", "health_mgr")


def list_consult_handlers() -> list[dict]:
    """咨询处理人名单：疾病预防负责人自动成为处理人，本轮默认全部 grid 角色。"""
    try:
        from data.db_user import list_users
        return list_users(role="grid")
    except Exception:
        return []


# ============================================================
# 一、健康内容发布与审核
# ============================================================

def create_content(title: str, content_type: str, body: str, source: str,
                   publisher: str, auditor: str = "", weather_link: list[str] | None = None,
                   elderly_reminder_text: str = "", info_updated_at: str = "",
                   expire_at: str = "", is_pinned: int = 0) -> tuple[int, str]:
    """创建内容（状态=草稿）。返回 (内容 ID, 提示语)；失败返回 (0, 错误信息)。"""
    if not title or not title.strip():
        return 0, "标题不能为空"
    if len(title.strip()) > CONTENT_MAX_TITLE:
        return 0, f"标题最长 {CONTENT_MAX_TITLE} 字"
    if content_type not in CONTENT_TYPES:
        return 0, "请选择正确的内容类型"
    if not body or len(body.strip()) < 5:
        return 0, "正文不能为空（至少 5 字）"
    if len(body.strip()) > CONTENT_MAX_BODY:
        return 0, f"正文最长 {CONTENT_MAX_BODY} 字"
    if not publisher:
        return 0, "缺少发布人信息"

    body = body.strip()
    # 社区自编：正文开头自动标注免责声明
    if source == _SELF_EDIT_SOURCE and not body.startswith(DISCLAIMER):
        body = f"{DISCLAIMER}\n\n{body}"

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO health_contents (title, content_type, body, source, publisher, "
            "auditor, status, is_pinned, weather_link_json, elderly_reminder_text, "
            "info_updated_at, expire_at) VALUES (?, ?, ?, ?, ?, ?, '草稿', ?, ?, ?, ?, ?)",
            (title.strip(), content_type, body, source, publisher, auditor,
             is_pinned, json.dumps(weather_link or [], ensure_ascii=False),
             elderly_reminder_text, info_updated_at, expire_at),
        )
        content_id = cur.lastrowid
        conn.commit()
    log_activity(publisher, "创建健康内容", "health_content", content_id, title.strip(),
                 module=MODULE, after_value="草稿", detail=f"类型：{content_type}；来源：{source}")
    return content_id, "ok"


def update_content(content_id: int, actor: str, title: str = "", content_type: str = "",
                   body: str = "", source: str = "", auditor: str | None = None,
                   weather_link: list[str] | None = None,
                   elderly_reminder_text: str | None = None,
                   info_updated_at: str | None = None, expire_at: str | None = None,
                   is_pinned: int | None = None) -> tuple[bool, str]:
    """编辑内容（仅草稿 / 审核不通过可编辑）。

    传 None 表示该字段保持不变；传空串表示清空该字段（title/body/source 用空串表示不修改）。
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM health_contents WHERE id=?", (content_id,)).fetchone()
        if row is None:
            return False, "内容不存在"
        if row["status"] not in ("草稿", "审核不通过"):
            return False, f"当前状态「{row['status']}」不支持编辑"

        fields = dict(row)
        if title:
            if len(title.strip()) > CONTENT_MAX_TITLE:
                return False, f"标题最长 {CONTENT_MAX_TITLE} 字"
            fields["title"] = title.strip()
        if content_type:
            if content_type not in CONTENT_TYPES:
                return False, "请选择正确的内容类型"
            fields["content_type"] = content_type
        if body:
            body = body.strip()
            if len(body) > CONTENT_MAX_BODY:
                return False, f"正文最长 {CONTENT_MAX_BODY} 字"
            if fields.get("source") == _SELF_EDIT_SOURCE and not body.startswith(DISCLAIMER):
                body = f"{DISCLAIMER}\n\n{body}"
            fields["body"] = body
        if source:
            fields["source"] = source
        if auditor is not None:
            fields["auditor"] = auditor
        if weather_link is not None:
            fields["weather_link_json"] = json.dumps(weather_link, ensure_ascii=False)
        if elderly_reminder_text is not None:
            fields["elderly_reminder_text"] = elderly_reminder_text
        if info_updated_at is not None:
            fields["info_updated_at"] = info_updated_at
        if expire_at is not None:
            fields["expire_at"] = expire_at
        if is_pinned is not None:
            fields["is_pinned"] = is_pinned

        conn.execute(
            "UPDATE health_contents SET title=?, content_type=?, body=?, source=?, auditor=?, "
            "is_pinned=?, weather_link_json=?, elderly_reminder_text=?, info_updated_at=?, "
            "expire_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (fields["title"], fields["content_type"], fields["body"], fields["source"],
             fields["auditor"], fields["is_pinned"], fields["weather_link_json"],
             fields["elderly_reminder_text"], fields["info_updated_at"],
             fields["expire_at"], content_id),
        )
        conn.commit()
    log_activity(actor, "修改健康内容", "health_content", content_id, fields["title"],
                 module=MODULE, before_value=row["status"], after_value=row["status"])
    return True, "ok"


def _validate_submit(content: dict) -> tuple[bool, str]:
    """提交审核前的完整校验（来源/审核人/免责/权威来源/疫苗有效期）。"""
    if not content.get("source"):
        return False, "必须填写内容来源"
    if not content.get("auditor"):
        return False, "必须填写审核人"
    if content.get("auditor") == content.get("publisher"):
        return False, "审核人不能与发布人相同"
    body = content.get("body") or ""
    source = content.get("source") or ""
    content_type = content.get("content_type") or ""
    if source == _SELF_EDIT_SOURCE and not body.startswith(DISCLAIMER):
        return False, f"社区自编内容正文开头必须标注：{DISCLAIMER}"
    if content_type in _AUTHORITY_TYPES and not _is_authority_source(source):
        return False, "疫苗接种提醒/传染病预警类内容来源必须为权威机构，不允许社区自编"
    if content_type == "疫苗接种提醒":
        if not content.get("info_updated_at"):
            return False, "疫苗接种提醒类必须填写信息更新时间"
        if not content.get("expire_at"):
            return False, "疫苗接种提醒类必须填写信息有效期"
    if content.get("weather_link_json"):
        try:
            links = json.loads(content["weather_link_json"] or "[]")
        except (ValueError, TypeError):
            links = []
        if links and not content.get("elderly_reminder_text"):
            return False, "联动天气时必须填写老年端提醒文案（口语化，最多30字）"
        if content.get("elderly_reminder_text") and len(content["elderly_reminder_text"]) > 30:
            return False, "老年端提醒文案最多 30 字"
    return True, ""


def submit_for_review(content_id: int, auditor: str, actor: str = "") -> tuple[bool, str]:
    """提交审核：草稿/审核不通过 → 待审核（校验拦截：缺来源/审核人、审核人与发布人相同等）。

    审核不通过的内容修改后再次提交，仍由原审核人重新审核（auditor 留空则沿用原审核人）。
    """
    with get_db() as conn:
        row = conn.execute("SELECT * FROM health_contents WHERE id=?", (content_id,)).fetchone()
        if row is None:
            return False, "内容不存在"
        content = dict(row)
        if content["status"] not in ("草稿", "审核不通过"):
            return False, f"当前状态「{content['status']}」不支持提交审核"
        if auditor:
            content["auditor"] = auditor
        ok, msg = _validate_submit(content)
        if not ok:
            return False, msg
        conn.execute(
            "UPDATE health_contents SET status='待审核', auditor=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (content["auditor"], content_id),
        )
        conn.commit()
    log_activity(actor or content["publisher"], "提交健康内容审核", "health_content", content_id,
                 content["title"], module=MODULE, before_value=row["status"], after_value="待审核",
                 detail=f"审核人：{content['auditor']}")
    return True, "ok"


def withdraw_submission(content_id: int, actor: str = "") -> tuple[bool, str]:
    """发布人在待审核状态撤回修改：待审核 → 草稿。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, title, publisher FROM health_contents WHERE id=?", (content_id,)
        ).fetchone()
        if row is None:
            return False, "内容不存在"
        if row["status"] != "待审核":
            return False, f"当前状态「{row['status']}」不支持撤回"
        conn.execute(
            "UPDATE health_contents SET status='草稿', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (content_id,),
        )
        conn.commit()
    log_activity(actor or row["publisher"], "撤回健康内容审核", "health_content", content_id,
                 row["title"], module=MODULE, before_value="待审核", after_value="草稿")
    return True, "ok"


def review_content(content_id: int, approve: bool, opinion: str = "",
                   actor: str = "") -> tuple[bool, str]:
    """审核人审核：通过 → 已发布（置顶校验）；不通过 → 审核不通过（意见必填）。"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM health_contents WHERE id=?", (content_id,)).fetchone()
        if row is None:
            return False, "内容不存在"
        if row["status"] != "待审核":
            return False, f"当前状态「{row['status']}」不支持审核"
        if row["auditor"] and actor and row["auditor"] != actor:
            return False, "仅原审核人可审核该内容"
        if not approve and not opinion.strip():
            return False, "审核不通过必须填写审核意见"
        content = dict(row)
        if approve and content["is_pinned"]:
            dup = conn.execute(
                "SELECT id FROM health_contents WHERE content_type=? AND is_pinned=1 "
                "AND status='已发布' AND id!=? LIMIT 1",
                (content["content_type"], content_id),
            ).fetchone()
            if dup:
                return False, f"「{content['content_type']}」类型已有置顶内容（每类型最多置顶1条）"
        new_status = "已发布" if approve else "审核不通过"
        conn.execute(
            "UPDATE health_contents SET status=?, audit_opinion=?, "
            "published_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE published_at END, "
            "pinned_at=CASE WHEN is_pinned=1 AND pinned_at IS NULL THEN CURRENT_TIMESTAMP ELSE pinned_at END, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_status, opinion.strip(), 1 if approve else 0, content_id),
        )
        conn.commit()
    log_activity(actor or row["auditor"], "审核通过" if approve else "审核不通过",
                 "health_content", content_id, row["title"], module=MODULE,
                 before_value="待审核", after_value=new_status, detail=opinion.strip())
    return True, "ok"


def delete_draft(content_id: int, actor: str = "") -> tuple[bool, str]:
    """删除草稿（仅草稿状态可删除）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, title, publisher FROM health_contents WHERE id=?", (content_id,)
        ).fetchone()
        if row is None:
            return False, "内容不存在"
        if row["status"] != "草稿":
            return False, "仅草稿状态可删除"
        conn.execute("DELETE FROM health_contents WHERE id=?", (content_id,))
        conn.commit()
    log_activity(actor or row["publisher"], "删除健康内容草稿", "health_content", content_id,
                 row["title"], module=MODULE, before_value="草稿", after_value="已删除")
    return True, "ok"


def set_pinned(content_id: int, pinned: bool, actor: str = "") -> tuple[bool, str]:
    """置顶/取消置顶：每内容类型最多 1 条置顶。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, content_type, title, is_pinned FROM health_contents WHERE id=?",
            (content_id,),
        ).fetchone()
        if row is None:
            return False, "内容不存在"
        if pinned and not row["is_pinned"]:
            dup = conn.execute(
                "SELECT id FROM health_contents WHERE content_type=? AND is_pinned=1 "
                "AND id!=? LIMIT 1",
                (row["content_type"], content_id),
            ).fetchone()
            if dup:
                return False, f"「{row['content_type']}」类型已有置顶内容（每类型最多置顶1条）"
        conn.execute(
            "UPDATE health_contents SET is_pinned=?, pinned_at=CASE WHEN ? THEN CURRENT_TIMESTAMP "
            "ELSE pinned_at END, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (1 if pinned else 0, 1 if pinned else 0, content_id),
        )
        conn.commit()
    log_activity(actor, "置顶内容" if pinned else "取消置顶", "health_content", content_id,
                 row["title"], module=MODULE,
                 before_value="置顶" if row["is_pinned"] else "未置顶",
                 after_value="置顶" if pinned else "未置顶")
    return True, "ok"


def take_down_content(content_id: int, reason: str, confirm: bool = False,
                      actor: str = "") -> tuple[bool, str]:
    """下架已发布内容：原因必填 + 二次确认。下架后居民端不显示，后台可查看留痕。"""
    if not reason or not reason.strip():
        return False, "下架原因必填"
    if not confirm:
        return False, "请二次确认后再下架"
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, title, publisher FROM health_contents WHERE id=?", (content_id,)
        ).fetchone()
        if row is None:
            return False, "内容不存在"
        if row["status"] != "已发布":
            return False, f"当前状态「{row['status']}」不支持下架"
        conn.execute(
            "UPDATE health_contents SET status='已下架', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (content_id,),
        )
        conn.commit()
    log_activity(actor or row["publisher"], "下架健康内容", "health_content", content_id,
                 row["title"], module=MODULE, before_value="已发布", after_value="已下架",
                 detail=reason.strip())
    return True, "ok"


def auto_unpin_expired() -> list[int]:
    """置顶超过 7 天自动取消（系统自动，留痕）。"""
    cutoff = _fmt(_now() - timedelta(days=PIN_MAX_DAYS))
    unpinned: list[int] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title FROM health_contents WHERE is_pinned=1 AND pinned_at IS NOT NULL "
            "AND pinned_at<?", (cutoff,),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE health_contents SET is_pinned=0 WHERE id=?", (r["id"],))
            unpinned.append(r["id"])
        conn.commit()
    for r in rows:
        log_activity("系统", "置顶自动取消", "health_content", r["id"], r["title"],
                     module=MODULE, before_value="置顶", after_value="未置顶",
                     detail=f"置顶超过{PIN_MAX_DAYS}天自动取消")
    return unpinned


def expire_contents() -> list[dict]:
    """疫苗类内容到期自动下架并提醒负责人；失败记录异常通知手动下架。"""
    today = _fmt(_now())[:10]
    results: list[dict] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM health_contents WHERE content_type='疫苗接种提醒' "
            "AND status='已发布' AND expire_at!='' AND expire_at<?",
            (today,),
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE health_contents SET status='已下架', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (r["id"],),
            )
            results.append({"id": r["id"], "title": r["title"]})
        conn.commit()
    for item in results:
        log_activity("系统", "疫苗内容到期自动下架", "health_content", item["id"],
                     item["title"], module=MODULE, before_value="已发布", after_value="已下架",
                     detail="信息有效期已到，自动下架并提醒负责人")
        _notify_managers(f"💉 疫苗提醒内容已到期下架：{item['title']}",
                         "该疫苗接种提醒内容已过信息有效期，已自动下架，请确认是否需要更新后重新发布。",
                         related_id=item["id"])
    return results


def get_content(content_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM health_contents WHERE id=?", (content_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["weather_link"] = json.loads(d.get("weather_link_json") or "[]")
        except (ValueError, TypeError):
            d["weather_link"] = []
        return d


def list_contents(status: str | None = None, content_type: str | None = None,
                  keyword: str | None = None, limit: int = 100) -> list[dict]:
    """负责人端内容管理列表。"""
    q = "SELECT * FROM health_contents WHERE 1=1"
    args: list = []
    if status:
        q += " AND status=?"
        args.append(status)
    if content_type:
        q += " AND content_type=?"
        args.append(content_type)
    if keyword:
        q += " AND (title LIKE ? OR body LIKE ?)"
        args += [f"%{keyword}%", f"%{keyword}%"]
    q += " ORDER BY is_pinned DESC, id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["weather_link"] = json.loads(d.get("weather_link_json") or "[]")
            except (ValueError, TypeError):
                d["weather_link"] = []
            out.append(d)
        return out


def get_published_contents(content_type: str | None = None, limit: int = 100) -> list[dict]:
    """居民端可见内容：已发布 + 未过期；置顶优先，其余按发布时间倒序。"""
    today = _fmt(_now())[:10]
    q = ("SELECT * FROM health_contents WHERE status='已发布' "
         "AND (expire_at='' OR expire_at>=?)")
    args: list = [today]
    if content_type:
        q += " AND content_type=?"
        args.append(content_type)
    q += " ORDER BY is_pinned DESC, published_at DESC, id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["weather_link"] = json.loads(d.get("weather_link_json") or "[]")
            except (ValueError, TypeError):
                d["weather_link"] = []
            out.append(d)
        return out


def has_content_updated_this_month() -> bool:
    """本自然月是否有内容更新过（更新频率提醒用）。"""
    month = _fmt(_now())[:7]
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM health_contents WHERE substr(updated_at,1,7)=?",
            (month,),
        ).fetchone()
        return bool(row and row["cnt"] > 0)


def monthly_update_reminder() -> dict:
    """每月 25 日提前 3 天提醒；超时未更新次月 1 日再次提醒（不标记，仅提醒）。"""
    now = _now()
    day = now.day
    month = now.month
    today = _fmt(now)[:10]
    result = {"reminded": False, "kind": "", "note": ""}
    if day == 25 and not has_content_updated_this_month():
        _log_once("内容更新提醒", f"今天是{today}，请在本月内更新疾病预防内容（每月至少更新一次）")
        result = {"reminded": True, "kind": "monthly_25", "note": "每月25日提前3天提醒"}
    elif day == 1 and not has_content_updated_this_month() and month > 1:
        _log_once("内容更新提醒", f"今天是{today}，上月未更新疾病预防内容，请尽快更新")
        result = {"reminded": True, "kind": "next_month_1", "note": "次月1日再次提醒，不标记"}
    return result


def resubmit_reminder() -> list[int]:
    """审核不通过后 7 天未重新提交 → 提醒一次（不自动关闭）。"""
    cutoff = _fmt(_now() - timedelta(days=RESUBMIT_REMIND_DAYS))
    reminded: list[int] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, publisher FROM health_contents "
            "WHERE status='审核不通过' AND updated_at<?", (cutoff,),
        ).fetchall()
    for r in rows:
        _log_once("审核退回修改提醒", f"内容「{r['title']}」审核不通过已超过{RESUBMIT_REMIND_DAYS}天，请尽快修改后重新提交",
                  f"health_content:{r['id']}")
        reminded.append(r["id"])
    return reminded


# ============================================================
# 二、居民健康咨询闭环
# ============================================================

def submit_consult(user_id: int, name: str, phone: str, consult_type: str,
                   content: str, building: str = "", attachment_json: str = "[]",
                   is_agent_report: int = 0, agent_name: str = "",
                   agent_phone: str = "", agent_relation: str = "") -> tuple[int, str, str]:
    """提交健康咨询。校验姓名/电话/类型/内容长度；成功生成记录（状态=待回复）并通知负责人。

    返回 (咨询 ID, 提示语, 咨询编号)。失败返回 (0, 错误信息, "")。
    """
    if not name or not name.strip():
        return 0, "姓名不能为空（可为昵称，但联系电话必须真实）", ""
    if not _validate_phone(phone):
        return 0, "请输入正确的手机号", ""
    if consult_type not in CONSULT_TYPES:
        return 0, "请选择咨询类型", ""
    if not content or len(content.strip()) < CONSULT_MIN_CONTENT:
        return 0, f"咨询内容不能少于 {CONSULT_MIN_CONTENT} 字", ""
    if len(content.strip()) > CONSULT_MAX_CONTENT:
        return 0, f"咨询内容不能超过 {CONSULT_MAX_CONTENT} 字", ""
    if is_agent_report and (not agent_name or not _validate_phone(agent_phone)):
        return 0, "代报需填写代报人姓名和真实电话", ""

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO health_consults (user_id, name, phone, consult_type, content, "
            "building, attachment_json, is_agent_report, agent_name, agent_phone, "
            "agent_relation, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '待回复')",
            (user_id, name.strip(), phone, consult_type, content.strip(), building,
             attachment_json, is_agent_report, agent_name, agent_phone, agent_relation),
        )
        consult_id = cur.lastrowid
        conn.commit()

    code = get_consult_code(consult_id)
    log_activity(name.strip() or "居民", "提交健康咨询", "health_consult", consult_id,
                 target_title=f"咨询{code}", module=MODULE, after_value="待回复",
                 detail=f"类型：{consult_type}")
    _notify_managers(
        f"🩺 新健康咨询（{consult_type}）",
        f"咨询编号 {code}，请尽量在{REPLY_HOURS}小时内回复。",
        related_id=consult_id,
    )
    return consult_id, "ok", code


def get_consult_code(consult_id: int) -> str:
    """咨询编号（唯一可复制）：ZX + 日期 + 序号。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT created_at FROM health_consults WHERE id=?", (consult_id,)
        ).fetchone()
    date_part = (row["created_at"] or "")[:10].replace("-", "") if row else ""
    return f"ZX{date_part}{consult_id:04d}"


def log_emergency_hint_shown(user_id: int) -> None:
    """记录紧急提示已显示（只记录"已显示"，不记录是否阅读，不拦截提交）。"""
    log_activity(f"居民#{user_id}", "显示紧急症状提示", "health_consult", module=MODULE,
                 detail="已显示紧急提示（120），不记录是否阅读")


def log_diagnosis_disclaimer_shown(consult_id: int) -> None:
    """记录回复框旁"请勿进行疾病诊断"提示已显示（提示留痕）。"""
    log_activity("负责人", "显示非诊断提示", "health_consult", consult_id, module=MODULE,
                 detail=NO_DIAGNOSIS_HINT)


def withdraw_consult(consult_id: int, user_id: int) -> tuple[bool, str]:
    """居民撤回咨询（仅待回复状态，可撤回一次）。→ 已撤回。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, user_id FROM health_consults WHERE id=?", (consult_id,)
        ).fetchone()
        if row is None:
            return False, "咨询不存在"
        if row["user_id"] != user_id:
            return False, "只能操作自己的咨询"
        if row["status"] != "待回复":
            return False, f"当前状态「{row['status']}」不支持撤回"
        count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM activity_log WHERE module=? AND action='撤回咨询' "
            "AND target_type='health_consult' AND target_id=?",
            (MODULE, consult_id),
        ).fetchone()
        if count and count["cnt"] > 0:
            return False, "每条咨询只能撤回一次"
        conn.execute("UPDATE health_consults SET status='已撤回' WHERE id=?", (consult_id,))
        conn.commit()
    log_activity(f"居民#{user_id}", "撤回咨询", "health_consult", consult_id,
                 module=MODULE, before_value="待回复", after_value="已撤回")
    return True, "ok"


def reopen_consult(consult_id: int, user_id: int, content: str = "",
                   attachment_json: str | None = None) -> tuple[bool, str]:
    """撤回后重新打开：回到待回复（重新计时），可修改一次（保留原编号留痕）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, user_id FROM health_consults WHERE id=?", (consult_id,)
        ).fetchone()
        if row is None:
            return False, "咨询不存在"
        if row["user_id"] != user_id:
            return False, "只能操作自己的咨询"
        if row["status"] != "已撤回":
            return False, f"当前状态「{row['status']}」不支持重新打开"
        # 修改次数上限：每条咨询最多修改一次
        count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM activity_log WHERE module=? AND action='修改咨询' "
            "AND target_type='health_consult' AND target_id=?",
            (MODULE, consult_id),
        ).fetchone()
        if content and count and count["cnt"] >= 1:
            return False, "每条咨询最多可修改一次"
        if content:
            if len(content.strip()) < CONSULT_MIN_CONTENT or len(content.strip()) > CONSULT_MAX_CONTENT:
                return False, f"咨询内容需在 {CONSULT_MIN_CONTENT}-{CONSULT_MAX_CONTENT} 字之间"
            conn.execute("UPDATE health_consults SET content=? WHERE id=?", (content.strip(), consult_id))
        if attachment_json is not None:
            conn.execute("UPDATE health_consults SET attachment_json=? WHERE id=?",
                         (attachment_json, consult_id))
        # feedback_at 作为"重新计时"基准（待回复状态按 feedback_at 重新起算 24h）
        conn.execute(
            "UPDATE health_consults SET status='待回复', feedback_at=CURRENT_TIMESTAMP WHERE id=?",
            (consult_id,),
        )
        conn.commit()
    if content:
        log_activity(f"居民#{user_id}", "修改咨询", "health_consult", consult_id,
                     module=MODULE, before_value="已撤回", after_value="待回复(已修改)",
                     detail="修改后保留原咨询编号")
    log_activity(f"居民#{user_id}", "重新打开咨询", "health_consult", consult_id,
                 module=MODULE, before_value="已撤回", after_value="待回复",
                 detail="负责人需重新计时24小时")
    return True, "ok"


def reply_consult(consult_id: int, reply: str, actor: str = "",
                  doctor_guide: str = "", need_offline: bool = False,
                  offline_confirmed: bool = False) -> tuple[bool, str]:
    """负责人回复咨询：待回复/继续回复/超时未回复 → 已回复。

    - 回复建议必填；
    - 需线下就医必须二次确认（offline_confirmed=True），回复中置顶"建议尽快线下就医"；
    - 回复框旁"请勿进行疾病诊断"提示由 UI 展示并调用 log_diagnosis_disclaimer_shown 留痕。
    """
    if not reply or not reply.strip():
        return False, "回复建议不能为空"
    if need_offline and not offline_confirmed:
        return False, "判断需线下就医须二次确认后才能提交回复"
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, user_id FROM health_consults WHERE id=?", (consult_id,)
        ).fetchone()
        if row is None:
            return False, "咨询不存在"
        if row["status"] not in ("待回复", "继续回复", "超时未回复"):
            return False, f"当前状态「{row['status']}」不支持回复（状态已变更，请刷新后重试）"
        old = row["status"]
        conn.execute(
            "UPDATE health_consults SET status='已回复', reply=?, reply_doctor_guide=?, "
            "reply_need_offline=?, reply_at=CURRENT_TIMESTAMP WHERE id=?",
            (reply.strip(), doctor_guide, 1 if need_offline else 0, consult_id),
        )
        conn.commit()
    reply_display = ("【建议尽快线下就医】" if need_offline else "") + reply.strip()
    log_activity(actor or "负责人", "回复健康咨询", "health_consult", consult_id,
                 module=MODULE, before_value=old, after_value="已回复",
                 detail=reply_display + (f"；就医指引：{doctor_guide}" if doctor_guide else ""))
    _notify_resident(row["user_id"], "💬 您的健康咨询已回复",
                     reply_display[:200] or "负责人已回复您的健康咨询，请查看。",
                     related_id=consult_id)
    return True, "ok"


def feedback_consult(consult_id: int, user_id: int, solved: bool,
                     reason: str = "") -> tuple[bool, str]:
    """居民反馈：已解决 → 已结束；未解决（原因必填）→ 继续回复（重新计时）。"""
    if not solved and not reason.strip():
        return False, "反馈未解决必须填写原因"
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, user_id FROM health_consults WHERE id=?", (consult_id,)
        ).fetchone()
        if row is None:
            return False, "咨询不存在"
        if row["user_id"] != user_id:
            return False, "只能操作自己的咨询"
        if row["status"] != "已回复":
            return False, f"当前状态「{row['status']}」不支持反馈"
        old = row["status"]
        new_status = "已结束" if solved else "继续回复"
        conn.execute(
            "UPDATE health_consults SET status=?, feedback=?, feedback_reason=?, "
            "feedback_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_status, "已解决" if solved else "未解决", reason.strip(), consult_id),
        )
        conn.commit()
    log_activity(f"居民#{user_id}", "反馈已解决" if solved else "反馈未解决", "health_consult",
                 consult_id, module=MODULE, before_value=old, after_value=new_status,
                 detail=reason.strip() or "")
    if not solved:
        _notify_managers(f"🔄 健康咨询待继续回复（{get_consult_code(consult_id)}）",
                         "居民反馈未解决，请继续回复（重新开始24小时回复时限）。",
                         related_id=consult_id)
    return True, "ok"


def close_consult(consult_id: int, user_id: int) -> tuple[bool, str]:
    """居民主动关闭咨询（负责人不可主动关闭）。→ 已关闭。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, user_id FROM health_consults WHERE id=?", (consult_id,)
        ).fetchone()
        if row is None:
            return False, "咨询不存在"
        if row["user_id"] != user_id:
            return False, "只能操作自己的咨询"
        if row["status"] not in ("待回复", "已回复", "继续回复", "超时未回复"):
            return False, f"当前状态「{row['status']}」不支持关闭"
        old = row["status"]
        conn.execute("UPDATE health_consults SET status='已关闭' WHERE id=?", (consult_id,))
        conn.commit()
    log_activity(f"居民#{user_id}", "关闭咨询", "health_consult", consult_id,
                 module=MODULE, before_value=old, after_value="已关闭")
    return True, "ok"


def mark_overdue_consults() -> list[dict]:
    """24 小时未回复 → 标记"超时未回复"，记录超时时长并再次提醒负责人。"""
    overdue: list[dict] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, consult_type FROM health_consults "
            "WHERE status IN ('待回复','继续回复') "
            "AND julianday('now') - julianday(COALESCE("
            "CASE WHEN status='继续回复' THEN feedback_at ELSE NULL END, created_at)) > ?",
            (REPLY_HOURS / 24.0,),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE health_consults SET status='超时未回复' WHERE id=?", (r["id"],))
            overdue.append(dict(r))
        conn.commit()
    for r in overdue:
        code = get_consult_code(r["id"])
        hours = _overdue_hours(r["id"])
        log_activity("系统", "咨询超时未回复", "health_consult", r["id"],
                     target_title=code, module=MODULE,
                     before_value="待回复/继续回复", after_value="超时未回复",
                     detail=f"超过{REPLY_HOURS}小时未回复，超时时长{hours}小时，再次提醒负责人")
        _notify_managers(f"⏰ 健康咨询超时未回复：{code}",
                         f"咨询（{r['consult_type']}）已超{REPLY_HOURS}小时未回复（超时{hours}小时），请尽快处理。",
                         related_id=r["id"])
    return overdue


def _overdue_hours(consult_id: int) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT julianday('now') - julianday(created_at) AS days FROM health_consults WHERE id=?",
            (consult_id,),
        ).fetchone()
    if not row or row["days"] is None:
        return 0
    return int(row["days"] * 24)


def auto_close_stale_consults() -> list[int]:
    """已回复后 7 天未反馈 → 自动已结束（系统自动，留痕）。"""
    cutoff = _fmt(_now() - timedelta(days=AUTO_CLOSE_DAYS))
    closed: list[int] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM health_consults WHERE status='已回复' AND feedback_at IS NULL "
            "AND reply_at IS NOT NULL AND reply_at<?", (cutoff,),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE health_consults SET status='已结束' WHERE id=?", (r["id"],))
            closed.append(r["id"])
        conn.commit()
    for cid in closed:
        log_activity("系统", "咨询自动结束", "health_consult", cid,
                     target_title=get_consult_code(cid), module=MODULE,
                     before_value="已回复", after_value="已结束",
                     detail=f"已回复后{AUTO_CLOSE_DAYS}天未反馈，自动已结束")
    return closed


def get_consult(consult_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM health_consults WHERE id=?", (consult_id,)).fetchone()
        return dict(row) if row else None


def list_consults(status: str | None = None, consult_type: str | None = None,
                  keyword: str | None = None, limit: int = 100) -> list[dict]:
    """负责人端咨询管理列表（电话脱敏；列表不直接展示内容和附件）。"""
    q = "SELECT * FROM health_consults WHERE 1=1"
    args: list = []
    if status:
        q += " AND status=?"
        args.append(status)
    if consult_type:
        q += " AND consult_type=?"
        args.append(consult_type)
    if keyword:
        q += " AND (name LIKE ? OR phone LIKE ? OR content LIKE ?)"
        args += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["phone_masked"] = mask_phone(d.get("phone", ""))
            d["code"] = get_consult_code(d["id"])
            out.append(d)
        return out


def get_my_consults(user_id: int, limit: int = 50) -> list[dict]:
    """居民"我的咨询"列表（含电话明文，仅本人可见）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM health_consults WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["code"] = get_consult_code(d["id"])
            out.append(d)
        return out


def get_unread_reply_count(user_id: int) -> int:
    """"我的咨询"未读回复徽标数：有回复待查看/待反馈的咨询数（近似口径）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM health_consults "
            "WHERE user_id=? AND status IN ('已回复','继续回复')",
            (user_id,),
        ).fetchone()
        return row["cnt"] if row else 0


# ============================================================
# 三、天气联动触发
# ============================================================

def get_linkage_thresholds() -> dict:
    """联动阈值（当前生效值）：高温/低温/24小时降温。"""
    return dict(_LINKAGE_THRESHOLDS)


def set_linkage_thresholds(high_temp: int | None = None, low_temp: int | None = None,
                           temp_drop: int | None = None, actor: str = "") -> dict:
    """调整联动阈值：仅疾病预防负责人可操作，调整后立即生效并留痕（不需二次确认）。

    说明：本轮阈值为进程内配置 + 留痕；跨重启持久化需配置表，由 UI/后续版本承接。
    """
    changes: list[str] = []
    if high_temp is not None and high_temp != _LINKAGE_THRESHOLDS["high_temp"]:
        changes.append(f"高温阈值 {_LINKAGE_THRESHOLDS['high_temp']}℃→{high_temp}℃")
        _LINKAGE_THRESHOLDS["high_temp"] = high_temp
    if low_temp is not None and low_temp != _LINKAGE_THRESHOLDS["low_temp"]:
        changes.append(f"低温阈值 {_LINKAGE_THRESHOLDS['low_temp']}℃→{low_temp}℃")
        _LINKAGE_THRESHOLDS["low_temp"] = low_temp
    if temp_drop is not None and temp_drop != _LINKAGE_THRESHOLDS["temp_drop"]:
        changes.append(f"降温阈值 {_LINKAGE_THRESHOLDS['temp_drop']}℃→{temp_drop}℃")
        _LINKAGE_THRESHOLDS["temp_drop"] = temp_drop
    if changes:
        log_activity(actor or "疾病预防负责人", "调整天气联动阈值", "weather_linkage",
                     module=MODULE, detail="；".join(changes))
    return get_linkage_thresholds()


def weather_event_to_link_keys(weather_event: dict) -> list[str]:
    """天气事件 → 联动键列表。

    weather_event 支持两种来源：
      1) 天气预警：{"alert_type": "高温", "level": "黄色", ...}
      2) 气温阈值：{"temp_high": 37, "temp_low": 3, "temp_drop_24h": 9, ...}
    """
    keys: list[str] = []
    alert_type = weather_event.get("alert_type", "")
    if alert_type in WEATHER_LINK_KEYS:
        keys.append(alert_type)
    # 气温阈值联动
    high = weather_event.get("temp_high")
    low = weather_event.get("temp_low")
    drop = weather_event.get("temp_drop_24h")
    if high is not None:
        try:
            if int(high) >= _LINKAGE_THRESHOLDS["high_temp"]:
                keys.append("高温")
        except (TypeError, ValueError):
            pass
    if low is not None:
        try:
            if int(low) <= _LINKAGE_THRESHOLDS["low_temp"]:
                keys.append("天气转冷")
        except (TypeError, ValueError):
            pass
    if drop is not None:
        try:
            if int(drop) >= _LINKAGE_THRESHOLDS["temp_drop"]:
                keys.append("天气转冷")
        except (TypeError, ValueError):
            pass
    # 去重并保持 WEATHER_LINK_KEYS 顺序
    return [k for k in WEATHER_LINK_KEYS if k in keys]


def _linkage_perm_closed(link_key: str) -> bool:
    """是否已永久关闭（且之后未重新开启）。"""
    with get_db() as conn:
        closed = conn.execute(
            "SELECT id FROM activity_log WHERE module=? AND action='永久关闭联动' "
            "AND target_type='weather_linkage' AND detail=? ORDER BY id DESC LIMIT 1",
            (MODULE, link_key),
        ).fetchone()
        if not closed:
            return False
        reopened = conn.execute(
            "SELECT id FROM activity_log WHERE module=? AND action='重新开启联动' "
            "AND target_type='weather_linkage' AND detail=? AND id>? ORDER BY id DESC LIMIT 1",
            (MODULE, link_key, closed["id"]),
        ).fetchone()
        return reopened is None


def _linkage_triggered_today(link_key: str) -> bool:
    """同一天气事件内不再触发（本轮按"同键同日"近似去重）。"""
    today = _fmt(_now())[:10]
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM activity_log WHERE module=? AND action='联动提醒触发' "
            "AND target_type='weather_linkage' AND detail LIKE ? AND substr(created_at,1,10)=? "
            "ORDER BY id DESC LIMIT 1",
            (MODULE, f"%{link_key}%", today),
        ).fetchone()
    return row is not None


def _find_linkable_contents(link_key: str) -> list[dict]:
    """找"已发布 + 未过期 + 联动键匹配"的内容，按优先级排序。"""
    contents = get_published_contents(limit=200)
    matched = [c for c in contents if link_key in (c.get("weather_link") or [])]
    matched.sort(key=lambda c: LINKAGE_PRIORITY.index(c["content_type"])
                 if c["content_type"] in LINKAGE_PRIORITY else 99)
    return matched


def trigger_weather_linkage(weather_event: dict, actor: str = "系统") -> dict:
    """天气联动触发：校验内容有效性 → 触发居民卡片/老年语音/后台记录。

    返回：
      {
        "keys": [...], "triggered": [内容...], "missing": [联动键...],
        "notified_missing": bool, "elderly_texts": [...],
      }
    """
    keys = weather_event_to_link_keys(weather_event)
    result: dict = {"keys": keys, "triggered": [], "missing": [], "notified_missing": False,
                    "elderly_texts": []}
    for key in keys:
        if _linkage_perm_closed(key):
            continue
        if _linkage_triggered_today(key):
            continue
        matched = _find_linkable_contents(key)
        if not matched:
            result["missing"].append(key)
            _log_once("联动内容缺失", f"联动键「{key}」无已发布且未过期的匹配内容，无法触发联动")
            result["notified_missing"] = True
            _notify_managers(
                f"⚠️ 天气联动内容缺失：{key}",
                "触发联动前校验未通过：无已发布且未过期的匹配内容，请补充内容后重新触发。",
            )
            continue
        content = matched[0]  # 按优先级取最高的一条
        log_activity(actor, "联动提醒触发", "weather_linkage", content["id"],
                     target_title=content["title"], module=MODULE,
                     after_value="已触发",
                     detail=f"{key}|{weather_event.get('level', '')}|{content['content_type']}")
        result["triggered"].append(content)
        if content.get("elderly_reminder_text"):
            result["elderly_texts"].append({
                "content_id": content["id"],
                "text": content["elderly_reminder_text"],
            })
    return result


def get_linkage_records(limit: int = 50) -> list[dict]:
    """联动提醒记录：触发/关闭/永久关闭/重新开启/阈值调整（全部来自留痕）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE module=? AND target_type='weather_linkage' "
            "ORDER BY id DESC LIMIT ?", (MODULE, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def close_linkage(link_key: str, reason: str, actor: str = "",
                  permanent: bool = False, confirm: bool = False) -> tuple[bool, str]:
    """关闭/永久关闭联动：仅疾病预防负责人可操作，需二次确认并留痕。

    permanent=False：同一天气事件内不再触发（同日去重）；
    permanent=True ：永久关闭，需重新开启后才能再次触发。
    """
    if link_key not in WEATHER_LINK_KEYS:
        return False, "联动类型不正确"
    if not reason or not reason.strip():
        return False, "关闭原因必填"
    if not confirm:
        return False, "请二次确认后再关闭"
    action = "永久关闭联动" if permanent else "关闭联动"
    log_activity(actor or "疾病预防负责人", action, "weather_linkage", module=MODULE,
                 before_value="已触发", after_value="已关闭", detail=link_key,
                 target_title=f"{link_key}联动")
    log_activity(actor or "疾病预防负责人", "联动关闭原因", "weather_linkage", module=MODULE,
                 detail=f"{link_key}：{reason.strip()}")
    return True, "ok"


def reopen_linkage(link_key: str, actor: str = "", confirm: bool = False) -> tuple[bool, str]:
    """重新开启永久关闭的联动：仅疾病预防负责人，需二次确认并留痕。"""
    if link_key not in WEATHER_LINK_KEYS:
        return False, "联动类型不正确"
    if not confirm:
        return False, "请二次确认后再重新开启"
    log_activity(actor or "疾病预防负责人", "重新开启联动", "weather_linkage", module=MODULE,
                 before_value="已永久关闭", after_value="已重新开启", detail=link_key,
                 target_title=f"{link_key}联动")
    return True, "ok"


def should_send_elderly_linkage_reminder(content_id: int) -> bool:
    """老年端联动提醒：每天上午 8 点一次，最多连续 7 天（超过需负责人手动决定）。"""
    today = _fmt(_now())[:10]
    with get_db() as conn:
        today_row = conn.execute(
            "SELECT id FROM activity_log WHERE module=? AND action='老年端联动提醒' "
            "AND target_type='health_content' AND target_id=? AND substr(created_at,1,10)=? LIMIT 1",
            (MODULE, content_id, today),
        ).fetchone()
        if today_row:
            return False
        week_ago = _fmt(_now() - timedelta(days=7))
        cnt = conn.execute(
            "SELECT COUNT(*) AS cnt FROM activity_log WHERE module=? AND action='老年端联动提醒' "
            "AND target_type='health_content' AND target_id=? AND created_at>=?",
            (MODULE, content_id, week_ago),
        ).fetchone()
    return not cnt or cnt["cnt"] < 7


def log_elderly_linkage_reminder(content_id: int, text: str) -> None:
    """记录一次老年端联动语音提醒（每天一次，最多连续 7 天由 should_send 控制）。"""
    log_activity("系统", "老年端联动提醒", "health_content", content_id,
                 module=MODULE, detail=text or "")


def get_elderly_linkage_reminders() -> list[dict]:
    """今天应播报的老年端联动提醒（内容已发布且未过期、未永久关闭、7 天窗口内）。"""
    out: list[dict] = []
    for c in get_published_contents(limit=200):
        links = c.get("weather_link") or []
        if not links:
            continue
        if not c.get("elderly_reminder_text"):
            continue
        if any(_linkage_perm_closed(k) for k in links):
            continue
        if should_send_elderly_linkage_reminder(c["id"]):
            out.append({
                "content_id": c["id"],
                "title": c["title"],
                "text": c["elderly_reminder_text"],
                "content_type": c["content_type"],
            })
    return out


def export_contents_csv(status: str | None = None,
                        content_type: str | None = None) -> tuple[str, str]:
    """导出健康内容列表 CSV。返回 (csv 文本, 文件名)。"""
    import csv
    import io
    from datetime import datetime

    rows = list_contents(status=status, content_type=content_type)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["标题", "内容类型", "来源", "发布人", "审核人", "状态", "发布时间", "是否置顶"])
    for r in rows:
        w.writerow([
            r.get("title", ""), r.get("content_type", ""), r.get("source", ""),
            r.get("publisher", ""), r.get("auditor", ""), r.get("status", ""),
            r.get("published_at") or "", "是" if r.get("is_pinned") else "否",
        ])
    return buf.getvalue(), f"健康内容导出_{datetime.now().strftime('%Y%m%d')}.csv"


def export_consults_csv(status: str | None = None,
                        consult_type: str | None = None) -> tuple[str, str]:
    """导出健康咨询列表 CSV（电话脱敏，不含附件与内部备注）。"""
    import csv
    import io
    from datetime import datetime

    rows = list_consults(status=status, consult_type=consult_type)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["咨询编号", "昵称", "电话", "类型", "提交时间", "状态", "回复人", "回复时间", "是否超时"])
    for r in rows:
        phone = r.get("phone", "") or ""
        masked = (phone[:3] + "****" + phone[-4:]) if len(phone) == 11 else phone
        w.writerow([
            r.get("id", ""), r.get("name", ""), masked, r.get("consult_type", ""),
            r.get("created_at") or "", r.get("status", ""), r.get("reply_by", "") or "",
            r.get("reply_at") or "", "是" if r.get("status") == "超时未回复" else "否",
        ])
    return buf.getvalue(), f"健康咨询导出_{datetime.now().strftime('%Y%m%d')}.csv"
