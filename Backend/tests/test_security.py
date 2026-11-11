"""เทสต์สิทธิ์เรียก API: key หลัก vs public key ต่อ tenant + origin"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import security

TENANTS = {
    "t1": {"public_key": "pk_one", "allowed_origins": ["http://host-one"],
           "title": "One", "widget": {"token": {"from": "cookie", "name": "accessToken"}}},
    "t2": {"public_key": "pk_two", "allowed_origins": ["http://host-two"]},
}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(security, "TENANTS", TENANTS)
    monkeypatch.setattr(security, "APP_API_KEY", "admin-secret")


def req(key: str = "", origin: str = "") -> Request:
    headers = []
    if key:
        headers.append((b"x-api-key", key.encode()))
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "headers": headers})


def status(key, origin, tenant):
    try:
        security.authorize(req(key, origin), tenant)
        return 200
    except HTTPException as e:
        return e.status_code


def test_admin_key_works_for_any_tenant():
    assert status("admin-secret", "", "t1") == 200
    assert status("admin-secret", "http://evil", "t2") == 200


def test_public_key_only_for_its_tenant_and_origin():
    assert status("pk_one", "http://host-one", "t1") == 200
    assert status("pk_one", "http://host-one", "t2") == 401   # key ของ tenant อื่น
    assert status("pk_one", "http://evil", "t1") == 403       # เว็บที่ไม่ได้รับอนุญาต
    assert status("pk_one", "", "t1") == 403                  # ไม่มี origin (ไม่ได้มาจากเบราว์เซอร์)


def test_missing_or_wrong_key():
    assert status("", "http://host-one", "t1") == 401
    assert status("nope", "http://host-one", "t1") == 401
    assert status("pk_one", "http://host-one", "unknown") == 401


def test_widget_config_has_no_secrets():
    cfg = security.widget_config("t1")
    assert cfg == {"tenant_id": "t1", "title": "One",
                   "token": {"from": "cookie", "name": "accessToken"}}
