# -*- coding: utf-8 -*-
"""天源数据服务：Open-Meteo 免费无密钥 API（历史归档 + 预报）。
历史归档用于 P1 观山指数模型训练；预报用于 P0 实时看板与规则版指数。"""
import requests

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TZ = "Asia/Shanghai"

# metric → (单位, 说明)  统一口径，入库即溯源
METRICS = {
    "temperature_c": "气温",
    "humidity_pct": "相对湿度",
    "cloud_cover_pct": "云量",
    "precipitation_mm": "降水量",
    "visibility_m": "能见度",
    "wind_kmh": "风速",
}


def fetch_archive(site: dict, start_date: str, end_date: str, timeout=20):
    """历史逐时数据（1985 年至今可回溯），返回标准化观测列表。"""
    r = requests.get(ARCHIVE, params={
        "latitude": site["latitude"], "longitude": site["longitude"],
        "start_date": start_date, "end_date": end_date,
        "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,precipitation,wind_speed_10m",
        "timezone": TZ,
    }, timeout=timeout)
    r.raise_for_status()
    h = r.json()["hourly"]
    out = []
    for i, t in enumerate(h["time"]):
        for metric, key, unit in [("temperature_c", "temperature_2m", "°C"),
                                  ("humidity_pct", "relative_humidity_2m", "%"),
                                  ("cloud_cover_pct", "cloud_cover", "%"),
                                  ("precipitation_mm", "precipitation", "mm"),
                                  ("wind_kmh", "wind_speed_10m", "km/h")]:
            v = h[key][i]
            if v is not None:
                out.append({"metric": metric, "ts": t, "value": float(v), "unit": unit})
    return out


def fetch_history_hourly(site: dict, start_date: str, end_date: str, timeout=30):
    """归档接口逐时 dict（注意：归档不支持能见度，实测全 null；训练请用 fetch_past_hourly）。"""
    r = requests.get(ARCHIVE, params={
        "latitude": site["latitude"], "longitude": site["longitude"],
        "start_date": start_date, "end_date": end_date,
        "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,precipitation,"
                  "wind_speed_10m,visibility",
        "timezone": TZ,
    }, timeout=timeout)
    r.raise_for_status()
    return r.json()["hourly"]


def fetch_past_hourly(site: dict, start_date: str, end_date: str, timeout=30):
    """P1 训练标签源：预报接口 past_days 模式（能见度真实可得，窗口≤92天）。"""
    r = requests.get(FORECAST, params={
        "latitude": site["latitude"], "longitude": site["longitude"],
        "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,precipitation,"
                  "wind_speed_10m,visibility",
        "start_date": start_date, "end_date": end_date, "timezone": TZ,
    }, timeout=timeout)
    r.raise_for_status()
    return r.json()["hourly"]


def fetch_forecast(site: dict, days=3, timeout=20):
    """未来 N 天逐时预报：云量/能见度/降水/温湿度 → 规则版观山指数输入。"""
    r = requests.get(FORECAST, params={
        "latitude": site["latitude"], "longitude": site["longitude"],
        "hourly": "temperature_2m,relative_humidity_2m,cloud_cover,precipitation,visibility,wind_speed_10m",
        "forecast_days": days, "timezone": TZ,
    }, timeout=timeout)
    r.raise_for_status()
    h = r.json()["hourly"]
    out = []
    for i, t in enumerate(h["time"]):
        pairs = [("temperature_c", "temperature_2m", "°C"),
                 ("humidity_pct", "relative_humidity_2m", "%"),
                 ("cloud_cover_pct", "cloud_cover", "%"),
                 ("precipitation_mm", "precipitation", "mm"),
                 ("visibility_m", "visibility", "m"),
                 ("wind_kmh", "wind_speed_10m", "km/h")]
        for metric, key, unit in pairs:
            v = h[key][i]
            if v is not None:
                out.append({"metric": metric, "ts": t, "value": float(v), "unit": unit})
    return out


def mountain_index_rule(forecast_obs: list, date: str):
    """P0 规则版观山指数：100 - 0.5*云量 - 15*(当日累计降水>0.5mm) - 0.1*max(0,湿度-70)。
    P1 将替换为 Open-Meteo 历史回测训练的轻量模型（目标回测准确率 ≥75%，如实公布混淆矩阵）。"""
    rows = [o for o in forecast_obs if o["ts"].startswith(date)]
    if not rows:
        return None
    cloud = [o["value"] for o in rows if o["metric"] == "cloud_cover_pct"]
    rain = sum(o["value"] for o in rows if o["metric"] == "precipitation_mm")
    hum = [o["value"] for o in rows if o["metric"] == "humidity_pct"]
    if not cloud:
        return None
    idx = 100 - 0.5 * (sum(cloud) / len(cloud))
    if rain > 0.5:
        idx -= 15
    if hum:
        idx -= 0.1 * max(0.0, sum(hum) / len(hum) - 70)
    return round(max(0.0, min(100.0, idx)), 1)
