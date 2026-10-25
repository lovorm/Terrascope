# -*- coding: utf-8 -*-
"""Pydantic 响应模型：所有对外数据必带溯源字段。"""
from datetime import datetime

from pydantic import BaseModel


class SourceOut(BaseModel):
    key: str
    name: str
    provider: str
    license: str
    update_freq: str
    homepage: str
    pipeline_ready: bool
    note: str
    rows: int = 0
    last_data_at: datetime | None = None


class ObsOut(BaseModel):
    site: str
    metric: str
    ts: datetime
    value: float
    unit: str
    source_key: str
    fetched_at: datetime


class MountainIndexOut(BaseModel):
    date: str
    index: float
    version: str = "rule-v0"
    note: str = "P0 规则版；P1 替换为回测模型（目标准确率≥75%，如实公布）"


class DeviceRegisterIn(BaseModel):
    device_id: str
    name: str = ""
    key: str


class DeviceObsIn(BaseModel):
    """ESP32 统一 JSON 上报契约：预留协议，云端零修改。"""
    metric: str
    value: float
    unit: str = ""
    ts: datetime | None = None  # 缺省用服务器时间
