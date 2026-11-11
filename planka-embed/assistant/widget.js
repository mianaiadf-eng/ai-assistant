(function () {
  if (window.__aiAssistantLoaded) return;
  window.__aiAssistantLoaded = true;

  // ตั้งค่า (ทดสอบในเครื่องเท่านั้น: API_KEY อยู่ในหน้าเว็บ ใครก็เห็นได้)
  var API_URL = "http://127.0.0.1:8000";
  var API_KEY = "password123";
  var TENANT = "demo-uni";

  var KEY = "aiAssistant.session";
  var state = { token: null, sessionId: null, busy: false };
  try {
    var saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
    if (saved) { state.token = saved.token; state.sessionId = saved.sessionId; }
  } catch (e) {}

  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify({ token: state.token, sessionId: state.sessionId })); } catch (e) {}
  }

  var host = document.createElement("div");
  host.id = "ai-assistant-host";
  host.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483000;";
  var root = host.attachShadow({ mode: "open" });

  root.innerHTML =
    '<style>' +
    ':host{all:initial}' +
    '*{box-sizing:border-box;font-family:system-ui,"Segoe UI","Noto Sans Thai",sans-serif}' +
    '[hidden]{display:none!important}' +
    '.fab{width:56px;height:56px;border-radius:50%;border:0;background:#2bb59a;color:#fff;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;margin-left:auto}' +
    '.fab:hover{background:#25a38a}' +
    '.fab svg{width:28px;height:28px}' +
    '.panel{position:absolute;right:0;bottom:68px;width:380px;max-width:calc(100vw - 40px);height:540px;max-height:calc(100vh - 110px);background:#1f2430;color:#e6e9ef;border:1px solid #333b4d;border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.5);display:flex;flex-direction:column;overflow:hidden}' +
    '.head{display:flex;align-items:center;gap:8px;padding:12px 14px;background:#262d3b;border-bottom:1px solid #333b4d;font-weight:600}' +
    '.head .sp{flex:1}' +
    '.head button{background:none;border:0;color:#aab2c3;cursor:pointer;font-size:13px}' +
    '.head button:hover{color:#fff}' +
    '.login{padding:18px;display:flex;flex-direction:column;gap:10px}' +
    '.login p{margin:0 0 4px;color:#aab2c3;font-size:14px}' +
    'input{width:100%;padding:10px 12px;border-radius:8px;border:1px solid #3a4358;background:#171b24;color:#e6e9ef;font-size:14px;outline:none}' +
    'input:focus{border-color:#2bb59a}' +
    '.btn{padding:10px 14px;border:0;border-radius:8px;background:#2bb59a;color:#fff;font-weight:600;cursor:pointer;font-size:14px}' +
    '.btn:disabled{opacity:.5;cursor:default}' +
    '.btn.ghost{background:#333b4d}' +
    '.err{color:#ff8a8a;font-size:13px;min-height:16px}' +
    '.chat{flex:1;display:flex;flex-direction:column;min-height:0}' +
    '.msgs{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}' +
    '.m{max-width:88%;padding:8px 11px;border-radius:12px;font-size:14px;line-height:1.5;word-break:break-word}' +
    '.m.u{align-self:flex-end;background:#2bb59a;color:#fff;border-bottom-right-radius:3px}' +
    '.m.b{align-self:flex-start;background:#2b3345;border-bottom-left-radius:3px}' +
    '.m.e{align-self:flex-start;background:#4a2630;color:#ffb3b3}' +
    '.tw{overflow-x:auto;margin:4px 0}' +
    'table{border-collapse:collapse;font-size:13px}' +
    'th,td{border:1px solid #3a4358;padding:4px 8px;white-space:nowrap;text-align:left}' +
    'th{background:#333b4d}' +
    '.bar{display:flex;gap:8px;padding:10px;border-top:1px solid #333b4d;background:#262d3b}' +
    '.modal{position:absolute;inset:0;background:rgba(10,12,18,.75);display:flex;align-items:center;justify-content:center;padding:18px}' +
    '.card{background:#262d3b;border:1px solid #3a4358;border-radius:12px;padding:16px;width:100%}' +
    '.card h4{margin:0 0 8px;font-size:15px}' +
    '.card .sum{font-size:14px;line-height:1.5;margin-bottom:14px;color:#dfe4ee}' +
    '.card .row{display:flex;gap:8px;justify-content:flex-end}' +
    '</style>' +
    '<div class="panel" hidden>' +
    '  <div class="head"><span>ผู้ช่วย Planka</span><span class="sp"></span>' +
    '    <button class="logout" hidden>ออกจากระบบ</button><button class="close" aria-label="ปิด">✕</button></div>' +
    '  <form class="login">' +
    '    <p>เข้าสู่ระบบด้วยบัญชี Planka</p>' +
    '    <input class="u" placeholder="ชื่อผู้ใช้หรืออีเมล" autocomplete="username">' +
    '    <input class="p" type="password" placeholder="รหัสผ่าน" autocomplete="current-password">' +
    '    <div class="err lerr"></div>' +
    '    <button class="btn" type="submit">เข้าสู่ระบบ</button>' +
    '  </form>' +
    '  <div class="chat" hidden>' +
    '    <div class="msgs"></div>' +
    '    <form class="bar"><input class="t" placeholder="ถามเรื่องตารางสอบ หรือสั่งสร้างการ์ด" autocomplete="off">' +
    '      <button class="btn send" type="submit">ส่ง</button></form>' +
    '  </div>' +
    '  <div class="modal" hidden><div class="card"><h4>ยืนยันการดำเนินการ</h4>' +
    '    <div class="sum"></div><div class="err merr"></div>' +
    '    <div class="row"><button class="btn ghost no" type="button">ยกเลิก</button>' +
    '    <button class="btn yes" type="button">ยืนยัน</button></div></div></div>' +
    '</div>' +
    '<button class="fab" aria-label="เปิดผู้ช่วย"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg></button>';

  var $ = function (s) { return root.querySelector(s); };
  var panel = $(".panel"), fab = $(".fab"), loginForm = $(".login"), chatBox = $(".chat");
  var msgs = $(".msgs"), input = $(".t"), modal = $(".modal"), logoutBtn = $(".logout");
  var pendingAction = null;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function inline(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }
  function tableHtml(rows) {
    rows = rows.filter(function (r) { return !/^\s*\|[\s:\-|]+\|\s*$/.test(r); });
    var cells = rows.map(function (r) { return r.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); }); });
    if (!cells.length) return "";
    var h = "<div class='tw'><table><thead><tr>" + cells[0].map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") + "</tr></thead><tbody>";
    cells.slice(1).forEach(function (r) { h += "<tr>" + r.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>"; });
    return h + "</tbody></table></div>";
  }
  function md(text) {
    var lines = String(text).split("\n"), out = "", i = 0;
    while (i < lines.length) {
      if (/^\s*\|/.test(lines[i])) {
        var rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
        out += tableHtml(rows);
      } else { out += inline(lines[i++]) + "<br>"; }
    }
    return out;
  }

  function add(kind, text, html) {
    var d = document.createElement("div");
    d.className = "m " + kind;
    if (html) d.innerHTML = md(text); else d.textContent = text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function showView() {
    var logged = !!state.token;
    loginForm.hidden = logged; chatBox.hidden = !logged; logoutBtn.hidden = !logged;
    if (logged && !msgs.children.length) add("b", "สวัสดีค่ะ ถามเรื่องตารางสอบ หรือสั่งสร้างการ์ดได้เลย");
  }

  function logout(msg) {
    state.token = null; state.sessionId = null; save();
    msgs.innerHTML = ""; $(".lerr").textContent = msg || "";
    showView();
  }

  function api(path, body) {
    return fetch(API_URL + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) {
          var e = new Error(typeof j.detail === "string" ? j.detail : "เกิดข้อผิดพลาด (" + r.status + ")");
          e.status = r.status; throw e;
        }
        return j;
      });
    }, function () { throw new Error("เชื่อมต่อเซิร์ฟเวอร์ผู้ช่วยไม่ได้ ตรวจว่า uvicorn รันอยู่"); });
  }

  loginForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var b = loginForm.querySelector(".btn"); b.disabled = true; $(".lerr").textContent = "";
    api("/login", { tenant_id: TENANT, username: $(".u").value.trim(), password: $(".p").value })
      .then(function (j) { state.token = j.token; save(); $(".p").value = ""; showView(); input.focus(); })
      .catch(function (e) { $(".lerr").textContent = e.message; })
      .then(function () { b.disabled = false; });
  });

  $(".bar").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var text = input.value.trim();
    if (!text || state.busy) return;
    input.value = ""; add("u", text); state.busy = true;
    var wait = document.createElement("div"); wait.className = "m b"; wait.textContent = "กำลังคิด…";
    msgs.appendChild(wait); msgs.scrollTop = msgs.scrollHeight;
    api("/chat", { tenant_id: TENANT, user_token: state.token, message: text, session_id: state.sessionId })
      .then(function (j) {
        wait.remove(); state.sessionId = j.session_id; save();
        add("b", j.reply, true);
        if (j.pending_action) openModal(j.pending_action);
      })
      .catch(function (e) { wait.remove(); if (e.status === 401) logout("เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่"); else add("e", e.message); })
      .then(function () { state.busy = false; });
  });

  function openModal(p) {
    pendingAction = p; $(".sum").textContent = p.summary; $(".merr").textContent = "";
    $(".yes").disabled = false; modal.hidden = false;
  }
  function closeModal() { modal.hidden = true; pendingAction = null; }

  $(".yes").addEventListener("click", function () {
    if (!pendingAction) return;
    var btn = $(".yes"); btn.disabled = true;
    api("/confirm", { tenant_id: TENANT, user_token: state.token, action_id: pendingAction.id })
      .then(function (j) { closeModal(); add("b", "✅ " + j.message); })
      .catch(function (e) { $(".merr").textContent = e.message; btn.disabled = false; });
  });
  $(".no").addEventListener("click", function () {
    var p = pendingAction; closeModal();
    if (p) api("/cancel", { tenant_id: TENANT, user_token: state.token, action_id: p.id }).catch(function () {});
    add("b", "ยกเลิกแล้วค่ะ ยังไม่มีการเปลี่ยนแปลงใด ๆ");
  });

  fab.addEventListener("click", function () { panel.hidden = !panel.hidden; if (!panel.hidden) { showView(); (state.token ? input : $(".u")).focus(); } });
  $(".close").addEventListener("click", function () { panel.hidden = true; });
  logoutBtn.addEventListener("click", function () { logout(); });
  root.addEventListener("keydown", function (e) { if (e.key === "Escape") { if (!modal.hidden) $(".no").click(); else panel.hidden = true; } e.stopPropagation(); });

  document.body.appendChild(host);
})();
