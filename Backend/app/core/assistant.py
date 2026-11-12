"""AI Core: คุยกับ LLM (Claude หรือโมเดลแบบ OpenAI เช่น Typhoon/Qwen) วนเรียก tool
ไม่รู้จักระบบหลักใด ๆ โดยตรง เครื่องมือมาจาก toolset ของ tenant
งานเขียน/ลบจะถูกเก็บเป็น pending รอผู้ใช้ยืนยันเสมอ"""
import hashlib
import json
import re
import uuid

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.adapters.registry import get_adapter
from app.catalog.catalog import get_catalog, is_catalog_tenant
from app.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT,
)
from app.core.toolsets import CatalogToolset, Ctx, LegacyToolset
from app.schemas import ChatRequest, ChatResponse

MAX_HISTORY = 20

MAX_SEEN_IDS = 5000

_sessions: dict[str, list[dict]] = {}
_seen_ids: dict[str, set[str]] = {}   # id ที่ session นี้เคยอ่านเจอ (กันโมเดลเดา id)


def make_toolset(tenant_id: str, user_token: str, session_id: str):
    if is_catalog_tenant(tenant_id):
        seen = _seen_ids.setdefault(session_id, set())
        if len(seen) > MAX_SEEN_IDS:
            seen.clear()
        return CatalogToolset(get_catalog(tenant_id), seen)
    return LegacyToolset(get_adapter(tenant_id, user_token))


# ---------------------------------------------------------------- Claude

_claude: AsyncAnthropic | None = None


def _get_claude() -> AsyncAnthropic:
    global _claude
    if _claude is None:
        _claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=LLM_TIMEOUT)
    return _claude


async def _chat_claude(history, user_msg, toolset, ctx) -> str:
    client = _get_claude()
    messages = history + [{"role": "user", "content": user_msg}]
    response = None

    corrected = False
    for _ in range(toolset.max_rounds):
        response = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1500,
            system=toolset.system_prompt(),
            tools=toolset.tools,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            fix = toolset.check_reply(text, ctx, user_msg)
            if fix and not corrected:
                corrected = True
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": f"[ระบบ] {fix}"})
                continue
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                text, is_error = await toolset.run(block.name, block.input, ctx)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": text,
                    "is_error": is_error,
                })
        messages.append({"role": "user", "content": results})

    if response is None:
        return ""
    return "".join(b.text for b in response.content if b.type == "text").strip()


# ------------------------------------------- โมเดลแบบ OpenAI (Typhoon/Qwen ฯลฯ)

_openai: AsyncOpenAI | None = None


def _openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(
            base_url=LLM_BASE_URL or None,
            api_key=LLM_API_KEY or "ollama",
            timeout=LLM_TIMEOUT,
        )
    return _openai


def _clean(text: str | None) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


async def _chat_openai(history, user_msg, toolset, ctx) -> str:
    if not LLM_MODEL:
        raise ValueError("ยังไม่ได้ตั้ง LLM_MODEL ใน .env")

    client = _get_openai()
    tools = _openai_tools(toolset.tools)
    messages = (
        [{"role": "system", "content": toolset.system_prompt()}]
        + history
        + [{"role": "user", "content": user_msg}]
    )

    corrected = False
    for _ in range(toolset.max_rounds):
        resp = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=tools,
            max_tokens=1500,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            text = _clean(msg.content)
            fix = toolset.check_reply(text, ctx, user_msg)
            if fix and not corrected:
                corrected = True
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content": f"[ระบบ] {fix}"})
                continue
            return text

        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {}
            text, _is_error = await toolset.run(tc.function.name, args, ctx)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
    return ""


# ------------------------------------------------------------------ main

async def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or str(uuid.uuid4())
    # ผูก session กับ tenant+ผู้ใช้ คนอื่นที่รู้ session_id จึงอ่านประวัติหรือ id ที่เห็นไม่ได้
    key = hashlib.sha256(f"{req.tenant_id}:{req.user_token}:{session_id}".encode()).hexdigest()
    toolset = make_toolset(req.tenant_id, req.user_token, key)
    history = _sessions.get(key, [])
    ctx = Ctx(tenant_id=req.tenant_id, user_token=req.user_token, user_msg=req.message)

    if LLM_PROVIDER == "openai":
        reply = await _chat_openai(history, req.message, toolset, ctx)
    else:
        reply = await _chat_claude(history, req.message, toolset, ctx)

    if not reply:
        reply = (
            "กรุณากดยืนยันในหน้าจอเพื่อดำเนินการต่อ"
            if ctx.pending
            else "ขออภัย ตอนนี้ยังตอบไม่ได้ ลองถามใหม่อีกครั้งนะคะ"
        )

    # กันโมเดลพูดว่า "กดยืนยัน" ทั้งที่ไม่มีงานรอยืนยันจริง
    if ctx.pending is None and toolset.confirm_word in reply:
        reply = toolset.no_pending_reply
    # กันโมเดลอ้างว่าทำงานเขียน/ลบสำเร็จ ทั้งที่ยังไม่ได้ทำ (แก้ตัวแล้วยังผิด)
    elif toolset.check_reply(reply, ctx, req.message):
        reply = toolset.false_success_reply

    history = history + [
        {"role": "user", "content": req.message},
        {"role": "assistant", "content": reply},
    ]
    _sessions[key] = history[-MAX_HISTORY:]

    return ChatResponse(
        session_id=session_id, reply=reply, exams=toolset.exams(), pending_action=ctx.pending
    )
