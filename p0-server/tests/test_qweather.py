# -*- coding: utf-8 -*-
"""和风天气解析离线测试（合成数据，不访问外部网络）。"""
from app.services import qweather


def test_parse_now_converts_visibility_km_to_m():
    """合成响应：和风 vis 单位为 km，标准化观测必须转换为 m。"""
    now = {"obsTime": "2026-10-25T10:30+08:00", "temp": "12.3",
           "humidity": "45", "vis": "10", "pressure": "1010"}
    rows = qweather._parse_now(now)
    by_metric = {row["metric"]: row for row in rows}
    assert by_metric["visibility_m"]["value"] == 10000.0
    assert by_metric["visibility_m"]["unit"] == "m"
    assert by_metric["temperature_c"]["value"] == 12.3
    assert by_metric["humidity_pct"]["value"] == 45.0
    assert by_metric["pressure_hpa"]["value"] == 1010.0


def test_fetch_now_skips_without_key(monkeypatch):
    """无 Key 时保持优雅跳过，不发起网络请求。"""
    monkeypatch.setattr(qweather, "QWEATHER_API_KEY", "")
    assert qweather.fetch_now() == (
        None, "QWEATHER_API_KEY 未配置，已跳过（和风天气免费订阅 dev.qweather.com）"
    )
