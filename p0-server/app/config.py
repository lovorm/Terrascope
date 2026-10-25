# -*- coding: utf-8 -*-
"""全局配置：全部数据源免费/低成本，坐标定点丽江，采集降频防超限。"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# ── 数据库：P0 默认 SQLite 零成本跑通；生产切 PostgreSQL（改 YUNQI_DATABASE_URL）──
# 注意：变量名带前缀，避免与宿主环境常见的 DATABASE_URL 全局变量冲突
DATABASE_URL = os.getenv(
    "YUNQI_DATABASE_URL",
    "sqlite:///" + str(Path(__file__).resolve().parent.parent / "data" / "yunqi.db"),
)

# ── 定点坐标（天源抓取目标点） ──
SITES = {
    "yulong_snow": {"name": "玉龙雪山", "latitude": 27.1197, "longitude": 100.1899},
    "lashi_lake": {"name": "拉市海", "latitude": 26.7070, "longitude": 100.1440},
}

# ── 降频采集：同一数据源两次抓取最小间隔（分钟），避免免费额度超限 ──
MIN_INTERVAL_MIN = {
    "open-meteo": 60,    # 历史气象：逐时数据，1小时抓一次足够
    "qweather": 30,      # 和风天气实时：30分钟
    "cnemc-air": 60,     # 生态环境部空气质量：逐时发布
}

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me-in-env")
QWEATHER_API_KEY = os.getenv("QWEATHER_API_KEY", "")  # 免费订阅，无 Key 时自动跳过

# ESP32 设备上报校验头
DEVICE_KEY_HEADER = "X-Device-Key"
