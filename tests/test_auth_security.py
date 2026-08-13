import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auth
from app.models import Base, Role, User
from scripts import init_admin


def test_production_jwt_secret_requires_strong_non_default_key():
    with pytest.raises(RuntimeError):
        auth._load_jwt_secret({"ENVIRONMENT": "production", "JWT_SECRET_KEY": ""})
    with pytest.raises(RuntimeError):
        auth._load_jwt_secret({"ENVIRONMENT": "production", "JWT_SECRET_KEY": "short-secret"})
    with pytest.raises(RuntimeError):
        auth._load_jwt_secret({"ENVIRONMENT": "production", "JWT_SECRET_KEY": auth._DEFAULT_SECRET})

    secret = "x" * 32
    assert auth._load_jwt_secret({"ENVIRONMENT": "production", "JWT_SECRET_KEY": secret}) == secret


def test_environment_alias_conflict_is_rejected():
    with pytest.raises(RuntimeError, match="冲突"):
        auth._load_jwt_secret(
            {"ENVIRONMENT": "production", "APP_ENV": "development", "JWT_SECRET_KEY": "x" * 32}
        )


def test_production_environment_aliases_are_equivalent():
    secret = "x" * 32
    assert auth._load_jwt_secret(
        {"ENVIRONMENT": "production", "APP_ENV": "prod", "JWT_SECRET_KEY": secret}
    ) == secret


def test_development_without_secret_uses_only_development_fallback():
    assert auth._load_jwt_secret({"ENVIRONMENT": "development", "JWT_SECRET_KEY": ""}) == auth._DEFAULT_SECRET


def test_explicit_admin_creation_rejects_weak_and_duplicate_password(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(init_admin, "SessionLocal", Session)

    with pytest.raises(ValueError):
        init_admin.create_admin("admin", "Admin123", "系统管理员", "")

    user_id = init_admin.create_admin("admin", "SafeAdmin12345", "系统管理员", "")
    assert user_id > 0
    assert Session().query(User).filter(User.username == "admin").count() == 1
    with pytest.raises(ValueError, match="已存在"):
        init_admin.create_admin("admin", "AnotherAdmin123", "系统管理员", "")


def test_runtime_initialization_has_no_debug_admin_recreator():
    import app.database as database

    assert not hasattr(database, "_ensure_debug_admin")
    assert not hasattr(__import__("app.routers.users", fromlist=["users"]), "_ensure_debug_admin_for_login")
