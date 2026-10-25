# -*- coding: utf-8 -*-
"""数据库会话管理。SQLAlchemy 2.0，SQLite/PostgreSQL 双兼容。"""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

# SQLite 场景自动创建父目录，保证新环境克隆后可直接运行
if DATABASE_URL.startswith("sqlite"):
    _db_file = DATABASE_URL.split("sqlite:///", 1)[-1]
    Path(_db_file).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
