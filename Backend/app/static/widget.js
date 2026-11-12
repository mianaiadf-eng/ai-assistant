/*
 * AI Assistant widget (เชื่อมต่อแบบ WebSocket)
 * ฝังในหน้าเว็บใดก็ได้:
 *   <script src="http://localhost:8000/widget.js" data-tenant="planka-api" data-key="pk_..."></script>
 * - data-api    : URL ของ assistant (ค่าเริ่มต้น = ที่อยู่ของไฟล์นี้)
 * - data-tenant : client id (ระบบที่ฝัง widget)
 * - data-key    : public key ของ client (ฝังในหน้าเว็บได้ ใช้ได้เฉพาะ client นี้และเว็บที่อนุญาต)
 *
 * ตัวตนผู้ใช้:
 * - client ตั้งค่า widget.token (เช่น cookie ของระบบหลัก) -> ใช้ session ที่ผู้ใช้ล็อกอินอยู่แล้ว
 *   ปุ่มแชตแสดงเฉพาะตอนล็อกอินระบบหลักอยู่ และ API ของระบบนี้ถูกเรียกจากหน้าเว็บนี้ (cookie ของผู้ใช้)
 * - ไม่ตั้งค่า -> widget สร้างรหัสผู้ใช้ชั่วคราวเอง
 * ระบบอื่น ๆ ผู้ใช้ผูกบัญชีทีละระบบผ่าน auth กลาง (ฟอร์มจะขึ้นเองเมื่อจำเป็น)
 *
 * แสดงสถานะแบบเรียลไทม์ผ่าน WebSocket hub (เช่น "ส่งให้ผู้ช่วยของ Planka", "กำลังอ่านข้อมูล ...")
 * ใช้ Shadow DOM เพื่อไม่ให้ style ชนกับหน้าเว็บที่ฝัง
 */
(function () {
  "use strict";
  if (window.__aiAssistantLoaded) return;
  window.__aiAssistantLoaded = true;

  var script = document.currentScript;
  var ds = (script && script.dataset) || {};
  var API = (ds.api || (script ? new URL(script.src).origin : "http://localhost:8000")).replace(/\/$/, "");
  var TENANT = ds.tenant || "planka-api";
  var STORE = "aiAssistant:" + TENANT + ":";

  function load(k, persist) {
    try { return (persist ? localStorage : sessionStorage).getItem(STORE + k) || ""; } catch (e) { return ""; }
  }
  function save(k, v, persist) {
    try {
      var s = persist ? localStorage : sessionStorage;
      v ? s.setItem(STORE + k, v) : s.removeItem(STORE + k);
    } catch (e) {}
  }
  function randomId() {
    var a = new Uint8Array(18);
    window.crypto.getRandomValues(a);
    return "anon_" + Array.prototype.map.call(a, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }

  var state = {
    key: ds.key || load("key"),
    session: load("session"),
    busy: false,
    hostToken: null,     // {from: "cookie", name: "..."} เมื่อใช้ session ของระบบหลัก
    hostAgent: null,     // sub agent ของระบบที่ฝัง widget อยู่
    lastToken: "",
    ws: null,
    ready: false,
    retry: 0,
    seq: 0,
    waiting: {},         // req_id -> {resolve, reject}
    status: null,        // แถบสถานะของงานที่กำลังทำ
    agents: [],
  };

  function readCookie(name) {
    var parts = document.cookie ? document.cookie.split("; ") : [];
    for (var i = 0; i < parts.length; i++) {
      var eq = parts[i].indexOf("=");
      if (parts[i].slice(0, eq) === name) {
        try { return decodeURIComponent(parts[i].slice(eq + 1)); } catch (e) { return parts[i].slice(eq + 1); }
      }
    }
    return "";
  }

  function getToken() {
    if (state.hostToken) return state.hostToken.from === "cookie" ? readCookie(state.hostToken.name) : "";
    var id = load("anon", true);
    if (!id) { id = randomId(); save("anon", id, true); }
    return id;
  }

  // ------------------------------------------------------------------ UI
  var host = document.createElement("div");
  host.style.cssText = "position:fixed;right:0;bottom:0;z-index:2147483000;";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });

  root.innerHTML =
    '<style>' +
    ':host{all:initial}[hidden]{display:none!important}' +
    '*{box-sizing:border-box;font-family:"IBM Plex Sans Thai","Leelawadee UI",Tahoma,sans-serif}' +
    '.fab{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:0;' +
    'background:#1f6b5c;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 6px 18px rgba(0,0,0,.25)}' +
    '.fab:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid #6cc3ad;outline-offset:2px}' +
    '.panel{position:fixed;right:20px;bottom:88px;width:min(400px,calc(100vw - 32px));height:min(600px,calc(100vh - 120px));' +
    'background:#fff;color:#1d2421;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.28);display:flex;flex-direction:column;overflow:hidden}' +
    '.head{background:#1f6b5c;color:#fff;padding:12px 14px;display:flex;align-items:center;gap:8px}' +
    '.head b{flex:1;font-size:15px}.head button{background:transparent;border:0;color:#fff;cursor:pointer;font-size:13px;opacity:.9}' +
    '.conn{width:8px;height:8px;border-radius:50%;background:#e0a33a}.conn.on{background:#7fe0b4}' +
    '.agents{padding:8px 12px;border-bottom:1px solid #d9dfdb;display:flex;flex-wrap:wrap;gap:6px;font-size:12.5px;background:#fff}' +
    '.chip{border:1px solid #d9dfdb;border-radius:999px;padding:2px 10px;background:#f6f7f5;cursor:default}' +
    '.chip.off{border-style:dashed;color:#5d6963;cursor:pointer}' +
    '.body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#f6f7f5;font-size:14px;line-height:1.6}' +
    '.msg{flex-shrink:0;max-width:88%;padding:9px 12px;border-radius:12px;word-wrap:break-word;overflow-x:auto}' +
    '.me{align-self:flex-end;background:#1f6b5c;color:#fff;border-bottom-right-radius:4px;white-space:pre-wrap}' +
    '.bot{align-self:flex-start;background:#fff;border:1px solid #d9dfdb;border-bottom-left-radius:4px}' +
    '.bot .who{font-size:11.5px;color:#1f6b5c;font-weight:600;margin-bottom:2px}' +
    '.bot p{margin:0 0 6px}.bot p:last-child{margin:0}.bot ul{margin:4px 0;padding-left:18px}' +
    '.bot table{border-collapse:collapse;font-size:12.5px;margin:4px 0}.bot th,.bot td{border:1px solid #d9dfdb;padding:3px 6px;text-align:left}' +
    '.sys{align-self:center;font-size:12.5px;color:#5d6963;text-align:center}' +
    '.err{align-self:stretch;background:#f8e3e1;color:#a8352d;border-radius:8px;padding:8px 10px;font-size:13px}' +
    '.card{flex-shrink:0;align-self:stretch;background:#fff;border:2px solid #9a6a12;border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px}' +
    '.card.destructive{border-color:#a8352d}.card.link{border-color:#1f6b5c}' +
    '.card .tag{font-size:12px;font-weight:600;color:#9a6a12}.card.destructive .tag{color:#a8352d}.card.link .tag{color:#1f6b5c}' +
    '.card .row{display:flex;gap:8px;justify-content:flex-end}' +
    '.card label{display:flex;flex-direction:column;gap:3px;font-size:12.5px;color:#5d6963}' +
    '.card input{border:1px solid #d9dfdb;border-radius:8px;padding:7px;font-size:14px}' +
    '.btn{border:0;border-radius:8px;padding:7px 14px;cursor:pointer;font-size:13.5px}' +
    '.ok{background:#9a6a12;color:#fff}.destructive .ok{background:#a8352d}.link .ok{background:#1f6b5c}.cancel{background:#e7ebe8;color:#1d2421}' +
    '.btn[disabled]{opacity:.5;cursor:default}' +
    '.foot{display:flex;gap:8px;padding:10px;border-top:1px solid #d9dfdb;background:#fff}' +
    '.foot textarea{flex:1;resize:none;border:1px solid #d9dfdb;border-radius:8px;padding:8px;font-size:14px;height:42px}' +
    '.send{background:#1f6b5c;color:#fff}' +
    '.keyform{padding:18px;display:flex;flex-direction:column;gap:10px;font-size:14px}' +
    '.keyform label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:#5d6963}' +
    '.keyform input{border:1px solid #d9dfdb;border-radius:8px;padding:8px;font-size:14px}' +
    '.dots::after{content:"";animation:d 1.2s steps(4) infinite}@keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}' +
    '@media (prefers-reduced-motion:reduce){.dots::after{animation:none;content:"..."}}' +
    '</style>' +
    '<button class="fab" id="fab" aria-label="เปิดผู้ช่วย AI" title="ผู้ช่วย AI">💬</button>' +
    '<section class="panel" id="panel" hidden aria-label="ผู้ช่วย AI">' +
    '  <div class="head"><span class="conn" id="conn" title="กำลังเชื่อมต่อ"></span><b>ผู้ช่วย AI</b>' +
    '    <button id="reset" title="เริ่มบทสนทนาใหม่">ล้างแชต</button><button id="close" aria-label="ปิด">✕</button></div>' +
    '  <form class="keyform" id="keyform" hidden>' +
    '    <label>API key ของผู้ช่วย<input id="key" type="password" autocomplete="off" required></label>' +
    '    <button class="btn send" type="submit">เชื่อมต่อ</button>' +
    '  </form>' +
    '  <div class="agents" id="agents" hidden aria-label="ระบบที่ผู้ช่วยเข้าถึงได้"></div>' +
    '  <div class="body" id="body"></div>' +
    '  <form class="foot" id="foot">' +
    '    <textarea id="input" placeholder="พิมพ์สิ่งที่ต้องการ แล้วกด Enter" aria-label="ข้อความ"></textarea>' +
    '    <button class="btn send" id="send" type="submit">ส่ง</button>' +
    '  </form>' +
    '</section>';

  var $ = function (id) { return root.getElementById(id); };
  var panel = $("panel"), body = $("body");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // มาร์กดาวน์แบบง่าย: ตาราง, รายการ, ตัวหนา (escape HTML ก่อนเสมอ กันสคริปต์จากข้อมูลระบบ)
  function md(text) {
    var lines = esc(text).split("\n"), out = [], i = 0;
    var inline = function (s) { return s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); };
    while (i < lines.length) {
      var l = lines[i];
      if (/^\s*\|.*\|\s*$/.test(l)) {
        var rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
        var cells = function (r) { return r.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return inline(c.trim()); }); };
        var html = "<table>", first = true;
        rows.forEach(function (r) {
          if (/^\s*\|[\s:\-|]+\|\s*$/.test(r)) return;
          var tag = first ? "th" : "td"; first = false;
          html += "<tr>" + cells(r).map(function (c) { return "<" + tag + ">" + c + "</" + tag + ">"; }).join("") + "</tr>";
        });
        out.push(html + "</table>");
        continue;
      }
      if (/^\s*[-*•]\s+/.test(l)) {
        var items = [];
        while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) items.push("<li>" + inline(lines[i++].replace(/^\s*[-*•]\s+/, "")) + "</li>");
        out.push("<ul>" + items.join("") + "</ul>");
        continue;
      }
      if (l.trim()) out.push("<p>" + inline(l) + "</p>");
      i++;
    }
    return out.join("");
  }

  function add(cls, html) {
    var d = document.createElement("div");
    d.className = cls;
    d.innerHTML = html;
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
    return d;
  }

  function setBusy(b) {
    state.busy = b;
    $("send").disabled = b || !state.ready;
    $("input").disabled = b;
  }

  // ------------------------------------------------------------ WebSocket
  function wsUrl() {
    return API.replace(/^http/, "ws") + "/ws?tenant=" + encodeURIComponent(TENANT) +
      "&key=" + encodeURIComponent(state.key || "");
  }

  function setConn(on, title) {
    $("conn").className = "conn" + (on ? " on" : "");
    $("conn").title = title;
    state.ready = on;
    setBusy(state.busy);
  }

  function connect() {
    if (!state.key) { show(); return; }
    if (state.ws) return;
    var ws;
    try { ws = new WebSocket(wsUrl()); } catch (e) { setConn(false, "เชื่อมต่อไม่ได้"); return; }
    state.ws = ws;
    setConn(false, "กำลังเชื่อมต่อ");
    ws.onopen = function () { state.retry = 0; hello(); };
    ws.onmessage = function (ev) {
      var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      onEvent(m);
    };
    ws.onclose = function (ev) {
      if (state.ws !== ws) return;
      state.ws = null;
      setConn(false, "หลุดการเชื่อมต่อ");
      Object.keys(state.waiting).forEach(function (id) {
        state.waiting[id].reject(new Error("การเชื่อมต่อหลุด กรุณาลองใหม่"));
      });
      state.waiting = {};
      if (ev.code === 4401 || ev.code === 4403) {     // key ผิด / เว็บไม่ได้รับอนุญาต: ไม่ต่อใหม่
        if (!ds.key) { state.key = ""; save("key", ""); show(); }
        return;
      }
      var delay = Math.min(30000, 1000 * Math.pow(2, state.retry++));
      setTimeout(connect, delay);
    };
  }

  function raw(msg) {
    if (state.ws && state.ws.readyState === 1) state.ws.send(JSON.stringify(msg));
  }

  function request(msg) {
    return new Promise(function (resolve, reject) {
      if (!state.ws || state.ws.readyState !== 1) { reject(new Error("ยังไม่ได้เชื่อมต่อผู้ช่วย")); return; }
      msg.req_id = "r" + (++state.seq);
      state.waiting[msg.req_id] = { resolve: resolve, reject: reject };
      raw(msg);
    });
  }

  function hello() {
    var token = getToken();
    if (!token) return;
    request({ type: "hello", user_token: token }).then(function () {}, function () {});
  }

  function onEvent(m) {
    if (m.type === "call") { hostFetch(m).then(function (res) {
      raw({ type: "call_result", call_id: m.call_id, status: res.status, body: res.body });
    }); return; }
    if (m.type === "status") {
      if (state.status) state.status.innerHTML = '<span class="dots">' + esc(m.text) + "</span>";
      return;
    }
    if (m.type === "ready") { setConn(true, "เชื่อมต่อแล้ว"); renderAgents(m.agents); }
    if (m.type === "linked") renderAgents(m.agents);
    if (m.type === "error" && !m.req_id) { add("err", esc(m.detail || "เกิดข้อผิดพลาด")); return; }
    var w = m.req_id && state.waiting[m.req_id];
    if (!w) return;
    delete state.waiting[m.req_id];
    if (m.type === "error") {
      var err = new Error(m.detail || "เกิดข้อผิดพลาด"); err.status = m.status; w.reject(err);
    } else w.resolve(m);
  }

  // งานที่ผู้ช่วยขอให้หน้าเว็บนี้เรียก API ของระบบนี้แทนเซิร์ฟเวอร์ (ใช้ cookie/session ของผู้ใช้)
  async function hostFetch(c) {
    // รับเฉพาะ path ภายในเว็บนี้ (กันการถูกสั่งให้ส่ง token ไปเว็บอื่น)
    if (typeof c.path !== "string" || !/^\/(?!\/)/.test(c.path) || c.path.indexOf("\\") !== -1) {
      return { status: 400, body: { message: "path ไม่ถูกต้อง" } };
    }
    var method = String(c.method || "GET").toUpperCase();
    var url = new URL(c.path, location.origin);
    Object.keys(c.query || {}).forEach(function (k) { url.searchParams.set(k, c.query[k]); });
    if (url.origin !== location.origin) return { status: 400, body: { message: "origin ไม่ถูกต้อง" } };
    var opts = {
      method: method,
      credentials: "same-origin",
      headers: { "Authorization": "Bearer " + getToken() },
    };
    if (c.body !== null && c.body !== undefined && method !== "GET") {
      var formVal = function (v) {
        return typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
      };
      if (c.format === "multipart") {
        var fd = new FormData();   // เบราว์เซอร์ใส่ Content-Type พร้อม boundary ให้เอง
        Object.keys(c.body).forEach(function (k) { fd.append(k, formVal(c.body[k])); });
        opts.body = fd;
      } else if (c.format === "form") {
        var sp = new URLSearchParams();
        Object.keys(c.body).forEach(function (k) { sp.append(k, formVal(c.body[k])); });
        opts.body = sp;
      } else {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(c.body);
      }
    }
    try {
      var r = await fetch(url.toString(), opts);
      var text = await r.text(), data = text;
      try { data = text ? JSON.parse(text) : {}; } catch (e) {}
      return { status: r.status, body: data };
    } catch (e) {
      return { status: 503, body: { message: "เรียกระบบหลักไม่สำเร็จ: " + e.message } };
    }
  }

  // ---------------------------------------------------------- ระบบที่เข้าถึงได้
  function renderAgents(list) {
    state.agents = list || [];
    var box = $("agents");
    box.innerHTML = "";
    box.hidden = state.agents.length < 2;
    state.agents.forEach(function (a) {
      var chip = document.createElement("span");
      chip.className = "chip" + (a.linked ? "" : " off");
      chip.textContent = (a.linked ? "✓ " : "+ ") + a.title;
      if (!a.linked && a.can_login) {
        chip.title = "ผูกบัญชี " + a.title;
        chip.tabIndex = 0;
        chip.setAttribute("role", "button");
        var open = function () { renderLink(a); };
        chip.addEventListener("click", open);
        chip.addEventListener("keydown", function (e) { if (e.key === "Enter") open(); });
      } else chip.title = a.linked ? "เชื่อมต่อแล้ว" : "ยังไม่ได้เชื่อมต่อ";
      box.appendChild(chip);
    });
  }

  // ฟอร์มผูกบัญชีระบบอื่น (auth กลาง): รหัสผ่านส่งไปล็อกอินระบบนั้นครั้งเดียว ผู้ช่วยเก็บแค่ token
  function renderLink(a) {
    var box = add("card link",
      '<div class="tag">ผูกบัญชี ' + esc(a.title) + "</div>" +
      "<div>ล็อกอินด้วยบัญชีของระบบนี้ เพื่อให้ผู้ช่วยทำรายการแทนคุณได้</div>" +
      '<label>ชื่อผู้ใช้หรืออีเมล<input class="u" autocomplete="username"></label>' +
      '<label>รหัสผ่าน<input class="p" type="password" autocomplete="current-password"></label>' +
      '<div class="row"><button class="btn cancel">ปิด</button><button class="btn ok">เข้าสู่ระบบ</button></div>');
    var ok = box.querySelector(".ok"), cancel = box.querySelector(".cancel");
    var u = box.querySelector(".u"), p = box.querySelector(".p");
    u.focus();
    cancel.addEventListener("click", function () { box.remove(); });
    var submit = async function () {
      if (!u.value.trim() || !p.value) return;
      ok.disabled = cancel.disabled = true;
      try {
        await request({ type: "link", agent: a.name, username: u.value.trim(), password: p.value });
        box.innerHTML = '<div class="tag">✓ ผูกบัญชี ' + esc(a.title) + " แล้ว ลองสั่งงานอีกครั้งได้เลย</div>";
      } catch (ex) {
        ok.disabled = cancel.disabled = false;
        p.value = "";
        var e = box.querySelector(".err") || box.appendChild(document.createElement("div"));
        e.className = "err"; e.textContent = ex.message;
      }
    };
    ok.addEventListener("click", submit);
    p.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); });
  }

  // ----------------------------------------------------------------- chat
  async function send(text) {
    add("msg me", esc(text));
    state.status = add("sys", '<span class="dots">กำลังคิด</span>');
    setBusy(true);
    try {
      var d = await request({ type: "chat", message: text, session_id: state.session || null });
      state.session = d.session_id;
      save("session", state.session);
      state.status.remove();
      var who = d.agent_title && state.agents.length > 1 ? '<div class="who">' + esc(d.agent_title) + "</div>" : "";
      add("msg bot", who + md(d.reply || ""));
      if (d.pending_action) renderConfirm(d.pending_action);
      if (d.link_required) {
        if (d.link_required.can_login) renderLink(d.link_required);
        else add("sys", "ระบบนี้ผูกบัญชีผ่านผู้ช่วยไม่ได้ กรุณาติดต่อผู้ดูแลระบบ");
      }
    } catch (ex) {
      state.status.remove();
      add("err", esc(ex.message));
    } finally {
      state.status = null;
      setBusy(false);
      $("input").focus();
    }
  }

  // ป๊อปอัปยืนยัน: ข้อความ summary สร้างจากโค้ดฝั่งเซิร์ฟเวอร์ ไม่ใช่จากโมเดล
  function renderConfirm(pa) {
    var destructive = pa.risk === "destructive";
    var box = add("card" + (destructive ? " destructive" : ""),
      '<div class="tag">' + (destructive ? "ต้องยืนยัน · ลบแล้วย้อนกลับไม่ได้" : "ต้องยืนยันก่อนทำรายการ") + "</div>" +
      "<div>" + esc(pa.summary) + "</div>" +
      '<div class="row"><button class="btn cancel">ยกเลิก</button>' +
      '<button class="btn ok">' + (destructive ? "ยืนยันการลบ" : "ยืนยัน") + "</button></div>");
    var ok = box.querySelector(".ok"), cancel = box.querySelector(".cancel");
    var done = function (msg, isErr) {
      ok.remove(); cancel.remove();
      box.querySelector(".row").innerHTML = '<span class="' + (isErr ? "tag" : "") + '">' + esc(msg) + "</span>";
    };
    ok.addEventListener("click", async function () {
      ok.disabled = cancel.disabled = true;
      state.status = add("sys", '<span class="dots">กำลังทำรายการ</span>');
      try {
        var d = await request({ type: "confirm", action_id: pa.id });
        done("✓ " + d.message);
        if ((d.agent || pa.agent) === state.hostAgent) hostChanged(box, pa);
      }
      catch (ex) { done("ทำไม่สำเร็จ: " + ex.message, true); }
      finally { if (state.status) state.status.remove(); state.status = null; }
    });
    cancel.addEventListener("click", async function () {
      ok.disabled = cancel.disabled = true;
      try { await request({ type: "cancel", action_id: pa.id }); } catch (ex) {}
      done("ยกเลิกแล้ว ไม่มีการเปลี่ยนแปลง");
    });
    setTimeout(function () {
      if (ok.isConnected) done("หมดเวลายืนยันแล้ว กรุณาสั่งใหม่", true);
    }, (pa.expires_in || 300) * 1000);
  }

  // ข้อมูลของระบบที่ฝัง widget เปลี่ยนแล้ว แต่หน้าเว็บอาจยังแสดงของเดิม
  // - หน้าเว็บที่อัปเดตตัวเองได้: ฟัง "ai-assistant:changed" แล้วเรียก event.preventDefault()
  // - ไม่มีใครรับ: แสดงปุ่มรีเฟรชหน้า (เก็บข้อความแชตไว้ ไม่ให้หายตอนโหลดใหม่)
  function hostChanged(box, pa) {
    var ev = new CustomEvent("ai-assistant:changed", {
      cancelable: true, detail: { agent: state.hostAgent, tool: pa.tool, risk: pa.risk },
    });
    if (!window.dispatchEvent(ev)) return;
    var btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = "รีเฟรชหน้าเพื่อดูข้อมูลล่าสุด";
    btn.addEventListener("click", function () {
      btn.remove();
      save("transcript", body.innerHTML);
      location.reload();
    });
    box.querySelector(".row").appendChild(btn);
  }

  function restoreTranscript() {
    var html = load("transcript");
    if (!html) return;
    save("transcript", "");
    body.innerHTML = html;
    // ปุ่มของกล่องยืนยันที่ค้างอยู่ใช้ต่อไม่ได้หลังโหลดหน้าใหม่
    Array.prototype.forEach.call(body.querySelectorAll(".card .btn"), function (b) { b.remove(); });
    body.scrollTop = body.scrollHeight;
  }

  // ------------------------------------------------------------- สถานะหน้าจอ
  function show() {
    var token = getToken(), logged = !!token;
    if (token !== state.lastToken) {        // เปลี่ยนผู้ใช้/ออกจากระบบหลัก: เริ่มบทสนทนาใหม่
      if (state.lastToken) { body.innerHTML = ""; state.session = ""; save("session", ""); }
      state.lastToken = token;
      if (logged) hello();
    }
    // ใช้ session ของระบบหลัก: ไม่ได้ล็อกอินระบบหลัก = ไม่แสดงแชต
    $("fab").hidden = !logged;
    if (!logged) panel.hidden = true;
    var needKey = !state.key;
    $("keyform").hidden = !needKey;
    body.hidden = $("foot").hidden = needKey;
    if (!needKey && logged && !body.childElementCount) {
      add("sys", "พร้อมช่วยแล้ว ลองพิมพ์ เช่น “สัปดาห์นี้มีสอบอะไรบ้าง”");
    }
  }

  $("keyform").addEventListener("submit", function (e) {
    e.preventDefault();
    state.key = $("key").value.trim();
    save("key", state.key);
    $("key").value = "";
    init();
  });

  $("foot").addEventListener("submit", function (e) {
    e.preventDefault();
    var t = $("input").value.trim();
    if (!t || state.busy || !state.ready) return;
    $("input").value = "";
    send(t);
  });
  $("input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("foot").requestSubmit();
    }
  });

  $("fab").addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) (state.key ? $("input") : $("key")).focus();
  });
  $("close").addEventListener("click", function () { panel.hidden = true; });
  $("reset").addEventListener("click", function () {
    body.innerHTML = ""; state.session = ""; save("session", ""); show();
  });

  // ดึงค่าตั้งของ client (ชื่อระบบ, ที่อยู่ของ token ในหน้าเว็บ) แล้วต่อ WebSocket
  var watching = false;
  async function init() {
    if (!state.key) { show(); return; }
    try {
      var r = await fetch(API + "/widget/config/" + encodeURIComponent(TENANT), {
        headers: { "X-API-Key": state.key },
      });
      if (r.ok) {
        var cfg = await r.json();
        state.hostToken = cfg.token || null;
        state.hostAgent = cfg.host_agent || null;
        if (cfg.title) root.querySelector(".head b").textContent = "ผู้ช่วย AI · " + cfg.title;
      }
    } catch (e) { /* ใช้รหัสผู้ใช้ชั่วคราวแทน */ }
    state.lastToken = getToken();
    restoreTranscript();
    show();
    connect();
    if (state.hostToken && !watching) {   // ตามการล็อกอิน/ออกจากระบบหลัก (SPA ไม่โหลดหน้าใหม่)
      watching = true;
      setInterval(show, 2000);
    }
  }

  $("fab").hidden = true;
  setBusy(false);
  init();
})();
