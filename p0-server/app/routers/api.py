# -*- coding: utf-8 -*-
"""对外 API：仪表盘 / 数据源溯源 / 设备协议 / 管理触发。"""
import hashlib
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ingest
from ..config import ADMIN_TOKEN, DEVICE_KEY_HEADER
from ..db import get_db
from ..models import Device, DeviceObservation, IngestLog, Observation, Source, Stay, utcnow
from ..p1 import mountain_model
from ..p1.aggregation import aggregate_daily_observations
from ..schemas import DeviceObsIn, DeviceRegisterIn
from ..services import open_meteo as open_meteo_svc

# ── 数据看板 ──────────────────────────────────────────────
dashboard = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@dashboard.get("/mountain-index")
def mountain_index(db: Session = Depends(get_db)):
    """观山指数（未来 3 天）：模型版（P1 回测模型）优先，规则版兜底；数据逐条可溯源。"""
    query = select(Observation).where(
        Observation.source_key == "open-meteo",
        Observation.metric.in_(["cloud_cover_pct", "precipitation_mm",
                                "humidity_pct", "wind_kmh"]),
        Observation.site == "yulong_snow")
    window_start = utcnow() - timedelta(days=7)
    rows = db.scalars(query.where(Observation.ts >= window_start)
                      .order_by(Observation.ts)).all()
    note = None
    if not rows:
        rows = db.scalars(query.order_by(Observation.ts)).all()
        note = ("最近 7 天无观测数据，已回退使用全表最近记录；"
                "请检查采集管道是否停跑")

    # 与训练同口径聚合：降水全天累计，其余指标取白天（08-18时）
    clean = aggregate_daily_observations((o.ts, o.metric, o.value) for o in rows)

    source = {"key": "open-meteo", "provider": "Open-Meteo（免费无密钥）",
              "update_freq": "逐时", "homepage": "https://open-meteo.com"}
    clf, meta = mountain_model.load_model()
    if clf and clean:
        recent_days = sorted(clean)[-3:]
        items = mountain_model.predict({d: clean[d] for d in recent_days})
        response = {"site": "yulong_snow", "items": items, "version": meta["version"],
                    "model_meta": {k: meta.get(k) for k in
                                  ("accuracy", "positive_rate", "window", "label_rule", "trained_at")},
                    "source": source}
        if note:
            response["note"] = note
        return response

    # 规则版兜底（无模型文件时）
    obs = [{"ts": o.ts.strftime("%Y-%m-%dT%H:%M"), "metric": o.metric, "value": o.value} for o in rows]
    out = []
    for d in sorted(clean)[-3:]:
        idx = open_meteo_svc.mountain_index_rule(obs, d)
        if idx is not None:
            out.append({"date": d, "index": idx, "version": "rule-v0",
                        "note": "P0 规则版；训练模型后自动切换 lr-v1"})
    response = {"site": "yulong_snow", "items": out, "version": "rule-v0", "source": source}
    if note:
        response["note"] = note
    return response


@dashboard.get("/latest")
def latest(metric: str, site: str = "yulong_snow", limit: int = 48,
           db: Session = Depends(get_db)):
    rows = db.scalars(select(Observation).where(
        Observation.metric == metric, Observation.site == site)
        .order_by(Observation.ts.desc()).limit(min(limit, 720))).all()
    return [{"metric": r.metric, "ts": r.ts, "value": r.value, "unit": r.unit,
             "source_key": r.source_key, "fetched_at": r.fetched_at} for r in rows]


# ── 数据源溯源 ────────────────────────────────────────────
sources = APIRouter(prefix="/api/sources", tags=["sources"])


@sources.get("")
def list_sources(db: Session = Depends(get_db)):
    ingest.ensure_sources(db)
    out = []
    for s in db.scalars(select(Source)).all():
        last = db.scalar(select(func.max(Observation.ts)).where(Observation.source_key == s.key))
        out.append({"key": s.key, "name": s.name, "provider": s.provider,
                    "license": s.license, "update_freq": s.update_freq,
                    "homepage": s.homepage, "pipeline_ready": s.pipeline_ready,
                    "note": s.note, "rows": db.scalar(select(func.count()).where(
                        Observation.source_key == s.key)) or 0,
                    "last_data_at": last})
    return out


# ── 人源·民宿名录（脱敏只读） ─────────────────────────────
stays = APIRouter(prefix="/api/stays", tags=["stays"])


@stays.get("")
def list_stays(village: str = "", db: Session = Depends(get_db)):
    """对外只读：仅 public=1（已授权）记录；输出不含联系方式/授权编号/内部备注。"""
    q = select(Stay).where(Stay.public == 1)
    if village:
        q = q.where(Stay.village == village)
    rows = db.scalars(q.order_by(Stay.stay_id)).all()
    return [{"stay_id": r.stay_id, "village": r.village, "stay_name": r.stay_name,
             "rooms_total": r.rooms_total, "price_band": r.price_band,
             "eco_features": r.eco_features, "culture_features": r.culture_features,
             "source": r.source, "collected_at": r.collected_at,
             "updated_freq": r.updated_freq} for r in rows]


# ── ESP32 预留协议（物源·增量拓展，云端零修改） ───────────
devices = APIRouter(prefix="/api/devices", tags=["devices"])


@devices.post("/register")
def register(payload: DeviceRegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(Device).where(Device.device_id == payload.device_id)):
        raise HTTPException(409, "device_id 已注册")
    db.add(Device(device_id=payload.device_id, name=payload.name,
                  key_hash=hashlib.sha256(payload.key.encode()).hexdigest()))
    db.commit()
    return {"ok": True, "protocol": "统一 JSON 上报：POST /api/devices/{device_id}/observations，"
                                     "请求头 X-Device-Key；OTA：GET /api/devices/{device_id}/ota"}


def _auth_device(device_id: str, key: str, db: Session) -> Device:
    dev = db.scalar(select(Device).where(Device.device_id == device_id))
    if not dev or dev.key_hash != hashlib.sha256((key or "").encode()).hexdigest():
        raise HTTPException(401, "设备认证失败")
    return dev


@devices.post("/{device_id}/observations")
def report(device_id: str, payload: list[DeviceObsIn],
           x_device_key: str = Header(default=""),
           db: Session = Depends(get_db)):
    dev = _auth_device(device_id, x_device_key, db)
    for item in payload:
        db.add(DeviceObservation(device_id=device_id, metric=item.metric,
                                 ts=item.ts or utcnow(), value=item.value, unit=item.unit))
    dev.last_seen = utcnow()
    db.commit()
    return {"ok": True, "received": len(payload)}


@devices.get("/{device_id}/ota")
def ota(device_id: str, x_device_key: str = Header(default=""),
        db: Session = Depends(get_db)):
    _auth_device(device_id, x_device_key, db)
    # P2 提供固件包分发；P0 先返回版本契约
    return {"latest_firmware": "v0.1.0", "url": None,
            "note": "OTA 分发 P2 上线；当前仅版本协商，接口不变"}


@devices.get("/{device_id}/latest")
def device_latest(device_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(DeviceObservation).where(
        DeviceObservation.device_id == device_id)
        .order_by(DeviceObservation.ts.desc()).limit(50)).all()
    return [{"metric": r.metric, "ts": r.ts, "value": r.value, "unit": r.unit} for r in rows]


# ── 管理触发（GitHub Actions 定时 curl） ──────────────────
admin = APIRouter(prefix="/api/admin", tags=["admin"])


@admin.post("/ingest")
def trigger_ingest(x_admin_token: str = Header(default=""),
                   db: Session = Depends(get_db)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "admin token 校验失败")
    return ingest.run_all(db)


@admin.post("/train-mountain-index")
def train_mountain(days: int = 365, threshold_m: int = 15000,
                   x_admin_token: str = Header(default="")):
    """P1：用 Open-Meteo 历史回测训练观山指数模型，指标如实写入元数据。"""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "admin token 校验失败")
    return mountain_model.train(days=days, threshold_m=threshold_m)


@admin.get("/logs")
def ingest_logs(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.scalars(select(IngestLog).order_by(IngestLog.started_at.desc())
                      .limit(min(limit, 200))).all()
    return [{"source_key": r.source_key, "started_at": r.started_at,
             "ok": r.ok, "rows": r.rows, "message": r.message} for r in rows]
