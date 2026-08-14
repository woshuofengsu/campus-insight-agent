# config.py
import logging
import os
from dotenv import load_dotenv

load_dotenv()
_log = logging.getLogger(__name__)

# ── Secret resolver ──
# Supports BOTH local .env (dev) and Streamlit Cloud Secrets (production).
# st.secrets is tried first; if streamlit isn't imported (e.g. api.py or tests),
# we fall back to os.getenv silently.
def _secret(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val is not None and val != "":
            return val
    except Exception:  # log and skip
        _log.debug("st.secrets access failed for key '%s', falling back to os.getenv", key)
    return os.getenv(key, default)


# ── Offline demo mode ──
# Set OFFLINE_MODE=true in .env or run with ?offline=1 URL param
OFFLINE_MODE = _secret("OFFLINE_MODE", "").lower() in ("1", "true", "yes")

# ── Demo mode ──
# 默认关闭。开启后显示「切换账号」等演示专用功能；正式使用务必关闭以隔离双角色。
DEMO_MODE = _secret("DEMO_MODE", "").lower() in ("1", "true", "yes")

# ── Demo live data ──
# 默认关闭：比赛/生产环境不每天自动伪造工单/解决/附议/反馈。
# 如需演示"持续活跃"的假数据，在 .env 设 DEMO_LIVE_DATA=true。
DEMO_LIVE_DATA = _secret("DEMO_LIVE_DATA", "").lower() in ("1", "true", "yes")

# ── 演示闭环机器人 ──
# 默认开启：新工单自动走「处理中→已解决→通知居民」，让「办」字闭环真的转。
# 生产/真实运营环境设 DEMO_AUTO_WORKER=false 关闭，回到人工流程。
DEMO_AUTO_WORKER = _secret("DEMO_AUTO_WORKER", "true").lower() in ("1", "true", "yes")

DEEPSEEK_API_KEY = _secret("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = _secret("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = _secret("DEEPSEEK_MODEL", "deepseek-chat")

# Agent settings
AGENT_MAX_ITERATIONS = 6
AGENT_TIMEOUT = 20
AGENT_TEMPERATURE = 0.3

# Perception settings
PERCEPTION_IDLE_SECONDS = 30

# ── Data Source Configuration ──
USE_REAL_WEATHER = True        # 和风天气免费 API（感知模块触发用）

# Community settings
# 键名已从 CAMPUS_* 迁到 COMMUNITY_*；旧键仍作 fallback 以保证老 .env 兼容。
COMMUNITY_CITY = _secret("COMMUNITY_CITY", "") or _secret("CAMPUS_CITY", "北京")
COMMUNITY_CITY_ID = _secret("COMMUNITY_CITY_ID", "") or _secret("CAMPUS_CITY_ID", "101010100")
COMMUNITY_DISTRICT = _secret("COMMUNITY_DISTRICT", "") or _secret("CAMPUS_DISTRICT", "海淀区")
COMMUNITY_BG_IMAGE = _secret("COMMUNITY_BG_IMAGE", "") or _secret("CAMPUS_BG_IMAGE", "")  # URL or local path

# Real API keys
HEFENG_API_KEY = _secret("HEFENG_API_KEY", "")
HEFENG_API_HOST = _secret("HEFENG_API_HOST", "")

# ── 邮件通知（QQ 邮箱 SMTP；凭据存于 .env，绝不提交/打包）──
SMTP_HOST = _secret("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(_secret("SMTP_PORT", "465") or "465")
SMTP_USER = _secret("SMTP_USER", "")
SMTP_PASS = _secret("SMTP_PASS", "")      # QQ 邮箱授权码（非登录密码）
SMTP_TO = _secret("SMTP_TO", "")          # 默认收件人；留空则发给自己

# API server auth (set in .env for production; defaults to empty = no auth required)
COMMUNITY_API_KEY = _secret("COMMUNITY_API_KEY", "") or _secret("CAMPUS_API_KEY", "")

# Paths
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "community_insight.db")
