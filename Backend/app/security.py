"""ตรวจสิทธิ์เรียก API ของผู้ช่วย (ทั้ง HTTP และ WebSocket)

มี key 2 แบบ
- APP_API_KEY (ใน .env): key หลักของผู้ดูแล ใช้ได้ทุก client ห้ามฝังในหน้าเว็บ
- public_key ของแต่ละ client (ใน tenants.json): ฝังใน widget ได้ เพราะ
    * ใช้ได้กับ client ของตัวเองเท่านั้น
    * ต้องมาจากหน้าเว็บที่อยู่ใน allowed_origins (ตรวจ header Origin ที่เบราว์เซอร์ส่งมา)
  หมายเหตุ: Origin ปลอมได้ถ้าไม่ได้เรียกจากเบราว์เซอร์ จึงยังต้องมี token ของผู้ใช้ในระบบทุกครั้ง
  (key นี้กันแค่การนำ widget ไปใช้บนเว็บอื่น ไม่ได้แทนการยืนยันตัวตนของผู้ใช้)
"""
import secrets

from fastapi import HTTPException, Request

from app.config import APP_API_KEY, TENANTS


def _eq(a: str, b: str) -> bool:
    return bool(a) and bool(b) and secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def check_access(key: str, origin: str, tenant_id: str, allow_admin: bool = True) -> None:
    if allow_admin and _eq(key, APP_API_KEY):
        return

    tenant = TENANTS.get(tenant_id) or {}
    if not _eq(key, tenant.get("public_key", "")):
        raise HTTPException(status_code=401, detail="invalid api key")

    if origin not in (tenant.get("allowed_origins") or []):
        raise HTTPException(status_code=403, detail="เว็บไซต์นี้ไม่ได้รับอนุญาตให้ใช้ผู้ช่วยของระบบนี้")


def authorize(request: Request, tenant_id: str) -> None:
    check_access(request.headers.get("x-api-key", ""), request.headers.get("origin", ""), tenant_id)


def widget_config(tenant_id: str) -> dict:
    """ค่าที่ widget ต้องรู้ (ไม่มีความลับ)"""
    tenant = TENANTS.get(tenant_id) or {}
    return {
        "tenant_id": tenant_id,
        "title": tenant.get("title") or tenant_id,
        # token ของผู้ใช้เอามาจากไหนในหน้าเว็บระบบหลัก เช่น {"from": "cookie", "name": "accessToken"}
        # ไม่ตั้ง = widget สร้างรหัสผู้ใช้ชั่วคราวเอง แล้วให้ผู้ใช้ผูกบัญชีทีละระบบ
        "token": (tenant.get("widget") or {}).get("token"),
        # ระบบที่ฝัง widget: เมื่อแก้ข้อมูลระบบนี้สำเร็จ widget จะแจ้งหน้าเว็บให้อัปเดต
        "host_agent": tenant.get("host_agent"),
    }
