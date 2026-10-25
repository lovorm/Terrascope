# -*- coding: utf-8 -*-
"""采集调度：数据源注册 + 降频控制 + 标准化入库。
本地运行：python -m app.ingest
线上触发：POST /api/admin/ingest（GitHub Actions 定时 curl，见 workflows/ingest.yml）"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import MIN_INTERVAL_MIN, SITES
from .models import IngestLog, Observation, Source, utcnow
from .services import cnemc, open_meteo, qweather

log = logging.getLogger("ingest")

# 9 类免费公开数据源注册表（与申报书「数据合规与来源声明」章一致）
SOURCES = [
    ("open-meteo", "逐时温湿度/云量/降水历史与预报", "Open-Meteo（免费无密钥）", "CC-BY 4.0", "逐时", "https://open-meteo.com", True),
    ("qweather", "实时天气/预报/能见度", "和风天气免费订阅", "免费开发者额度", "逐时", "https://dev.qweather.com", True),
    ("cnemc-air", "空气质量 AQI/PM2.5", "生态环境部全国城市空气质量实时发布平台", "公开发布", "逐时", "https://air.cnemc.cn:18007", False),
    ("sentinel-landsat", "卫星遥感时序（NDSI冰川/NDWI水域）", "Copernicus Sentinel-2 / Landsat", "免费开放", "过境重访", "https://dataspace.copernicus.eu", False),
    ("srtm-dem", "30m 高程 DEM", "NASA SRTM", "免费开放", "静态", "https://earthdata.nasa.gov", False),
    ("base-map", "合规底图", "天地图/高德开放平台免费额度", "免费开发者额度", "—", "https://www.tianditu.gov.cn", False),
    ("authority-refs", "权威对照（冰川站/湿地年报）", "中科院玉龙雪山冰川站、拉市海湿地公开年报", "公开摘要", "年", "—", False),
    ("biodiversity", "越冬水鸟统计", "保护区公开监测统计", "公开数据", "季", "—", False),
    ("tourism-macro", "文旅宏观（游客量/生态负荷）", "丽江统计公报、文旅局公开数据", "公开数据", "年", "—", False),
]


def ensure_sources(db: Session):
    for key, name, provider, license_, freq, url, ready in SOURCES:
        row = db.scalar(select(Source).where(Source.key == key))
        if row is None:
            db.add(Source(key=key, name=name, provider=provider, license=license_,
                          update_freq=freq, homepage=url, pipeline_ready=ready,
                          note="逐条标注来源/更新时间/频率" if ready else "P0 已注册，P1 接入管道"))
    db.commit()


def _allowed(db: Session, key: str) -> bool:
    """降频控制：距上次成功采集不足 MIN_INTERVAL_MIN 则跳过（防免费额度超限）。"""
    last = db.scalar(select(IngestLog).where(
        IngestLog.source_key == key, IngestLog.ok.is_(True))
        .order_by(IngestLog.started_at.desc()).limit(1))
    if last and (utcnow() - last.started_at) < timedelta(minutes=MIN_INTERVAL_MIN.get(key, 60)):
        return False
    return True


def _save(db: Session, source_key: str, site: str, rows: list) -> int:
    n = 0
    for r in rows:
        ts = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M") if "T" in r["ts"] \
            else datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        exists = db.scalar(select(Observation).where(
            Observation.source_key == source_key, Observation.site == site,
            Observation.metric == r["metric"], Observation.ts == ts))
        if not exists:
            db.add(Observation(source_key=source_key, site=site, metric=r["metric"],
                               ts=ts, value=r["value"], unit=r.get("unit", "")))
            n += 1
    db.commit()
    return n


def _log(db: Session, key: str, ok: bool, rows: int, msg: str):
    db.add(IngestLog(source_key=key, ok=ok, rows=rows, message=msg[:500]))
    db.commit()
    log.info("[%s] ok=%s rows=%s %s", key, ok, rows, msg)


def ingest_open_meteo(db: Session, history_days: int = 7):
    """天源主管道：历史 7 天（增量）+ 未来 3 天预报，两个定点坐标。"""
    if not _allowed(db, "open-meteo"):
        return {"source": "open-meteo", "skipped": True, "reason": "降频窗口内"}
    total = 0
    try:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=history_days)
        for site_key, site in SITES.items():
            total += _save(db, "open-meteo", site_key,
                           open_meteo.fetch_archive(site, start.isoformat(), end.isoformat()))
            total += _save(db, "open-meteo", site_key,
                           open_meteo.fetch_forecast(site, days=3))
        _log(db, "open-meteo", True, total, "history+forecast")
        return {"source": "open-meteo", "rows": total}
    except Exception as e:  # 单源失败不影响其他源
        _log(db, "open-meteo", False, total, repr(e))
        return {"source": "open-meteo", "error": repr(e)}


def ingest_qweather(db: Session):
    if not _allowed(db, "qweather"):
        return {"source": "qweather", "skipped": True, "reason": "降频窗口内"}
    try:
        rows, msg = qweather.fetch_now()
        n = _save(db, "qweather", "lijiang", rows) if rows else 0
        _log(db, "qweather", rows is not None, n, msg)
        return {"source": "qweather", "rows": n, "note": msg}
    except Exception as e:
        _log(db, "qweather", False, 0, repr(e))
        return {"source": "qweather", "error": repr(e)}


def ingest_cnemc(db: Session):
    ok_flag, msg = False, ""
    try:
        cnemc.fetch_latest()
        ok_flag, msg = True, "unexpected success"
    except NotImplementedError as e:
        msg = str(e)
    except Exception as e:
        msg = repr(e)
    _log(db, "cnemc-air", ok_flag, 0, msg)
    return {"source": "cnemc-air", "note": msg}


def run_all(db: Session) -> dict:
    ensure_sources(db)
    return {
        "run_at": utcnow().isoformat(),
        "results": [ingest_open_meteo(db), ingest_qweather(db), ingest_cnemc(db)],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from .db import SessionLocal
    with SessionLocal() as s:
        import json
        print(json.dumps(run_all(s), ensure_ascii=False, indent=2, default=str))
