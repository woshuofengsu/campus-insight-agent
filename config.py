# config.py
import logging
import os
from dotenv import load_dotenv

load_dotenv()
_log = logging.getLogger(__name__)

# 密钥读取：本地 .env 和 Streamlit Cloud Secrets 都要支持
# 优先试 st.secrets；没 import streamlit（比如 api.py 或测试）就静默退回 os.getenv。
def _secret(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val is not None and val != "":
            return val
    except Exception:  # 拿不到就记个日志跳过
        _log.debug("st.secrets 读 key '%s' 失败，退回 os.getenv", key)
    return os.getenv(key, default)


# 离线演示模式：.env 里设 OFFLINE_MODE=true，或 URL 带 ?offline=1
OFFLINE_MODE = _secret("OFFLINE_MODE", "").lower() in ("1", "true", "yes")

# 演示模式：默认开（比赛演示一键登录方便）。正式用 .env 设 DEMO_MODE=false 关闭，
# 快速体验按钮消失、走正式鉴权，隔离双角色。
DEMO_MODE = _secret("DEMO_MODE", "true").lower() in ("1", "true", "yes")

# 演示假数据，默认关：比赛/生产环境不每天自动伪造工单/解决/附议/反馈。
# 想演示"持续活跃"就 .env 设 DEMO_LIVE_DATA=true。
DEMO_LIVE_DATA = _secret("DEMO_LIVE_DATA", "").lower() in ("1", "true", "yes")

# 演示闭环机器人，默认开：新工单自动走「处理中→已解决→通知居民」，「办」字闭环真的转起来。
# 生产/真实运营环境设 DEMO_AUTO_WORKER=false 关掉，回到人工流程。
DEMO_AUTO_WORKER = _secret("DEMO_AUTO_WORKER", "true").lower() in ("1", "true", "yes")

DEEPSEEK_API_KEY = _secret("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = _secret("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = _secret("DEEPSEEK_MODEL", "deepseek-chat")

# Agent 参数
AGENT_MAX_ITERATIONS = 6
AGENT_TIMEOUT = 20
AGENT_TEMPERATURE = 0.3

# 感知模块参数
PERCEPTION_IDLE_SECONDS = 30

# 数据源配置
USE_REAL_WEATHER = True        # 和风天气免费 API（感知模块触发用）

# 社区相关设置
# 键名已从 CAMPUS_* 迁到 COMMUNITY_*；旧键仍作 fallback 以保证老 .env 兼容。
COMMUNITY_CITY = _secret("COMMUNITY_CITY", "") or _secret("CAMPUS_CITY", "北京")
COMMUNITY_CITY_ID = _secret("COMMUNITY_CITY_ID", "") or _secret("CAMPUS_CITY_ID", "101010100")
COMMUNITY_DISTRICT = _secret("COMMUNITY_DISTRICT", "") or _secret("CAMPUS_DISTRICT", "海淀区")
COMMUNITY_BG_IMAGE = _secret("COMMUNITY_BG_IMAGE", "") or _secret("CAMPUS_BG_IMAGE", "")  # URL 或本地路径

# 真实 API 密钥
HEFENG_API_KEY = _secret("HEFENG_API_KEY", "")
HEFENG_API_HOST = _secret("HEFENG_API_HOST", "")

# 邮件通知（QQ 邮箱 SMTP；凭据存 .env，绝不提交/打包）
SMTP_HOST = _secret("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(_secret("SMTP_PORT", "465") or "465")
SMTP_USER = _secret("SMTP_USER", "")
SMTP_PASS = _secret("SMTP_PASS", "")      # QQ 邮箱授权码（非登录密码）
SMTP_TO = _secret("SMTP_TO", "")          # 默认收件人；留空则发给自己

# API 鉴权（生产环境在 .env 里配；留空就是免鉴权）
COMMUNITY_API_KEY = _secret("COMMUNITY_API_KEY", "") or _secret("CAMPUS_API_KEY", "")

# 路径
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "community_insight.db")
