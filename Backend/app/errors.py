"""ข้อผิดพลาดกลางของระบบ (ข้อความต้องอ่านเข้าใจได้ เพราะส่งถึงผู้ใช้)"""
import logging

log = logging.getLogger("assistant")


class UpstreamError(Exception):
    """ติดต่อหรือทำรายการกับระบบรอบข้างไม่สำเร็จ"""


class NotSupported(Exception):
    """sub agent นี้ไม่รองรับสิ่งที่ขอ"""


def describe_error(e: Exception) -> tuple[int, str]:
    """แปลง exception เป็น (รหัส HTTP, ข้อความที่ผู้ใช้อ่านเข้าใจ) ใช้ทั้ง HTTP และ WebSocket"""
    import openai
    from fastapi import HTTPException

    from app.services.turns import TurnError

    if isinstance(e, HTTPException):
        return e.status_code, str(e.detail)
    if isinstance(e, TurnError):
        return 404, str(e)
    if isinstance(e, KeyError):
        return 404, str(e.args[0]) if e.args else "ไม่พบข้อมูล"
    if isinstance(e, PermissionError):
        return 401, str(e)
    if isinstance(e, NotSupported):
        return 501, str(e)
    if isinstance(e, UpstreamError):
        return 502, str(e)
    if isinstance(e, TimeoutError):
        return 504, str(e) or "ใช้เวลานานเกินไป ลองใหม่อีกครั้ง"
    if isinstance(e, ValueError):
        return 500, str(e)
    if isinstance(e, openai.AuthenticationError):
        return 502, "LLM_API_KEY ไม่ถูกต้อง ตรวจไฟล์ .env แล้วรีสตาร์ทเซิร์ฟเวอร์"
    if isinstance(e, openai.APIConnectionError):
        return 503, "เชื่อมต่อโมเดล AI ไม่ได้"
    if isinstance(e, openai.APITimeoutError):
        return 504, "โมเดล AI ตอบช้าเกินไป ลองใหม่อีกครั้ง"
    if isinstance(e, openai.APIError):
        log.error("LLM error: %r", e)
        return 502, f"เรียกโมเดลไม่สำเร็จ: {type(e).__name__}"
    try:
        import anthropic
        if isinstance(e, anthropic.APIError):
            log.error("LLM error: %r", e)
            return 502, f"เรียกโมเดลไม่สำเร็จ: {type(e).__name__}"
    except ImportError:
        pass
    log.error("unexpected error", exc_info=e)
    return 500, "เกิดข้อผิดพลาดภายในระบบ"
