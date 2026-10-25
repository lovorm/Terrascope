# -*- coding: utf-8 -*-
"""冒烟测试：真实调用 Open-Meteo（免费无密钥）+ 全接口契约。
运行：pytest tests/ -v"""
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.ingest import ingest_open_meteo
from app.main import app

Base.metadata.create_all(engine)  # 保证无 lifespan 场景下表已建
client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_sources_registry():
    r = client.get("/api/sources")
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert {"open-meteo", "qweather", "cnemc-air", "sentinel-landsat"} <= keys


def test_real_ingest_open_meteo():
    """真实抓取丽江两坐标（免费无密钥），验证管道与溯源字段。"""
    from sqlalchemy import delete
    from app.models import IngestLog, Observation
    with SessionLocal() as db:
        db.execute(delete(IngestLog).where(IngestLog.source_key == "open-meteo"))
        db.execute(delete(Observation).where(Observation.source_key == "open-meteo"))
        db.commit()  # 清空降频窗口与旧观测，保证测试确定性（生产由窗口+去重控制）
        res = ingest_open_meteo(db)
    assert "error" not in res, res
    assert res["rows"] > 0
    r = client.get("/api/dashboard/latest", params={"metric": "temperature_c", "site": "yulong_snow", "limit": 5})
    assert r.status_code == 200 and len(r.json()) > 0
    assert {"source_key", "fetched_at"} <= set(r.json()[0])  # 溯源字段齐备


def test_mountain_index():
    """观山指数契约：模型版（lr-v1）或规则版（rule-v0）都需结构合法、指数在 0-100。"""
    r = client.get("/api/dashboard/mountain-index")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] in ("lr-v1", "rule-v0")
    if body["version"] == "lr-v1":
        assert {"accuracy", "window", "label_rule"} <= set(body["model_meta"])
    for item in body["items"]:
        assert 0 <= item["index"] <= 100


def test_mountain_index_falls_back_when_seven_day_window_empty(tmp_path):
    """T-A1：管道停跑超 7 天时，接口回退全表并显式提示，而不是返回空列表。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base, get_db
    from app.models import Observation, utcnow

    fallback_engine = create_engine(f"sqlite:///{tmp_path / 'fallback.db'}", future=True)
    Base.metadata.create_all(fallback_engine)
    FallbackSession = sessionmaker(bind=fallback_engine)
    stale_ts = utcnow() - timedelta(days=10)
    with FallbackSession() as db:
        db.add_all([
            Observation(source_key="open-meteo", site="yulong_snow",
                        metric="cloud_cover_pct", ts=stale_ts.replace(hour=9),
                        value=30.0, unit="%"),
            Observation(source_key="open-meteo", site="yulong_snow",
                        metric="humidity_pct", ts=stale_ts.replace(hour=9),
                        value=60.0, unit="%"),
            Observation(source_key="open-meteo", site="yulong_snow",
                        metric="wind_kmh", ts=stale_ts.replace(hour=9),
                        value=5.0, unit="km/h"),
        ])
        db.commit()

    def override_get_db():
        db = FallbackSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        r = client.get("/api/dashboard/mountain-index")
    finally:
        app.dependency_overrides.pop(get_db, None)
        fallback_engine.dispose()

    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) > 0
    assert "最近 7 天无观测数据" in body["note"]
    assert "回退使用全表最近记录" in body["note"]


def test_device_protocol():
    """ESP32 预留协议全流程：注册 → 上报 → 查询 → OTA 协商。"""
    import uuid
    did = "esp32-" + uuid.uuid4().hex[:8]  # 每次运行唯一，库可复用
    key = "secret-key-123"
    r = client.post("/api/devices/register",
                    json={"device_id": did, "name": "民宿A-室外", "key": key})
    assert r.status_code == 200
    assert client.post("/api/devices/register",
                       json={"device_id": did, "key": "x"}).status_code == 409  # 重复注册
    ts = (datetime.now(timezone.utc) + timedelta(minutes=-1)).isoformat()
    r = client.post(f"/api/devices/{did}/observations",
                    headers={"X-Device-Key": key},
                    json=[{"metric": "co2_ppm", "value": 652, "unit": "ppm", "ts": ts},
                          {"metric": "temp_c", "value": 15.8, "unit": "°C", "ts": ts}])
    assert r.status_code == 200 and r.json()["received"] == 2
    assert client.post(f"/api/devices/{did}/observations", headers={"X-Device-Key": "wrong"},
                       json=[{"metric": "t", "value": 1}]).status_code == 401  # 认证失败
    r = client.get(f"/api/devices/{did}/latest")
    assert r.status_code == 200 and r.json()[0]["metric"] in ("co2_ppm", "temp_c")
    r = client.get(f"/api/devices/{did}/ota", headers={"X-Device-Key": key})
    assert r.status_code == 200 and r.json()["latest_firmware"] == "v0.1.0"


def test_stays_public_only():
    """民宿名录脱敏契约：仅 public=1 对外；响应永不包含联系方式/授权编号/内部备注。"""
    from app.models import Stay

    def _stay(sid, name, consent, pub, notes=""):
        return Stay(stay_id=sid, village="测试村", stay_name=name, rooms_total=5,
                    price_band="150-300", eco_features="太阳能热水", culture_features="",
                    source="实地调研", collected_at="2026-09-20", updated_freq="学期更新",
                    consent=consent, contact_ref="", notes=notes,
                    public=pub, row_hash="hash-" + sid, loaded_at="2026-09-20")

    with SessionLocal() as db:
        db.merge(_stay("YQ-TST-901", "授权民宿", "口头同意", 1))
        db.merge(_stay("YQ-TST-902", "未授权民宿", "未联系", 0, notes="内部备注-勿外泄"))
        db.commit()
    r = client.get("/api/stays")
    assert r.status_code == 200
    items = r.json()
    ids = {s["stay_id"] for s in items}
    assert "YQ-TST-901" in ids and "YQ-TST-902" not in ids          # 未授权不出现
    banned = {"contact_ref", "notes", "consent", "row_hash", "loaded_at"}
    assert banned.isdisjoint(set(items[0]))                          # 脱敏字段永不外泄
    r = client.get("/api/stays", params={"village": "测试村"})
    assert r.status_code == 200 and all(s["village"] == "测试村" for s in r.json())
