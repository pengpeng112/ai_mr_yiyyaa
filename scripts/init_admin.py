"""显式初始化首个管理员账号。

该脚本不会在应用启动或登录请求中自动创建账号。重复执行时，如果用户名已存在则拒绝操作，
避免把初始化命令误用成密码重置入口。
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth import hash_password
from app.database import SessionLocal, init_db
from app.models import Role, User


MIN_PASSWORD_LENGTH = 12


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"管理员密码至少需要 {MIN_PASSWORD_LENGTH} 个字符")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("管理员密码必须同时包含字母和数字")
    if password.lower() in {"admin123456", "password123456", "adminadmin123"}:
        raise ValueError("禁止使用常见管理员密码")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="显式创建 Med-Audit 管理员账号")
    parser.add_argument("--username", default=os.getenv("INIT_ADMIN_USERNAME", ""))
    parser.add_argument("--full-name", default=os.getenv("INIT_ADMIN_FULL_NAME", "系统管理员"))
    parser.add_argument("--email", default=os.getenv("INIT_ADMIN_EMAIL", ""))
    return parser.parse_args(argv)


def create_admin(username: str, password: str, full_name: str, email: str) -> int:
    username = (username or "").strip()
    if not username or len(username) > 50:
        raise ValueError("用户名不能为空且不能超过 50 个字符")
    _validate_password(password)

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            raise ValueError("该用户名已存在，初始化命令不会重置已有账号")
        role = db.query(Role).filter(Role.name == "admin").first()
        if not role:
            role = Role(name="admin", description="系统管理员")
            db.add(role)
            db.flush()
        user = User(
            username=username,
            password_hash=hash_password(password),
            full_name=(full_name or "系统管理员").strip(),
            email=(email or "").strip(),
            role_id=role.id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return int(user.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    username = args.username or input("管理员用户名: ").strip()
    password = getpass.getpass("管理员密码（不回显）: ")
    confirm = getpass.getpass("再次输入管理员密码: ")
    if password != confirm:
        print("两次密码不一致", file=sys.stderr)
        return 2
    try:
        init_db()
        user_id = create_admin(username, password, args.full_name, args.email)
    except ValueError as exc:
        print(f"初始化失败: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"初始化失败: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"管理员创建成功: username={username}, user_id={user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
