# -*- coding: utf-8 -*-
"""数据模型：数据源注册表（溯源）、观测数据、采集日志、ESP32 设备与上报。"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow():
    """统一存 naive UTC（SQLite 无时区），避免 naive/aware 混算报错。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Source(Base):
    """数据源注册表：9 类免费公开数据源，全站溯源的元数据底座。"""
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(120))
    license: Mapped[str] = mapped_column(String(120))
    update_freq: Mapped[str] = mapped_column(String(40))
    homepage: Mapped[str] = mapped_column(Text, default="")
    pipeline_ready: Mapped[bool] = mapped_column(Boolean, default=False)  # P0 仅前3类接管道
    note: Mapped[str] = mapped_column(Text, default="")


class Observation(Base):
    """平台观测数据：每条必带 source_key + fetched_at，实现逐条可溯源。"""
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("source_key", "site", "metric", "ts", name="uq_obs"),
        Index("ix_obs_query", "source_key", "metric", "ts"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(40), index=True)
    site: Mapped[str] = mapped_column(String(40), default="")   # yulong_snow / lashi_lake
    metric: Mapped[str] = mapped_column(String(60))             # temperature_c / humidity / cloud_cover_pct ...
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # 数据所属时间
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IngestLog(Base):
    """采集日志：降频判断 + 排障监控。"""
    __tablename__ = "ingest_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")


class Device(Base):
    """物源（增量拓展）设备注册表：ESP32 即插即用，云端零修改。"""
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    key_hash: Mapped[str] = mapped_column(String(64))           # sha256(上报密钥)
    firmware: Mapped[str] = mapped_column(String(32), default="unknown")
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class DeviceObservation(Base):
    __tablename__ = "device_observations"
    __table_args__ = (Index("ix_devobs", "device_id", "metric", "ts"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(60))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), default="")


class Stay(Base):
    """人源·民宿名录：由 scripts/load_stays.py 校验入库；public=0 仅内部统计。
    脱敏红线：contact_ref 仅授权编号、notes 内部备注——二者永不出对外接口。"""
    __tablename__ = "stays"
    stay_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    village: Mapped[str] = mapped_column(String(64))
    stay_name: Mapped[str] = mapped_column(String(128))
    rooms_total: Mapped[int] = mapped_column(Integer)
    price_band: Mapped[str] = mapped_column(String(16), default="")
    eco_features: Mapped[str] = mapped_column(String(255), default="")
    culture_features: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(32))
    collected_at: Mapped[str] = mapped_column(String(10))
    updated_freq: Mapped[str] = mapped_column(String(16))
    consent: Mapped[str] = mapped_column(String(16))
    contact_ref: Mapped[str] = mapped_column(String(32), default="")
    notes: Mapped[str] = mapped_column(String(255), default="")
    public: Mapped[int] = mapped_column(Integer)      # 1=已授权可对外展示
    row_hash: Mapped[str] = mapped_column(String(64))  # 幂等：内容哈希，未变跳过
    loaded_at: Mapped[str] = mapped_column(String(20))
