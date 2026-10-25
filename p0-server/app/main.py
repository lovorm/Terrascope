# -*- coding: utf-8 -*-
"""「见山Terrascope」数字底座 API —— P0 骨架。
启动：uvicorn app.main:app --reload   文档：http://127.0.0.1:8000/docs"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine
from .ingest import ensure_sources
from .routers.api import admin, dashboard, devices, sources, stays

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    from .db import SessionLocal
    with SessionLocal() as db:
        ensure_sources(db)
    yield


app = FastAPI(
    title="「见山Terrascope」数字底座 API",
    version="0.1.0",
    description="天-地-人-物四源融合 · 纯云端可独立落地 · 全部数据逐条可溯源 | "
                "P0：Open-Meteo/和风管道 + 降频缓存 + ESP32 预留协议 | "
                "P1：观山指数回测模型、卫星遥感时序、小程序 | P2：众包打卡、异常告警、OTA 分发",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(dashboard)
app.include_router(sources)
app.include_router(stays)
app.include_router(devices)
app.include_router(admin)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "project": "yunqi-naxi", "stage": "P0", "cost_per_year_cny": 300}
