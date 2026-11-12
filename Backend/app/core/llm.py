"""คุยกับ LLM: ค่าเริ่มต้นคือโมเดลรูปแบบ OpenAI (Typhoon) / Claude เป็นทางเลือก
- run_tools(...)  วนเรียก tool ของ sub agent จนได้คำตอบ
- complete(...)   เรียกครั้งเดียวไม่มี tool (ใช้โดย agent หลักตอนเลือก sub agent)"""
import json
import re

from openai import AsyncOpenAI

from app.config import (
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    LLM_PROVIDER, LLM_TIMEOUT,
)

MAX_TOKENS = 1500

_openai: AsyncOpenAI | None = None
_claude = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(base_url=LLM_BASE_URL or None, api_key=LLM_API_KEY or "ollama",
                              timeout=LLM_TIMEOUT)
    return _openai


def _get_claude():
    global _claude
    if _claude is None:
        from anthropic import AsyncAnthropic
        _claude = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=LLM_TIMEOUT)
    return _claude


def _clean(text: str | None) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def _openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["input_schema"],
    }} for t in tools]


# ------------------------------------------------------------- ครั้งเดียว

async def complete(system: str, user: str, max_tokens: int = 50) -> str:
    if LLM_PROVIDER == "claude":
        r = await _get_claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in r.content if b.type == "text").strip()
    if not LLM_MODEL:
        raise ValueError("ยังไม่ได้ตั้ง LLM_MODEL ใน .env")
    r = await _get_openai().chat.completions.create(
        model=LLM_MODEL, max_tokens=max_tokens, temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return _clean(r.choices[0].message.content)


# ------------------------------------------------------------- วนเรียก tool

async def run_tools(history: list[dict], user_msg: str, toolset, ctx) -> str:
    if LLM_PROVIDER == "claude":
        return await _run_claude(history, user_msg, toolset, ctx)
    return await _run_openai(history, user_msg, toolset, ctx)


async def _run_openai(history, user_msg, toolset, ctx) -> str:
    if not LLM_MODEL:
        raise ValueError("ยังไม่ได้ตั้ง LLM_MODEL ใน .env")
    client = _get_openai()
    tools = _openai_tools(toolset.tools)
    messages = ([{"role": "system", "content": toolset.system_prompt()}] + history
                + [{"role": "user", "content": user_msg}])

    corrected = False
    for _ in range(toolset.max_rounds):
        kwargs = {"tools": tools} if tools else {}
        resp = await client.chat.completions.create(
            model=LLM_MODEL, messages=messages, max_tokens=MAX_TOKENS, **kwargs)
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


async def _run_claude(history, user_msg, toolset, ctx) -> str:
    client = _get_claude()
    messages = history + [{"role": "user", "content": user_msg}]
    response = None
    corrected = False
    for _ in range(toolset.max_rounds):
        response = await client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=MAX_TOKENS, system=toolset.system_prompt(),
            tools=toolset.tools, messages=messages)
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
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    if response is None:
        return ""
    return "".join(b.text for b in response.content if b.type == "text").strip()
