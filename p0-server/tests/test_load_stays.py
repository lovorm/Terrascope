# -*- coding: utf-8 -*-
"""load_stays.py 行为测试：脱敏红线 / 枚举校验 / 幂等重跑 / 变更更新。
运行：pytest tests/test_load_stays.py -v（纯标准库，无网络依赖）"""
import csv
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "load_stays.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stays_fixture.csv"


def run(csv_path, db_path, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--csv", str(csv_path), "--db", str(db_path), *extra],
                          capture_output=True, text=True)


def test_reject_and_accept(tmp_path):
    """红线：手机号行整行拒绝、明文永不入库；枚举非法拒绝；合规行正常入库。"""
    r = run(FIXTURE, tmp_path / "t.db")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "通过 2" in out and "拒绝 2" in out
    assert "疑似明文手机号" in out and "source 值非法: 网购" in out
    assert "总 2 条 | 对外展示 1 条 | 仅内部 1 条" in out  # 未联系 → 不展示
    con = sqlite3.connect(tmp_path / "t.db")
    rows = con.execute("SELECT stay_id, consent, contact_ref, public FROM stays ORDER BY stay_id").fetchall()
    con.close()
    assert rows == [("YQ-BS-002", "未联系", "", 0), ("YQ-LSH-001", "书面同意", "AUTH-2026-001", 1)]
    assert all(not str(r[2]).startswith("1") or len(str(r[2])) < 11 for r in rows)  # 无明文手机号


def test_idempotent_rerun(tmp_path):
    """同批数据重复提交 → 全部未变跳过，不产生重复行。"""
    db = tmp_path / "t.db"
    run(FIXTURE, db)
    r2 = run(FIXTURE, db)
    assert "新增 0 | 更新 0 | 未变跳过 2" in r2.stdout
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM stays").fetchone()[0] == 2
    con.close()


def test_update_on_change(tmp_path):
    """同 stay_id 数据变更 → UPDATE 而非新增。"""
    db = tmp_path / "t.db"
    run(FIXTURE, db)
    rows = list(csv.DictReader(open(FIXTURE, encoding="utf-8")))
    rows[0]["rooms_total"] = "9"
    v2 = tmp_path / "v2.csv"
    with open(v2, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    r = run(v2, db)
    assert "更新 1" in r.stdout and "新增 0" in r.stdout
    con = sqlite3.connect(db)
    assert con.execute("SELECT rooms_total FROM stays WHERE stay_id='YQ-LSH-001'").fetchone()[0] == 9
    con.close()


def test_dry_run_no_db(tmp_path):
    """--dry-run 只校验，不产生数据库文件。"""
    r = run(FIXTURE, tmp_path / "none.db", "--dry-run")
    assert r.returncode == 0 and "入库后" not in r.stdout
    assert not (tmp_path / "none.db").exists()
