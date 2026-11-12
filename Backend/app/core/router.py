"""agent หลัก: วิเคราะห์ว่าข้อความนี้เป็นงานของ sub agent ไหน แล้วส่งต่อ

เรียก LLM ให้น้อยที่สุด (Typhoon ช้า) ตามลำดับ:
1. มี sub agent ตัวเดียว -> ใช้ตัวนั้น
2. ข้อความมีคำสำคัญ (keywords/ชื่อระบบ) ของ sub agent ตัวเดียว -> ใช้ตัวนั้น
3. ข้อความสั้นแบบต่อเนื่อง (เช่น "ใช่", "อันแรก") -> ใช้ตัวเดิมของบทสนทนา
4. ถาม LLM ด้วย prompt สั้น ๆ ให้ตอบชื่อ sub agent คำเดียว
"""
import logging
from dataclasses import dataclass

from app.core import llm
from app.subagent.base import SubAgent

log = logging.getLogger("assistant")

FOLLOW_UP_MAX_CHARS = 25


@dataclass
class Route:
    agent: SubAgent
    how: str   # only | keyword | follow_up | llm | fallback


def _keyword_hits(message: str, agent: SubAgent) -> int:
    text = message.lower()
    words = {agent.title.lower(), agent.name.lower(), *(k.lower() for k in agent.keywords)}
    return sum(1 for w in words if w and w in text)


def _prompt(candidates: list[SubAgent]) -> str:
    lines = "\n".join(f"- {a.name}: {a.title} — {a.description}" for a in candidates)
    return ("คุณคือ agent หลัก ทำหน้าที่ส่งข้อความของผู้ใช้ไปยังระบบที่รับผิดชอบ\n"
            f"ระบบที่มี:\n{lines}\n\n"
            "ตอบเป็นชื่อระบบ (คำหน้าเครื่องหมาย :) เพียงคำเดียว ห้ามอธิบาย")


async def route(message: str, candidates: list[SubAgent], last: str | None = None) -> Route:
    if not candidates:
        raise KeyError("ไม่มี sub agent ที่ใช้ได้")
    if len(candidates) == 1:
        return Route(candidates[0], "only")

    hits = [(_keyword_hits(message, a), a) for a in candidates]
    best = max(h for h, _ in hits)
    top = [a for h, a in hits if h == best]
    if best > 0 and len(top) == 1:
        return Route(top[0], "keyword")

    by_name = {a.name: a for a in candidates}
    if last in by_name and len(message.strip()) <= FOLLOW_UP_MAX_CHARS:
        return Route(by_name[last], "follow_up")

    user = f"ข้อความของผู้ใช้: {message}"
    if last in by_name:
        user = (f"ข้อความก่อนหน้าคุยกับระบบ {last} ถ้าเป็นเรื่องต่อเนื่องให้เลือก {last}\n" + user)
    try:
        answer = (await llm.complete(_prompt(candidates), user)).lower()
    except Exception as e:  # เลือกไม่ได้ไม่ควรทำให้ทั้งงานล้ม ใช้ตัวสำรอง
        log.warning("ROUTER llm error: %r", e)
        answer = ""
    for name in sorted(by_name, key=len, reverse=True):
        if name.lower() in answer:
            return Route(by_name[name], "llm")
    return Route(by_name.get(last) or candidates[0], "fallback")
