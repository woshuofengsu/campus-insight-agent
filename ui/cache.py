# ui/cache.py
"""（垫片，N6）缓存实现已迁至 utils/cache.py，主服务（api_routes）统一从 utils.cache 导入。

本文件仅作历史 UI（Streamlit ui/）向后兼容重导出，主请求链路不再 import ui。
"""
from utils.cache import *  # noqa: F401,F403  (重导出，供旧 ui/ 页面使用；ui/ 被 lint 排除不重复校验)
