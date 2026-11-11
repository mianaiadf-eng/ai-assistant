"""ตรวจสิทธิ์เรียก API ของผู้ช่วย

มี key 2 แบบ
- APP_API_KEY (ใน .env): key หลักของผู้ดูแล ใช้ได้ทุก tenant ห้ามฝังในหน้าเว็บ
- public_key ของแต่ละ tenant (ใน tenants.json): ฝังใน widget ได้ เพราะ
    * ใช้ได้กับ tenant ของตัวเองเท่านั้น
    * ต้องมาจากหน้าเว็บที่อยู่ใน allowed_origins (ตรวจ header Origin ที่เบราว์เซอร์ส่งมา)
  หมายเหตุ: Origin ปลอมได้ถ้าไม่ได้เรียกจากเบราว์เซอร์ จึงยังต้องมี token ของผู้ใช้ในระบบหลักทุกครั้ง
  (key นี้กันแค่การนำ widget ไปใช้บนเว็บอื่น ไม่ได้แทนการยืนยันตัวตนของผู้ใช้)
"""
import secrets

from fastapi import HTTPException, Request

from app.config import APP_API_KEY, TENANTS


def _eq(a: str, b: str) -> bool:
    return bool(a) and bool(b) and secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def authorize(request: Request, tenant_id: str) -> None:
    key = request.headers.get("x-api-key", "")
    if _eq(key, APP_API_KEY):
        return

    tenant = TENANTS.get(tenant_id) or {}
    if not _eq(key, tenant.get("public_key", "")):
        raise HTTPException(status_code=401, detail="invalid api key")

    allowed = tenant.get("allowed_origins") or []
    origin = request.headers.get("origin", "")
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="เว็บไซต์นี้ไม่ได้รับอนุญาตให้ใช้ผู้ช่วยของระบบนี้")


def widget_config(tenant_id: str) -> dict:
    """ค่าที่ widget ต้องรู้ (ไม่มีความลับ)"""
    tenant = TENANTS.get(tenant_id) or {}
    return {
        "tenant_id": tenant_id,
        "title": tenant.get("title") or tenant_id,
        # token ของผู้ใช้เอามาจากไหนในหน้าเว็บระบบหลัก เช่น {"from": "cookie", "name": "accessToken"}
        # ไม่ตั้ง = widget แสดงหน้าล็อกอินของตัวเอง
        "token": (tenant.get("widget") or {}).get("token"),
    }
