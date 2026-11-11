/*
 * AI Assistant widget (รุ่นทดลอง เฟส 3)
 * ฝังในหน้าเว็บใดก็ได้:
 *   <script src="http://localhost:8000/widget.js" data-tenant="planka-api" data-key="..."></script>
 * - data-api    : URL ของ assistant (ค่าเริ่มต้น = ที่อยู่ของไฟล์นี้)
 * - data-tenant : tenant id
 * - data-key    : public key ของ tenant (ฝังในหน้าเว็บได้ ใช้ได้เฉพาะ tenant นี้และเว็บที่อนุญาต)
 * ถ้า tenant ตั้งค่า widget.token (เช่นอ่านจาก cookie ของระบบหลัก) จะใช้ session ที่ผู้ใช้ล็อกอินอยู่แล้ว
 * ไม่ต้องล็อกอินซ้ำ และปุ่มแชตจะแสดงเฉพาะตอนที่ล็อกอินระบบหลักอยู่
 * ถ้าไม่ได้ตั้งค่า จะแสดงหน้าล็อกอินของ widget เอง
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

  function load(k) { try { return sessionStorage.getItem(STORE + k) || ""; } catch (e) { return ""; } }
  function save(k, v) { try { v ? sessionStorage.setItem(STORE + k, v) : sessionStorage.removeItem(STORE + k); } catch (e) {} }

  var state = {
    key: ds.key || load("key"),
    token: load("token"),
    session: load("session"),
    busy: false,
    hostToken: null,   // {from: "cookie", name: "..."} เมื่อใช้ session ของระบบหลัก
    lastToken: "",
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
    if (state.hostToken && state.hostToken.from === "cookie") return readCookie(state.hostToken.name);
    return state.token;
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
    '.panel[hidden]{display:none}' +
    '.head{background:#1f6b5c;color:#fff;padding:12px 14px;display:flex;align-items:center;gap:8px}' +
    '.head b{flex:1;font-size:15px}.head button{background:transparent;border:0;color:#fff;cursor:pointer;font-size:13px;opacity:.9}' +
    '.body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#f6f7f5;font-size:14px;line-height:1.6}' +
    '.msg{max-width:88%;padding:9px 12px;border-radius:12px;word-wrap:break-word;overflow-x:auto}' +
    '.me{align-self:flex-end;background:#1f6b5c;color:#fff;border-bottom-right-radius:4px;white-space:pre-wrap}' +
    '.bot{align-self:flex-start;background:#fff;border:1px solid #d9dfdb;border-bottom-left-radius:4px}' +
    '.bot p{margin:0 0 6px}.bot p:last-child{margin:0}.bot ul{margin:4px 0;padding-left:18px}' +
    '.bot table{border-collapse:collapse;font-size:12.5px;margin:4px 0}.bot th,.bot td{border:1px solid #d9dfdb;padding:3px 6px;text-align:left}' +
    '.sys{align-self:center;font-size:12.5px;color:#5d6963;text-align:center}' +
    '.err{align-self:stretch;background:#f8e3e1;color:#a8352d;border-radius:8px;padding:8px 10px;font-size:13px}' +
    '.confirm{align-self:stretch;background:#fff;border:2px solid #9a6a12;border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px}' +
    '.confirm.destructive{border-color:#a8352d}' +
    '.confirm .tag{font-size:12px;font-weight:600;color:#9a6a12}.confirm.destructive .tag{color:#a8352d}' +
    '.confirm .row{display:flex;gap:8px;justify-content:flex-end}' +
    '.btn{border:0;border-radius:8px;padding:7px 14px;cursor:pointer;font-size:13.5px}' +
    '.ok{background:#9a6a12;color:#fff}.destructive .ok{background:#a8352d}.cancel{background:#e7ebe8;color:#1d2421}' +
    '.btn[disabled]{opacity:.5;cursor:default}' +
    '.foot{display:flex;gap:8px;padding:10px;border-top:1px solid #d9dfdb;background:#fff}' +
    '.foot textarea{flex:1;resize:none;border:1px solid #d9dfdb;border-radius:8px;padding:8px;font-size:14px;height:42px}' +
    '.send{background:#1f6b5c;color:#fff}' +
    '.login{padding:18px;display:flex;flex-direction:column;gap:10px;font-size:14px;overflow-y:auto}' +
    '.login label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:#5d6963}' +
    '.login input{border:1px solid #d9dfdb;border-radius:8px;padding:8px;font-size:14px}' +
    '.dots::after{content:"";animation:d 1.2s steps(4) infinite}@keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}' +
    '@media (prefers-reduced-motion:reduce){.dots::after{animation:none;content:"..."}}' +
    '</style>' +
    '<button class="fab" id="fab" aria-label="เปิดผู้ช่วย AI" title="ผู้ช่วย AI">💬</button>' +
    '<section class="panel" id="panel" hidden aria-label="ผู้ช่วย AI">' +
    '  <div class="head"><b>ผู้ช่วย AI</b><button id="logout" hidden>ออกจากระบบ</button><button id="close" aria-label="ปิด">✕</button></div>' +
    '  <form class="login" id="login">' +
    '    <div>ล็อกอินด้วยบัญชีของระบบ (' + esc(TENANT) + ')</div>' +
    '    <label id="keyWrap">API key ของผู้ช่วย<input id="key" type="password" autocomplete="off"></label>' +
    '    <label>ชื่อผู้ใช้หรืออีเมล<input id="user" autocomplete="username" required></label>' +
    '    <label>รหัสผ่าน<input id="pass" type="password" autocomplete="current-password" required></label>' +
    '    <button class="btn send" id="loginBtn" type="submit">เข้าสู่ระบบ</button>' +
    '    <div class="err" id="loginErr" hidden></div>' +
    '  </form>' +
    '  <div class="body" id="body" hidden></div>' +
    '  <form class="foot" id="foot" hidden>' +
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

  function show() {
    var token = getToken(), logged = !!token;
    if (token !== state.lastToken) {        // เปลี่ยนผู้ใช้/ออกจากระบบหลัก: เริ่มบทสนทนาใหม่
      if (state.lastToken) { body.innerHTML = ""; state.session = ""; save("session", ""); }
      state.lastToken = token;
    }
    // ใช้ session ของระบบหลัก: ไม่ได้ล็อกอินระบบหลัก = ไม่แสดงแชต
    $("fab").hidden = !!state.hostToken && !logged;
    if ($("fab").hidden) panel.hidden = true;
    $("login").hidden = logged || !!state.hostToken;
    body.hidden = foot().hidden = !logged;
    $("logout").hidden = !logged || !!state.hostToken;
    $("keyWrap").hidden = !!ds.key;
    if (logged && !body.childElementCount) add("sys", "พร้อมช่วยแล้ว ลองพิมพ์ เช่น “สัปดาห์นี้มีสอบอะไรบ้าง”");
  }
  function foot() { return $("foot"); }

  // งานที่อาจต้องให้หน้าเว็บนี้เรียก API ระบบหลักแทนเซิร์ฟเวอร์ (ใช้ cookie/session ของผู้ใช้)
  // เซิร์ฟเวอร์ตอบ {turn_id, call} = ขอให้เรียก API นี้ แล้วส่งผลกลับที่ /turn/{turn_id} จนกว่างานจะเสร็จ
  async function work(path, payload) {
    if (state.hostToken) payload.client_exec = true;
    var d = await call(path, payload);
    while (d && d.call && d.turn_id) {
      var res = await hostFetch(d.call);
      d = await call("/turn/" + encodeURIComponent(d.turn_id), {
        tenant_id: TENANT, user_token: payload.user_token,
        call_id: d.call.call_id, status: res.status, body: res.body,
      });
    }
    return d;
  }

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
      var text = await r.text(), body = text;
      try { body = text ? JSON.parse(text) : {}; } catch (e) {}
      return { status: r.status, body: body };
    } catch (e) {
      return { status: 503, body: { message: "เรียกระบบหลักไม่สำเร็จ: " + e.message } };
    }
  }

  async function call(path, payload) {
    var r = await fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": state.key },
      body: JSON.stringify(payload),
    });
    var data = {};
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) {
      var detail = data.detail;
      if (typeof detail !== "string") detail = "เกิดข้อผิดพลาด (รหัส " + r.status + ")";
      var err = new Error(detail); err.status = r.status; throw err;
    }
    return data;
  }

  function setBusy(b) {
    state.busy = b;
    $("send").disabled = b;
    $("input").disabled = b;
  }

  // ---------------------------------------------------------------- login
  $("login").addEventListener("submit", async function (e) {
    e.preventDefault();
    var err = $("loginErr");
    err.hidden = true;
    if (!ds.key) state.key = $("key").value.trim();
    $("loginBtn").disabled = true;
    try {
      var d = await call("/login", { tenant_id: TENANT, username: $("user").value.trim(), password: $("pass").value });
      state.token = d.token;
      save("token", state.token);
      if (!ds.key) save("key", state.key);
      $("pass").value = "";
      show();
      $("input").focus();
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      $("loginBtn").disabled = false;
    }
  });

  $("logout").addEventListener("click", function () {
    state.token = state.session = "";
    save("token", ""); save("session", "");
    body.innerHTML = "";
    show();
  });

  // ----------------------------------------------------------------- chat
  async function send(text) {
    add("msg me", esc(text));
    var wait = add("sys", '<span class="dots">กำลังคิด</span>');
    setBusy(true);
    try {
      var d = await work("/chat", {
        tenant_id: TENANT, user_token: getToken(), message: text, session_id: state.session || null,
      });
      state.session = d.session_id;
      save("session", state.session);
      wait.remove();
      add("msg bot", md(d.reply || ""));
      if (d.pending_action) renderConfirm(d.pending_action);
    } catch (ex) {
      wait.remove();
      add("err", esc(ex.message));
      if (ex.status === 401 && /token/i.test(ex.message) && !state.hostToken) $("logout").click();
    } finally {
      setBusy(false);
      $("input").focus();
    }
  }

  // ป๊อปอัปยืนยัน: ข้อความ summary สร้างจากโค้ดฝั่งเซิร์ฟเวอร์ ไม่ใช่จากโมเดล
  function renderConfirm(pa) {
    var destructive = pa.risk === "destructive";
    var box = add("confirm" + (destructive ? " destructive" : ""),
      '<div class="tag">' + (destructive ? "ต้องยืนยัน · ลบแล้วย้อนกลับไม่ได้" : "ต้องยืนยันก่อนทำรายการ") + "</div>" +
      "<div>" + esc(pa.summary) + "</div>" +
      '<div class="row"><button class="btn cancel">ยกเลิก</button>' +
      '<button class="btn ok">' + (destructive ? "ยืนยันการลบ" : "ยืนยัน") + "</button></div>");
    var ok = box.querySelector(".ok"), cancel = box.querySelector(".cancel");
    var done = function (msg, isErr) {
      ok.remove(); cancel.remove();
      box.querySelector(".row").innerHTML = '<span class="' + (isErr ? "tag" : "") + '">' + esc(msg) + "</span>";
    };
    var payload = { tenant_id: TENANT, user_token: getToken(), action_id: pa.id };
    ok.addEventListener("click", async function () {
      ok.disabled = cancel.disabled = true;
      try { var d = await work("/confirm", payload); done("✓ " + d.message); }
      catch (ex) { done("ทำไม่สำเร็จ: " + ex.message, true); }
    });
    cancel.addEventListener("click", async function () {
      ok.disabled = cancel.disabled = true;
      try { await call("/cancel", payload); } catch (ex) {}
      done("ยกเลิกแล้ว ไม่มีการเปลี่ยนแปลง");
    });
    setTimeout(function () {
      if (ok.isConnected) done("หมดเวลายืนยันแล้ว กรุณาสั่งใหม่", true);
    }, (pa.expires_in || 300) * 1000);
  }

  foot().addEventListener("submit", function (e) {
    e.preventDefault();
    var t = $("input").value.trim();
    if (!t || state.busy) return;
    $("input").value = "";
    send(t);
  });
  $("input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      foot().requestSubmit();
    }
  });

  $("fab").addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) (state.token ? $("input") : $("user")).focus();
  });
  $("close").addEventListener("click", function () { panel.hidden = true; });

  // ดึงค่าตั้งของ tenant (ชื่อระบบ, ที่อยู่ของ token ในหน้าเว็บ)
  async function init() {
    try {
      var r = await fetch(API + "/widget/config/" + encodeURIComponent(TENANT), {
        headers: { "X-API-Key": state.key },
      });
      if (r.ok) {
        var cfg = await r.json();
        // data-auth="login" = บังคับใช้หน้าล็อกอินของ widget (เช่นหน้าทดสอบที่ไม่ได้อยู่ในระบบหลัก)
        state.hostToken = ds.auth === "login" ? null : (cfg.token || null);
        if (cfg.title) root.querySelector(".head b").textContent = "ผู้ช่วย AI · " + cfg.title;
      }
    } catch (e) { /* ใช้หน้าล็อกอินของ widget แทน */ }
    show();
    if (state.hostToken) setInterval(show, 2000);  // ตามการล็อกอิน/ออกจากระบบหลัก (SPA ไม่โหลดหน้าใหม่)
  }

  $("fab").hidden = true;
  init();
})();
