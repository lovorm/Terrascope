# -*- coding: utf-8 -*-
"""观山模型聚合口径测试（合成数据，不访问外部网络）。"""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.db import Base, get_db
from app.main import app
from app.models import Observation, utcnow
from app.p1.aggregation import aggregate_daily_observations
from app.p1.mountain_model import daily_features

client = TestClient(app)


def test_precipitation_accumulates_all_day():
    """合成数据：白天与夜间降水都进入全天累计。"""
    day = datetime(2026, 1, 15)
    features = aggregate_daily_observations([
        (day.replace(hour=8), "precipitation_mm", 1.0),
        (day.replace(hour=20), "precipitation_mm", 5.0),
        (day.replace(hour=9), "cloud_cover_pct", 40.0),
    ])
    assert features["2026-01-15"]["precip_sum"] == 6.0


def test_training_and_api_share_daily_features(tmp_path, monkeypatch):
    """合成数据：训练入口与线上 DB 入口产出同一份日特征。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.p1 import mountain_model

    date = (utcnow() - timedelta(days=1)).date()
    hourly = {"time": [], "cloud_cover": [], "relative_humidity_2m": [],
              "wind_speed_10m": [], "precipitation": []}
    rows = []
    for hour in range(24):
        ts = datetime.combine(date, datetime.min.time()).replace(hour=hour)
        values = {"cloud_cover": 40.0 if hour == 9 else None,
                  "relative_humidity_2m": 60.0 if hour == 10 else None,
                  "wind_speed_10m": 5.0 if hour == 11 else None,
                  "precipitation": 1.0 if hour == 8 else (5.0 if hour == 20 else None)}
        timestamp = ts.isoformat()
        hourly["time"].append(timestamp)
        for key, value in values.items():
            hourly[key].append(value)
            if value is not None:
                metric = {"cloud_cover": "cloud_cover_pct",
                          "relative_humidity_2m": "humidity_pct",
                          "wind_speed_10m": "wind_kmh",
                          "precipitation": "precipitation_mm"}[key]
                rows.append(Observation(source_key="open-meteo", site="yulong_snow",
                                        metric=metric, ts=ts, value=value, unit="synthetic"))

    expected = daily_features(hourly)
    assert expected[date.isoformat()]["precip_sum"] == 6.0

    test_engine = create_engine(f"sqlite:///{tmp_path / 'aggregation.db'}", future=True)
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine)
    with TestSession() as db:
        db.add_all(rows)
        db.commit()

    captured = {}

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    def fake_load_model():
        return object(), {"version": "lr-test", "accuracy": 0.8, "positive_rate": 0.5,
                          "window": "synthetic", "label_rule": "synthetic",
                          "trained_at": "2026-01-15"}

    def fake_predict(feats):
        captured.update(feats)
        return [{"date": d, "index": 50.0} for d in sorted(feats)[-3:]]

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(mountain_model, "load_model", fake_load_model)
    monkeypatch.setattr(mountain_model, "predict", fake_predict)
    try:
        response = client.get("/api/dashboard/mountain-index")
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()

    assert response.status_code == 200
    assert captured == expected
