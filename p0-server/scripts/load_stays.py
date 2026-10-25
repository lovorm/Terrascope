# -*- coding: utf-8 -*-
"""民宿数据入库脚本：采集表 CSV -> 校验 -> 脱敏红线检查 -> SQLite 幂等入库。

依据《03_民宿数据/民宿数据规范.md》。仅用标准库，任何环境可直接运行：
    python scripts/load_stays.py --csv <采集表.csv> [--db <yunqi.db>] [--dry-run]

红线（规范第二节）：
  1. 任一字段出现疑似手机号/连续 7 位以上数字 → 整行拒绝（明文联系方式永不入库）
  2. contact_ref 若填写必须为授权编号格式 AUTH-YYYY-NNN
  3. consent 为"未联系"的记录 public=0，不进入对外展示
"""
import argparse
import csv
import hashlib
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PHONE_RE = re.compile(r"1[3-9]\d{9}")
LONG_DIGITS_RE = re.compile(r"\d{7,}")
AUTH_RE = re.compile(r"^AUTH-\d{4}-\d{3}$")
STAY_ID_RE = re.compile(r"^YQ-[A-Z0-9]{2,6}-\d{3}$")

FIELDS = ["stay_id", "village", "stay_name", "rooms_total", "price_band",
          "eco_features", "culture_features", "source", "collected_at",
          "updated_freq", "consent", "contact_ref", "notes"]
REQUIRED = ["stay_id", "village", "stay_name", "rooms_total", "source",
            "collected_at", "updated_freq", "consent"]
ENUMS = {
    "price_band": {"<150", "150-300", "300-500", ">500", ""},
    "source": {"实地调研", "业主自报", "村委提供", "公开平台"},
    "updated_freq": {"一次性", "学期更新", "月更新"},
    "consent": {"书面同意", "口头同意", "未联系"},
}
PUBLIC_CONSENT = {"书面同意", "口头同意"}

DDL = """CREATE TABLE IF NOT EXISTS stays(
 stay_id TEXT PRIMARY KEY, village TEXT, stay_name TEXT, rooms_total INTEGER,
 price_band TEXT, eco_features TEXT, culture_features TEXT, source TEXT,
 collected_at TEXT, updated_freq TEXT, consent TEXT, contact_ref TEXT,
 notes TEXT, public INTEGER NOT NULL, row_hash TEXT NOT NULL, loaded_at TEXT NOT NULL)"""


def validate(row: dict) -> list:
    """返回错误列表；空列表 = 通过。"""
    errs = []
    sid = row.get("stay_id", "")
    for f in REQUIRED:
        if not (row.get(f) or "").strip():
            errs.append(f"必填字段缺失: {f}")
    if sid and not STAY_ID_RE.match(sid):
        errs.append(f"stay_id 格式非法: {sid}（应为 YQ-村落-编号）")
    try:
        if not int(row.get("rooms_total", "0")) > 0:
            errs.append("rooms_total 须为正整数")
    except ValueError:
        errs.append("rooms_total 非整数")
    for f, allowed in ENUMS.items():
        v = (row.get(f) or "").strip()
        if v and v not in allowed:
            errs.append(f"{f} 值非法: {v}")
    try:
        datetime.strptime(row.get("collected_at", ""), "%Y-%m-%d")
    except ValueError:
        errs.append("collected_at 须为 YYYY-MM-DD 日期")
    ref = (row.get("contact_ref") or "").strip()
    if ref and not AUTH_RE.match(ref):
        errs.append(f"contact_ref 须为授权编号 AUTH-YYYY-NNN，不得存明文: {ref}")
    for f in FIELDS:  # 脱敏红线：全字段扫描
        v = row.get(f) or ""
        if PHONE_RE.search(v):
            errs.append(f"疑似明文手机号（字段 {f}），整行拒绝")
        elif LONG_DIGITS_RE.search(v):
            errs.append(f"疑似敏感长数字串（字段 {f}），整行拒绝")
    return errs


def row_hash(row: dict) -> str:
    canon = "\x1f".join((row.get(f) or "").strip() for f in FIELDS)
    return hashlib.sha256(canon.encode()).hexdigest()


def load(csv_path: str, db_path: str, dry: bool):
    rows, errs_out = [], []
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        for i, raw in enumerate(csv.DictReader(fh), start=2):  # 行1为表头
            row = {k: (raw.get(k) or "").strip() for k in FIELDS}
            if not any(row.values()):
                continue
            errs = validate(row)
            rows.append((i, row, errs))
            errs_out += [f"  [拒绝] 行{i} {row['stay_id'] or '?'}: {e}" for e in errs]
    ok = [(i, r) for i, r, e in rows if not e]
    print(f"入库汇总: 读入 {len(rows)} 行 | 通过 {len(ok)} | 拒绝 {len(rows) - len(ok)}")
    for line in errs_out:
        print(line)
    if dry or not ok:
        return 0 if ok else 1
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute(DDL)
    now = datetime.now().isoformat(timespec="seconds")
    ins = upd = skip = 0
    for _, r in ok:
        h = row_hash(r)
        cur = con.execute("SELECT row_hash FROM stays WHERE stay_id=?", (r["stay_id"],)).fetchone()
        if cur and cur[0] == h:
            skip += 1
            continue
        vals = [r["stay_id"], r["village"], r["stay_name"], int(r["rooms_total"]),
                r["price_band"], r["eco_features"], r["culture_features"], r["source"],
                r["collected_at"], r["updated_freq"], r["consent"], r["contact_ref"],
                r["notes"], int(r["consent"] in PUBLIC_CONSENT), h, now]
        if cur:
            con.execute("UPDATE stays SET village=?,stay_name=?,rooms_total=?,price_band=?,"
                        "eco_features=?,culture_features=?,source=?,collected_at=?,updated_freq=?,"
                        "consent=?,contact_ref=?,notes=?,public=?,row_hash=?,loaded_at=? WHERE stay_id=?",
                        vals[1:] + [r["stay_id"]])
            upd += 1
        else:
            con.execute("INSERT INTO stays VALUES(" + ",".join("?" * 16) + ")", vals)
            ins += 1
    con.commit()
    pub, tot = con.execute("SELECT SUM(public),COUNT(*) FROM stays").fetchone()
    con.close()
    print(f"写入: 新增 {ins} | 更新 {upd} | 未变跳过 {skip}")
    print(f"入库后: 总 {tot} 条 | 对外展示 {pub} 条 | 仅内部 {tot - pub} 条  (db: {db_path})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="民宿数据采集表入库（校验+脱敏+幂等）")
    ap.add_argument("--csv", required=True, help="采集表 CSV 路径")
    ap.add_argument("--db", default=str(Path(__file__).resolve().parent.parent / "data" / "yunqi.db"))
    ap.add_argument("--dry-run", action="store_true", help="只校验不入库")
    a = ap.parse_args()
    sys.exit(load(a.csv, a.db, a.dry_run))
