# -*- coding: utf-8 -*-
"""地源数据服务：生态环境部全国城市空气质量实时发布平台（AQI/PM2.5）适配层。

P0 说明：该平台为网页发布、无官方开放 JSON 接口；本层预留统一返回结构，
P0 阶段数据可由人工摘录或和风空气 API（需免费订阅）补充，接口契约保持不变，
P1 替换实现时不改动上层代码（与预留 ESP32 协议同一设计原则）。"""

# 丽江市站点（生态环境部发布口径，站点编码以平台公布为准）
STATIONS = {"lijiang": "丽江市（点位以生态环境部平台为准）"}

CONTRACT = {
    "metric": ["aqi", "pm25_ugm3", "pm10_ugm3", "o3_ugm3"],
    "ts": "发布时间（逐时）",
    "source": "cnemc-air",
}


def fetch_latest(timeout=15):
    """P0 返回未实现标记；上层 ingest 捕获后写入 IngestLog，管道状态对外可见。"""
    raise NotImplementedError(
        "生态环境部平台无官方开放 API：P0 由人工摘录/和风空气API补充，P1 接入合规数据服务"
    )
