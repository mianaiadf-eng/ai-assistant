"""เทสต์แคตตาล็อก action จาก OpenAPI และกฎการยืนยัน (ไม่ต้องต่อเครือข่ายจริง)
รัน: .venv\\Scripts\\python -m pytest -q   (จากโฟลเดอร์ Backend)"""
import asyncio
import json

import httpx
import pytest

from app.catalog.catalog import Catalog
from app.catalog.spec import build_actions
from app.core.toolsets import CATALOG_TOOL, CatalogToolset, Ctx, execute_confirmed
from app.services import pending

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Demo"},
    "servers": [{"url": "/api"}],
    "components": {"schemas": {"CardBody": {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string", "example": "x"},
            "kind": {"type": "string", "enum": ["a", "b"]},
        },
    }}},
    "paths": {
        "/cards/{id}": {
            "get": {"operationId": "getCard", "summary": "Get card", "tags": ["Cards"],
                    "parameters": [{"name": "id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}]},
            "delete": {"operationId": "deleteCard", "summary": "Delete card", "tags": ["Cards"],
                       "parameters": [{"name": "id", "in": "path", "required": True,
                                       "schema": {"type": "string"}}]},
        },
        "/lists/{listId}/cards": {
            "post": {"operationId": "createCard", "summary": "Create card", "tags": ["Cards"],
                     "parameters": [{"name": "listId", "in": "path", "required": True,
                                     "schema": {"type": "string"}}],
                     "requestBody": {"required": True, "content": {"application/json": {
                         "schema": {"$ref": "#/components/schemas/CardBody"}}}}},
        },
        "/lists/{id}": {
            "get": {"operationId": "getList", "summary": "Get list", "tags": ["Lists"],
                    "parameters": [{"name": "id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}]},
        },
        "/lists/{id}/clear": {
            "post": {"operationId": "clearList", "summary": "Clear list", "tags": ["Lists"],
                     "parameters": [{"name": "id", "in": "path", "required": True,
                                     "schema": {"type": "string"}}]},
        },
        "/users": {
            "get": {"operationId": "getUsers", "summary": "Get users", "tags": ["Users"]},
        },
        "/cards/{id}/attachments": {
            "post": {"operationId": "createAttachment", "summary": "Upload", "tags": ["Cards"],
                     "parameters": [{"name": "id", "in": "path", "required": True,
                                     "schema": {"type": "string"}}],
                     "requestBody": {"content": {"multipart/form-data": {"schema": {
                         "type": "object", "required": ["file"],
                         "properties": {"file": {"type": "string", "format": "binary"},
                                        "name": {"type": "string"}}}}}}},
        },
    },
}

POLICY = {
    "blocked_tags": ["Users"],
    "risk": {"clearList": "destructive"},
    "labels": {"deleteCard": "ลบการ์ด"},
}


def make_catalog(requests: list):
    cfg = {"base_url": "http://host", "openapi": "x", "policy": POLICY}
    cat = Catalog("t1", cfg, SPEC)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.raw_path.decode()))
        if request.method == "GET" and request.url.path == "/api/cards/c1":
            return httpx.Response(200, json={"item": {"id": "c1", "name": "ทบทวนฐานข้อมูล"}})
        if request.method == "GET" and request.url.path == "/api/lists/l1":
            return httpx.Response(200, json={"item": {"id": "l1", "name": "งานที่ต้องทำ"}})
        if request.method == "GET" and request.url.path.startswith("/api/cards/"):
            return httpx.Response(404, json={"code": "E_NOT_FOUND"})
        return httpx.Response(200, json={"item": {"id": "ok"}})

    cat.transport = httpx.MockTransport(handler)
    return cat


# ------------------------------------------------------------------ spec

def test_risk_from_method_and_policy():
    actions = build_actions(SPEC, POLICY)
    assert actions["getCard"].risk == "read"
    assert actions["createCard"].risk == "write"
    assert actions["deleteCard"].risk == "destructive"
    assert actions["clearList"].risk == "destructive"   # override จาก policy


def test_blocked_and_multipart_are_hidden():
    actions = build_actions(SPEC, POLICY)
    assert "getUsers" not in actions          # blocked_tags
    assert "createAttachment" not in actions  # อัปโหลดไฟล์ทำผ่านแชตไม่ได้


def test_body_ref_is_resolved_and_slimmed():
    schema = build_actions(SPEC, POLICY)["createCard"].input_schema()
    assert set(schema["properties"]) == {"listId", "name", "kind"}
    assert set(schema["required"]) == {"listId", "name"}
    assert "example" not in schema["properties"]["name"]


def test_validate():
    cat = make_catalog([])
    a = cat.actions["createCard"]
    assert cat.validate(a, {"listId": "l1", "name": "n"}) == []
    errs = " ".join(cat.validate(a, {"listId": "l1", "kind": "zzz", "hack": 1}))
    assert "name" in errs and "kind" in errs and "hack" in errs


def test_path_params_cannot_escape_endpoint():
    cat = make_catalog([])
    url, _, _ = cat._request_parts(cat.actions["deleteCard"], {"id": "../users/1"})
    assert url == "http://host/api/cards/..%2Fusers%2F1"


# ------------------------------------------------------------ การยืนยัน

def run(coro):
    return asyncio.run(coro)


def test_read_runs_immediately():
    reqs = []
    ts = CatalogToolset(make_catalog(reqs), seen_ids={"c1"})
    ctx = Ctx("t1", "tok")
    text, err = run(ts.run("call_action", {"action_id": "getCard", "args": {"id": "c1"}}, ctx))
    assert not err and "ทบทวนฐานข้อมูล" in text
    assert reqs == [("GET", "/api/cards/c1")]
    assert ctx.pending is None


def test_guessed_id_is_rejected():
    reqs = []
    ts = CatalogToolset(make_catalog(reqs))
    ctx = Ctx("t1", "tok")
    text, err = run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx))
    assert err and "ห้ามเดา id" in text
    assert reqs == [] and ctx.pending is None
    # การอ่านด้วย id ที่ไม่เคยเห็นก็ถูกปฏิเสธเช่นกัน
    _, err = run(ts.run("call_action", {"action_id": "getCard", "args": {"id": "c1"}}, ctx))
    assert err and reqs == []
    # หลังผลการอ่านรายการมี id นี้ (เช่นจาก GET รายการการ์ด) จึงใช้ได้
    ts._remember_ids({"items": [{"id": "c1", "listId": "l1"}]})
    _, err = run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx))
    assert not err and ctx.pending is not None


def test_action_name_used_as_tool_name():
    reqs = []
    ts = CatalogToolset(make_catalog(reqs), seen_ids={"c1"})
    ctx = Ctx("t1", "tok")
    _, err = run(ts.run("deleteCard", {"id": "c1"}, ctx))
    assert not err and ctx.pending is not None          # ยังต้องยืนยันเหมือนเดิม
    assert ("DELETE", "/api/cards/c1") not in reqs


def test_destructive_never_runs_without_confirm():
    reqs = []
    cat = make_catalog(reqs)
    ts = CatalogToolset(cat, seen_ids={"c1"})
    ctx = Ctx("t1", "tok")
    text, err = run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx))
    assert not err
    assert ("DELETE", "/api/cards/c1") not in reqs         # ยังไม่ลบจริง
    assert ctx.pending is not None and ctx.pending.risk == "destructive"
    # ข้อความยืนยันสร้างจากโค้ด มีชื่อจริงของการ์ดที่ดึงจาก GET
    assert "ลบการ์ด" in ctx.pending.summary and "ทบทวนฐานข้อมูล" in ctx.pending.summary

    # ทำได้ทีละรายการ
    _, err2 = run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx))
    assert err2

    # ผู้ใช้อื่นยืนยันแทนไม่ได้
    assert pending.take(ctx.pending.id, "t1", "someone-else") is None

    rec = pending.take(ctx.pending.id, "t1", "tok")
    assert rec.tool == CATALOG_TOOL
    run(execute_confirmed(cat, rec.args, rec.summary, "tok"))
    assert ("DELETE", "/api/cards/c1") in reqs              # ลบหลังยืนยันเท่านั้น
    assert pending.take(ctx.pending.id, "t1", "tok") is None  # ใช้ซ้ำไม่ได้


def test_destructive_with_unknown_id_is_rejected_before_confirm():
    reqs = []
    ts = CatalogToolset(make_catalog(reqs), seen_ids={"nope"})
    ctx = Ctx("t1", "tok")
    text, err = run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "nope"}}, ctx))
    assert err and ctx.pending is None


def test_unknown_or_blocked_action_rejected():
    ts = CatalogToolset(make_catalog([]))
    ctx = Ctx("t1", "tok")
    for aid in ("getUsers", "createAttachment", "made_up"):
        _, err = run(ts.run("call_action", {"action_id": aid, "args": {}}, ctx))
        assert err


def test_describe_actions():
    ts = CatalogToolset(make_catalog([]))
    text, err = run(ts.run("describe_actions", {"action_ids": ["createCard"]}, Ctx("t1", "tok")))
    assert not err
    assert json.loads(text)[0]["args_schema"]["required"] == ["listId", "name"]


@pytest.mark.parametrize("risk", ["write", "destructive"])
def test_summary_marks_risk(risk):
    actions = build_actions(SPEC, POLICY)
    a = actions["createCard"] if risk == "write" else actions["deleteCard"]
    s = CatalogToolset._summary(a, {"listId": "l1", "name": "X"}, None)
    assert ("แก้ไขข้อมูล" if risk == "write" else "ย้อนกลับไม่ได้") in s


# ------------------------------------------------------------- เวลา/ค่าเริ่มต้น

def test_local_time_input_is_sent_as_utc():
    from app.catalog.catalog import to_utc
    assert to_utc("2026-11-12T18:00") == "2026-11-12T11:00:00.000Z"        # เวลาไทย
    assert to_utc("2026-11-12T11:00:00.000Z") == "2026-11-12T11:00:00.000Z"  # UTC อยู่แล้ว


def test_results_show_local_time():
    from app.catalog.catalog import result_text
    text = result_text({"item": {"dueDate": "2026-11-13T02:00:00.000Z", "name": None}})
    assert "2026-11-13T09:00+07:00" in text and "13 พ.ย. 2569" in text
    assert "name" not in text  # ค่าว่างถูกตัดทิ้ง


def test_policy_defaults_fill_missing_args():
    spec = json.loads(json.dumps(SPEC))
    spec["components"]["schemas"]["CardBody"]["properties"]["position"] = {"type": "number"}
    cat = Catalog("t1", {"base_url": "http://host", "openapi": "x",
                         "policy": {"defaults": {"createCard": {"position": 65536, "name": "d"}}}},
                  spec)
    a = cat.actions["createCard"]
    assert cat.validate(a, {"listId": "l1"}) == []  # name มีค่าเริ่มต้นแล้ว
    _, _, body = cat._request_parts(a, {"listId": "l1", "name": "จริง"})
    assert body == {"name": "จริง", "position": 65536}  # ค่าที่โมเดลส่งชนะค่าเริ่มต้น


# ------------------------------------------------- กันโมเดลอ้างว่าทำสำเร็จ

@pytest.mark.parametrize("user_msg,reply,flagged", [
    ("ลบการ์ด อ่านบทที่ 3", "การ์ด \"อ่านบทที่ 3\" ได้ถูกลบเรียบร้อยแล้วครับ", True),
    ("สร้างการ์ดชื่อ A", "สร้างการ์ดให้แล้วครับ", True),
    ("ลบการ์ด X", "ลบไม่สำเร็จ เพราะไม่พบการ์ดชื่อนี้", False),
    ("ลบการ์ด X", "พบการ์ดชื่อ X สองใบ ต้องการลบใบไหนครับ", False),
    ("สัปดาห์นี้มีสอบอะไร", "นี่คือตารางสอบ เรียบร้อยครับ", False),  # ไม่ได้สั่งเขียน
])
def test_false_success_claim(user_msg, reply, flagged):
    ts = CatalogToolset(make_catalog([]))
    assert bool(ts.check_reply(reply, Ctx("t1", "tok"), user_msg)) is flagged


def test_success_claim_allowed_when_pending_exists():
    ts = CatalogToolset(make_catalog([]), seen_ids={"c1"})
    ctx = Ctx("t1", "tok")
    run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx))
    assert ts.check_reply("เตรียมลบเรียบร้อย กรุณากดยืนยัน", ctx, "ลบการ์ด") is None


def test_popup_warns_when_target_differs_from_user_words():
    ts = CatalogToolset(make_catalog([]), seen_ids={"c1"})
    ctx = Ctx("t1", "tok", user_msg="ลบการ์ด อ่านบทที่ 3")       # การ์ด c1 ชื่อ ทบทวนฐานข้อมูล
    text, _ = run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx))
    assert ctx.pending.summary.startswith("⚠") and "ไม่ตรง" in text

    ctx2 = Ctx("t1", "tok", user_msg="ลบการ์ด “ทบทวน ฐานข้อมูล”")
    run(ts.run("call_action", {"action_id": "deleteCard", "args": {"id": "c1"}}, ctx2))
    assert not ctx2.pending.summary.startswith("⚠")


def test_popup_shows_parent_name_for_create():
    reqs = []
    ts = CatalogToolset(make_catalog(reqs), seen_ids={"l1"})
    ctx = Ctx("t1", "tok", user_msg="สร้างการ์ด A")
    _, err = run(ts.run("call_action", {"action_id": "createCard",
                                        "args": {"listId": "l1", "name": "A"}}, ctx))
    assert not err
    assert "ใน “งานที่ต้องทำ”" in ctx.pending.summary
    assert ("POST", "/api/lists/l1/cards") not in reqs   # ยังไม่สร้างจริง


def test_create_on_collection_with_same_path_get():
    """ระบบแบบ Planka มี GET /lists/{listId}/cards (รายการ) ที่ path เดียวกับ POST สร้างการ์ด"""
    spec = json.loads(json.dumps(SPEC))
    spec["paths"]["/lists/{listId}/cards"]["get"] = {
        "operationId": "getCards", "summary": "Get cards", "tags": ["Cards"],
        "parameters": [{"name": "listId", "in": "path", "required": True, "schema": {"type": "string"}}]}
    cat = Catalog("t1", {"base_url": "http://host", "openapi": "x"}, spec)
    reqs = []
    cat.transport = make_catalog(reqs).transport
    ts = CatalogToolset(cat, seen_ids={"l1"})
    ctx = Ctx("t1", "tok", user_msg="สร้างการ์ด A")
    run(ts.run("call_action", {"action_id": "createCard", "args": {"listId": "l1", "name": "A"}}, ctx))
    assert "ใน “งานที่ต้องทำ”" in ctx.pending.summary and "⚠" not in ctx.pending.summary


def test_multipart_without_required_file_is_usable():
    spec = json.loads(json.dumps(SPEC))
    spec["paths"]["/projects/{projectId}/boards"] = {"post": {
        "operationId": "createBoard", "summary": "Create board", "tags": ["Boards"],
        "parameters": [{"name": "projectId", "in": "path", "required": True, "schema": {"type": "string"}}],
        "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
            "type": "object", "required": ["name", "position"],
            "properties": {"name": {"type": "string"}, "position": {"type": "number"},
                           "importFile": {"type": "string", "format": "binary"}}}}}}}}
    cat = Catalog("t1", {"base_url": "http://host", "openapi": "x"}, spec)
    a = cat.actions["createBoard"]
    assert a.body_format == "multipart"
    assert set(a.input_schema()["properties"]) == {"projectId", "name", "position"}  # ตัดช่องไฟล์ออก

    seen = {}

    def handler(request):
        seen["ctype"] = request.headers["content-type"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"item": {"id": "b1"}})
    cat.transport = httpx.MockTransport(handler)
    status, _ = run(cat.call(a, {"projectId": "p1", "name": "open", "position": 65536}, "tok"))
    assert status == 200 and seen["ctype"].startswith("multipart/form-data")
    assert 'name="name"' in seen["body"] and "open" in seen["body"]
