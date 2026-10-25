# -*- coding: utf-8 -*-
"""天源数据服务：和风天气免费订阅（实时天气/预报/能见度，空气质量历史补充）。
无 API Key 时优雅跳过并记录日志，不阻塞其他数据管道。"""
import requests

from ..config import QWEATHER_API_KEY

NOW_URL = "https://devapi.qweather.com/v7/weather/now"
# 免费订阅为固定 Host；location 用和风 LocationID（丽江 101291401）
LIJIANG_LOCATION = "101291401"


def fetch_now(timeout=15):
    """返回标准化观测列表；未配置 Key 时返回 (None, 'QWEATHER_API_KEY 未配置，已跳过')。"""
    if not QWEATHER_API_KEY:
        return None, "QWEATHER_API_KEY 未配置，已跳过（和风天气免费订阅 dev.qweather.com）"
    r = requests.get(NOW_URL, params={"location": LIJIANG_LOCATION, "key": QWEATHER_API_KEY},
                     timeout=timeout)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != "200":
        return None, f"和风接口返回 code={d.get('code')}"
    out = _parse_now(d["now"])
    return out, "ok"


def _parse_now(now: dict) -> list:
    """解析和风 v7 now 字段；vis 原始单位 km，入库前转换为 m。"""
    unit_map = [("temperature_c", "temp", "°C"), ("humidity_pct", "humidity", "%"),
                ("visibility_m", "vis", "m"), ("pressure_hpa", "pressure", "hPa")]
    return [{"metric": m, "ts": now["obsTime"][:16].replace("T", " ") + ":00",
             "value": float(now[k]) * 1000 if m == "visibility_m" else float(now[k]),
             "unit": u}
            for m, k, u in unit_map if now.get(k) not in (None, "")]
