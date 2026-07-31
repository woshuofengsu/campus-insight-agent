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
    except Exception:  # non-critical: logged and suppressed
        _log.debug("st.secrets access failed for key '%s', falling back to os.getenv", key)
    return os.getenv(key, default)


# ── Offline demo mode ──
# Set OFFLINE_MODE=true in .env or run with ?offline=1 URL param
OFFLINE_MODE = _secret("OFFLINE_MODE", "").lower() in ("1", "true", "yes")

DEEPSEEK_API_KEY = _secret("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = _secret("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = _secret("DEEPSEEK_MODEL", "deepseek-chat")

# Agent settings
AGENT_MAX_ITERATIONS = 10
AGENT_TIMEOUT = 30
AGENT_TEMPERATURE = 0.3

# Perception settings
PERCEPTION_IDLE_SECONDS = 30

# ── Data Source Configuration ──
USE_REAL_WEATHER = True        # 和风天气免费API（感知引擎触发用）

# Campus settings
CAMPUS_CITY = _secret("CAMPUS_CITY", "北京")
CAMPUS_CITY_ID = _secret("CAMPUS_CITY_ID", "101010100")
CAMPUS_DISTRICT = _secret("CAMPUS_DISTRICT", "海淀区")
CAMPUS_BG_IMAGE = _secret("CAMPUS_BG_IMAGE", "")  # URL or local path for onboarding background

# Real API keys
HEFENG_API_KEY = _secret("HEFENG_API_KEY", "")
HEFENG_API_HOST = _secret("HEFENG_API_HOST", "")

# API server auth (set in .env for production; defaults to empty = no auth required)
CAMPUS_API_KEY = _secret("CAMPUS_API_KEY", "")

# Paths
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "campus_insight.db")
