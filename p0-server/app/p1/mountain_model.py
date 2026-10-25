# -*- coding: utf-8 -*-
"""P1 · 观山指数回测模型（轻量逻辑回归）。

口径与推算依据（对应申报书「补充数据目标推算依据」要求）：
- 真值标签：Open-Meteo 预报系统存档逐时能见度（免费无密钥，past_days 上限 92 天；
  归档接口实测不支持能见度变量、返回全 null，故标签窗口为近 92 天，扩大窗口列 P1.1）。
  当日 08:00–18:00（本地时）有效能见度小时数 ≥5 且中位数 ≥ threshold_m（默认 15000m）→ 标签 1「可观山」。
  依据：15km 能见度下玉龙雪山山体轮廓清晰；夜间云雾与游览无关，故取白天中位数、抗短时极值。
  阈值作为可调参数写入模型元数据，P2 上线游客众包打卡后用真实"是否看到雪山"交叉校准。
- 特征（与 P0 规则版同口径，预报数据同样具备）：白天云量均值 / 全天累计降水 /
  白天湿度均值 / 白天最大风速。
- 切分：按日期时序切分（前 80% 训练、后 20% 测试），不做随机切分，避免时间泄漏。
- 评估：测试集准确率 / 精确率 / 召回率 / 混淆矩阵，如实写入元数据并对外公布，不夸大。
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib

from ..config import SITES
from ..services import open_meteo
from .aggregation import aggregate_daily_observations

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "model"
MODEL_PATH = MODEL_DIR / "mountain_index_lr.joblib"
META_PATH = MODEL_DIR / "mountain_index_meta.json"
VERSION = "lr-v1"

FEATURES = ["cloud_mean", "precip_sum", "humidity_mean", "wind_max"]


def daily_features(hourly: dict) -> dict:
    """逐时数据 → {date: {features}}，训练与线上预测共用同一聚合口径。"""
    observations = []
    for i, t in enumerate(hourly["time"]):
        for metric, key in (("cloud_cover_pct", "cloud_cover"),
                            ("humidity_pct", "relative_humidity_2m"),
                            ("wind_kmh", "wind_speed_10m"),
                            ("visibility_m", "visibility"),
                            ("precipitation_mm", "precipitation")):
            value = hourly.get(key, [None] * len(hourly["time"]))[i]
            if value is not None:
                observations.append((datetime.fromisoformat(t), metric, float(value)))
    return aggregate_daily_observations(observations)


def fetch_history(site: dict, days: int) -> dict:
    """标签源：预报接口 past_days（能见度可得窗口，上限 92 天）。"""
    days = min(days, 92)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return open_meteo.fetch_past_hourly(site, start.isoformat(), end.isoformat())


def train(days: int = 92, threshold_m: int = 15000) -> dict:
    site = SITES["yulong_snow"]
    feats = daily_features(fetch_history(site, days))
    ds = sorted((d, f) for d, f in feats.items() if f["vis_median"] is not None)
    if len(ds) < 60:
        raise RuntimeError(f"有效样本不足（{len(ds)} 天），无法回测")

    X = [[f[k] for k in FEATURES] for _, f in ds]
    y = [1 if f["vis_median"] >= threshold_m else 0 for _, f in ds]

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix, precision_score, recall_score, accuracy_score
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    # Walk-forward 时序交叉验证：雨季正值率低且分布不均，单次切分测试窗可能无正样本，
    # 池化各折样本外预测再算指标，是小子样下最诚实的回测方式。
    n_splits = 5
    y_true_all, y_pred_all = [], []
    for tr_idx, te_idx in TimeSeriesSplit(n_splits=n_splits).split(X):
        if len(set(y[i] for i in tr_idx)) < 2:
            continue  # 训练折只有一类时跳过（无法拟合）
        clf = make_pipeline(StandardScaler(),
                            LogisticRegression(class_weight="balanced", max_iter=500))
        clf.fit([X[i] for i in tr_idx], [y[i] for i in tr_idx])
        y_true_all += [y[i] for i in te_idx]
        y_pred_all += clf.predict([X[i] for i in te_idx]).tolist()
    if not y_true_all:
        raise RuntimeError("交叉验证无有效折，回测失败")

    # 用全量数据重训最终模型（供线上预测）
    final = make_pipeline(StandardScaler(),
                          LogisticRegression(class_weight="balanced", max_iter=500))
    final.fit(X, y)

    report = {
        "version": VERSION,
        "trained_at": date.today().isoformat(),
        "site": site["name"],
        "n_days": len(ds),
        "window": f"{ds[0][0]} ~ {ds[-1][0]}",
        "evaluation": f"walk-forward TimeSeriesSplit({n_splits}) 池化样本外结果",
        "label_rule": f"08:00-18:00 能见度中位数 ≥ {threshold_m}m 记为可观山（1）",
        "threshold_m": threshold_m,
        "features": FEATURES,
        "data_source": "Open-Meteo 预报系统存档能见度（past_days 上限 92 天）",
        "sample_note": "窗口为近 3 个月，季节覆盖有限（雨季正值率低）；P1.1 接入 ERA5/CDS 能见度扩大样本，P2 用众包打卡校准",
        "n_oos": len(y_true_all),
        "positive_rate": round(sum(y) / len(y), 3),
        "accuracy": round(float(accuracy_score(y_true_all, y_pred_all)), 3),
        "precision": round(float(precision_score(y_true_all, y_pred_all, zero_division=0)), 3),
        "recall": round(float(recall_score(y_true_all, y_pred_all, zero_division=0)), 3),
        "confusion_matrix": confusion_matrix(y_true_all, y_pred_all, labels=[0, 1]).tolist(),
        "note": "回测基于数值预报存档能见度，非人工目击记录；上线后用 P2 众包打卡交叉校准",
    }
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, MODEL_PATH)
    META_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def load_model():
    if MODEL_PATH.exists() and META_PATH.exists():
        return joblib.load(MODEL_PATH), json.loads(META_PATH.read_text(encoding="utf-8"))
    return None, None


def predict(feats: dict) -> list:
    """feats: {date: feature_dict} → [{date, index}]，模型版输出（0-100）。"""
    clf, meta = load_model()
    if clf is None:
        return []
    ds = sorted(feats)
    X = [[feats[d][k] for k in FEATURES] for d in ds]
    prob = clf.predict_proba(X)[:, 1]
    return [{"date": d, "index": round(float(p) * 100, 1)} for d, p in zip(ds, prob)]
