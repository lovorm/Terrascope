# -*- coding: utf-8 -*-
"""观山指数逐日特征聚合：训练与线上共用的唯一口径实现。"""
from datetime import datetime
from statistics import median
from typing import Iterable

_PRECIPITATION = "precipitation_mm"
_VISIBILITY = "visibility_m"
_MIN_VIS_HOURS = 5


def aggregate_daily_observations(observations: Iterable[tuple[datetime, str, float]]) -> dict:
    """规范化观测行 → {date: daily_features}。

    输入行格式：(ts, metric, value)。口径：降水全天累计；
    云量/湿度/风速/能见度仅取 08:00-18:00 白天数据。
    """
    days = {}
    for ts, metric, value in observations:
        date_key = ts.strftime("%Y-%m-%d")
        day = days.setdefault(date_key, {"cloud": [], "precip_sum": 0.0,
                                        "humidity": [], "wind": [], "visibility": []})
        daytime = 8 <= ts.hour <= 18
        if metric == _PRECIPITATION:
            day["precip_sum"] += value
        elif daytime and metric == "cloud_cover_pct":
            day["cloud"].append(value)
        elif daytime and metric == "humidity_pct":
            day["humidity"].append(value)
        elif daytime and metric == "wind_kmh":
            day["wind"].append(value)
        elif daytime and metric == _VISIBILITY:
            day["visibility"].append(value)

    return {
        date_key: {
            "cloud_mean": sum(day["cloud"]) / len(day["cloud"]),
            "precip_sum": round(day["precip_sum"], 2),
            "humidity_mean": (sum(day["humidity"]) / len(day["humidity"])
                              if day["humidity"] else 50.0),
            "wind_max": max(day["wind"]) if day["wind"] else 0.0,
            "vis_median": (median(day["visibility"])
                           if len(day["visibility"]) >= _MIN_VIS_HOURS else None),
        }
        for date_key, day in days.items()
        if day["cloud"]
    }
