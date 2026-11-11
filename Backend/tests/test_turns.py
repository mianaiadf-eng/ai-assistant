"""เทสต์การให้ widget เรียก API ระบบหลักแทนเซิร์ฟเวอร์ (turns)"""
import asyncio

import pytest

from app.core.toolsets import CatalogToolset, Ctx, execute_confirmed
from app.services import pending, turns
from tests.test_catalog import make_catalog


def test_read_goes_through_browser_and_server_never_calls_host():
    async def main():
        server_reqs = []
        cat = make_catalog(server_reqs)          # ถ้าเซิร์ฟเวอร์เรียกเอง จะถูกบันทึกในนี้
        ts = CatalogToolset(cat, seen_ids={"c1"})
        ctx = Ctx("t1", "tok")

        async def work():
            return await ts.run("call_action", {"action_id": "getCard", "args": {"id": "c1"}}, ctx)

        ev = await turns.start(work, "t1", "tok")
        assert ev["call"]["method"] == "GET" and ev["call"]["path"] == "/api/cards/c1"

        # คนอื่นส่งผลแทนไม่ได้
        with pytest.raises(turns.TurnError):
            await turns.resume(ev["turn_id"], "t1", "other", ev["call"]["call_id"], 200, {})

        text, err = await turns.resume(ev["turn_id"], "t1", "tok", ev["call"]["call_id"], 200,
                                       {"item": {"id": "c1", "name": "จากเบราว์เซอร์"}})
        assert not err and "จากเบราว์เซอร์" in text
        assert server_reqs == []
    asyncio.run(main())


def test_delete_flow_via_browser_requires_confirm():
    async def main():
        server_reqs = []
        cat = make_catalog(server_reqs)
        ts = CatalogToolset(cat, seen_ids={"c1"})
        ctx = Ctx("t1", "tok", user_msg="ลบการ์ด ทบทวนฐานข้อมูล")

        async def plan():
            return await ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx)

        ev = await turns.start(plan, "t1", "tok")
        # ขั้นวางแผน: เบราว์เซอร์ถูกขอแค่ GET (ดึงชื่อการ์ดมาแสดงในป๊อปอัป) ไม่มี DELETE
        assert ev["call"]["method"] == "GET"
        await turns.resume(ev["turn_id"], "t1", "tok", ev["call"]["call_id"], 200,
                           {"item": {"name": "ทบทวนฐานข้อมูล"}})
        assert ctx.pending is not None and "ทบทวนฐานข้อมูล" in ctx.pending.summary

        # หลังผู้ใช้กดยืนยัน: เบราว์เซอร์ถูกขอให้ DELETE
        rec = pending.take(ctx.pending.id, "t1", "tok")
        ev = await turns.start(lambda: execute_confirmed(cat, rec.args, rec.summary, "tok"), "t1", "tok")
        assert ev["call"]["method"] == "DELETE" and ev["call"]["path"] == "/api/cards/c1"
        msg = await turns.resume(ev["turn_id"], "t1", "tok", ev["call"]["call_id"], 200, {})
        assert "เรียบร้อย" in msg
        assert server_reqs == []
    asyncio.run(main())


def test_errors_inside_turn_are_raised_to_caller():
    async def main():
        async def boom():
            raise ValueError("พัง")
        with pytest.raises(ValueError):
            await turns.start(boom, "t1", "tok")
    asyncio.run(main())


def test_without_bridge_server_calls_directly():
    async def main():
        reqs = []
        cat = make_catalog(reqs)
        status, _ = await cat.call(cat.actions["getCard"], {"id": "c1"}, "tok")
        assert status == 200 and reqs == [("GET", "/api/cards/c1")]
    asyncio.run(main())
