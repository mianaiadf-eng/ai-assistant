"""เทสต์โครงสร้าง agent หลัก + sub agent: router, auth กลาง, native function, WebSocket hub
(ไม่ต่อ LLM จริง: แทน llm.run_tools / llm.complete ด้วยสคริปต์)"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import config, security
from app.auth import vault
from app.core import llm, orchestrator, router
from app.services import pending
from app.subagent import registry
from app.subagent.base import NativeFunction, SubAgent
from tests.test_catalog import make_agent


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ fixtures

DONE: list[dict] = []


async def _list_items(ctx, args):
    return {"items": [{"name": "ของในระบบ B", "token_used": ctx.token}]}


async def _add_item(ctx, args):
    DONE.append({"name": args["name"], "token": ctx.token})
    return f"เพิ่ม {args['name']} แล้ว"


async def _login(agent, username, password):
    if password != "pw":
        from app.errors import UpstreamError
        raise UpstreamError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return f"tok-b-{username}"


def make_native_agent() -> SubAgent:
    return SubAgent(
        "sysb", "ระบบบี", "ระบบคลังของ", keywords=["คลัง"], login=_login,
        functions=[
            NativeFunction("list_items", "ดูของในคลัง", {"type": "object", "properties": {}}, _list_items),
            NativeFunction("add_item", "เพิ่มของ", {"type": "object", "properties": {"name": {"type": "string"}},
                                                    "required": ["name"]},
                           _add_item, risk="write", summarize=lambda a: f"เพิ่มของ “{a['name']}”"),
        ],
    )


@pytest.fixture
def setup(monkeypatch):
    reqs: list = []
    host = make_agent(reqs, name="sysa")
    host.title, host.keywords = "ระบบเอ", ("การ์ด",)
    other = make_native_agent()
    registry.register(host)
    registry.register(other)
    monkeypatch.setitem(config.TENANTS, "c1", {
        "public_key": "pk_c1", "allowed_origins": ["http://site-a"],
        "host_agent": "sysa", "agents": ["sysa", "sysb"],
    })
    monkeypatch.setattr(security, "APP_API_KEY", "admin")
    DONE.clear()
    yield {"host": host, "other": other, "reqs": reqs}
    registry.unregister("sysa")
    registry.unregister("sysb")


def script(*calls, reply="เสร็จแล้ว"):
    """แทน llm.run_tools: เรียกเครื่องมือตามลำดับที่กำหนด แล้วตอบข้อความ reply"""
    seen = {}

    async def fake(history, user_msg, toolset, ctx):
        seen["agent"] = toolset.agent.name
        seen["results"] = [await toolset.run(n, a, ctx) for n, a in calls]
        return reply
    return fake, seen


# ------------------------------------------------------------------ router

def test_router_prefers_cheap_paths(monkeypatch, setup):
    a, b = setup["host"], setup["other"]
    asked = []

    async def fake_complete(system, user, max_tokens=50):
        asked.append(user)
        return "sysb"
    monkeypatch.setattr(llm, "complete", fake_complete)

    assert run(router.route("อะไรก็ได้", [a])).how == "only"
    r = run(router.route("ในคลังมีอะไร", [a, b]))
    assert (r.agent, r.how) == (b, "keyword")
    r = run(router.route("ใช่", [a, b], last="sysa"))
    assert (r.agent, r.how) == (a, "follow_up")
    assert asked == []                                  # สามกรณีแรกไม่เรียก LLM
    r = run(router.route("ช่วยดูของที่ยืมไว้ทั้งหมดให้หน่อยได้ไหมครับ", [a, b]))
    assert (r.agent, r.how) == (b, "llm") and len(asked) == 1


def test_router_falls_back_when_llm_fails(monkeypatch, setup):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(llm, "complete", boom)
    r = run(router.route("ข้อความยาว ๆ ที่ไม่มีคำสำคัญของระบบใดเลยครับ", [setup["host"], setup["other"]],
                         last="sysb"))
    assert (r.agent.name, r.how) == ("sysb", "fallback")


# ------------------------------------------------------- auth กลาง + native

def test_other_system_requires_link_then_uses_vault_token(monkeypatch, setup):
    fake, seen = script(("list_items", {}))
    monkeypatch.setattr(llm, "run_tools", fake)

    r = run(orchestrator.chat("c1", "user-a", "ในคลังมีอะไร"))
    assert r.link_required is not None and r.link_required.name == "sysb"
    assert "agent" not in seen                          # ยังไม่ผูกบัญชี: ไม่ถึง sub agent

    with pytest.raises(Exception):
        run(orchestrator.link("c1", "user-a", "sysb", "somchai", "wrong"))
    info = run(orchestrator.link("c1", "user-a", "sysb", "somchai", "pw"))
    assert info.linked

    r = run(orchestrator.chat("c1", "user-a", "ในคลังมีอะไร", r.session_id))
    assert r.agent == "sysb" and r.link_required is None
    assert "tok-b-somchai" in seen["results"][0][0]     # sub agent ได้ token จาก auth กลาง

    # ผู้ใช้อื่น (token หน้าเว็บต่างกัน) ไม่ได้บัญชีที่ผูกไว้ไปด้วย
    r = run(orchestrator.chat("c1", "user-b", "ในคลังมีอะไร"))
    assert r.link_required is not None
    vault.remove(orchestrator.owner_of("c1", "user-a"), "sysb")


def test_native_write_waits_for_confirm(monkeypatch, setup):
    run(orchestrator.link("c1", "user-a", "sysb", "somchai", "pw"))
    fake, seen = script(("add_item", {"name": "ปากกา"}))
    monkeypatch.setattr(llm, "run_tools", fake)

    r = run(orchestrator.chat("c1", "user-a", "เพิ่มของในคลัง ปากกา"))
    assert DONE == []                                    # ยังไม่ทำจริง
    pa = r.pending_action
    assert pa is not None and pa.agent == "sysb" and "ปากกา" in pa.summary

    assert pending.take(pa.id, "c1", "user-b") is None   # คนอื่นยืนยันแทนไม่ได้
    rec = pending.take(pa.id, "c1", "user-a")
    res = run(orchestrator.confirm(rec, "c1", "user-a"))
    assert DONE == [{"name": "ปากกา", "token": "tok-b-somchai"}] and "ปากกา" in res.message
    vault.remove(orchestrator.owner_of("c1", "user-a"), "sysb")


def test_native_missing_required_arg(setup):
    from app.subagent.toolset import SubAgentToolset
    ctx = orchestrator.AgentCtx(agent=setup["other"], tenant_id="c1", owner="o")
    text, err = run(SubAgentToolset(setup["other"]).run("add_item", {}, ctx))
    assert err and "name" in text and ctx.pending is None


def test_host_agent_uses_page_token(monkeypatch, setup):
    fake, seen = script(("call_action", {"action_id": "getCard", "args": {"id": "c1"}}))
    monkeypatch.setattr(llm, "run_tools", fake)
    # host ไม่ต้องผูกบัญชี: ใช้ token ของหน้าเว็บ (ไม่มี bridge -> เซิร์ฟเวอร์เรียกเอง)
    ctx = orchestrator.make_ctx(setup["host"], "c1", "page-token")
    assert ctx is not None and ctx.token == "page-token"
    status = orchestrator.agents_status("c1", "page-token")
    assert {a.name: a.linked for a in status} == {"sysa": True, "sysb": False}


def test_planka_search_finds_actions():
    cat = registry.get_agent("planka").catalog
    assert cat.use_search
    assert cat.search("ลบการ์ด", 1)[0]["action_id"] == "deleteCard"
    assert cat.search("create list", 1)[0]["action_id"] == "createList"
    assert cat.search("list boards", 1)[0]["action_id"] == "getBoard"
    assert all(a["action_id"] != "getUsers" for a in cat.search("users", 20))   # ถูก block


# ------------------------------------------------------------------ WebSocket

def _recv_until(ws, kind):
    events = []
    while True:
        m = ws.receive_json()
        events.append(m)
        if m.get("type") in (kind, "error"):
            return m, events


def test_websocket_rejects_bad_origin(setup):
    from app.main import app
    with TestClient(app) as client:
        with client.websocket_connect("/ws?tenant=c1&key=pk_c1", headers={"origin": "http://evil"}) as ws:
            m = ws.receive_json()
            assert m["type"] == "error" and m["status"] == 403


def test_websocket_chat_with_browser_call_and_confirm(monkeypatch, setup):
    """ระบบที่ฝัง widget: เซิร์ฟเวอร์ขอให้หน้าเว็บเรียก API ผ่าน WebSocket แล้วแสดงสถานะระหว่างทาง"""
    from app.main import app
    setup["host"].catalog  # โหลดแคตตาล็อก
    fake, seen = script(("call_action", {"action_id": "getCard", "args": {"id": "c1"}}),
                        reply="การ์ดชื่อ จากเบราว์เซอร์")

    async def fake_with_seen(history, user_msg, toolset, ctx):
        toolset.seen_ids.add("c1")
        return await fake(history, user_msg, toolset, ctx)
    monkeypatch.setattr(llm, "run_tools", fake_with_seen)

    with TestClient(app) as client:
        with client.websocket_connect("/ws?tenant=c1&key=pk_c1", headers={"origin": "http://site-a"}) as ws:
            ws.send_json({"type": "hello", "user_token": "page-token", "req_id": "h"})
            ready, _ = _recv_until(ws, "ready")
            assert {a["name"] for a in ready["agents"]} == {"sysa", "sysb"}

            ws.send_json({"type": "chat", "message": "การ์ดนี้ชื่ออะไร", "req_id": "r1"})
            call, events = _recv_until(ws, "call")
            assert any(e.get("type") == "status" for e in events)          # สถานะเรียลไทม์
            assert call["method"] == "GET" and call["path"] == "/api/cards/c1"
            ws.send_json({"type": "call_result", "call_id": call["call_id"], "status": 200,
                          "body": {"item": {"id": "c1", "name": "จากเบราว์เซอร์"}}})
            reply, _ = _recv_until(ws, "reply")
            assert reply["req_id"] == "r1" and reply["agent"] == "sysa"
            assert "จากเบราว์เซอร์" in seen["results"][0][0]
            assert setup["reqs"] == []                     # เซิร์ฟเวอร์ไม่ได้เรียกระบบเอง

            ws.send_json({"type": "confirm", "action_id": "nope", "req_id": "c"})
            err, _ = _recv_until(ws, "confirmed")
            assert err["type"] == "error" and err["status"] == 404
