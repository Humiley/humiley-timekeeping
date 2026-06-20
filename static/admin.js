// Admin dashboard logic

const $ = (id) => document.getElementById(id);
let TOKEN = sessionStorage.getItem("tk_token") || null;

// --- API helper -------------------------------------------------------------
async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (TOKEN) headers["Authorization"] = "Bearer " + TOKEN;
  if (opts.body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    logout();
    throw new Error("Session expired. Please sign in again.");
  }
  return res;
}

function fmt(iso) { return iso ? new Date(iso).toLocaleString() : "—"; }
function fmtT(iso) { return iso ? new Date(iso).toLocaleTimeString() : ""; }
function hours(a, b) { return a && b ? ((new Date(b) - new Date(a)) / 3600000).toFixed(2) : ""; }

// --- auth -------------------------------------------------------------------
function showDash() {
  $("login-view").classList.add("hidden");
  $("dash-view").classList.remove("hidden");
  $("logout-btn").classList.remove("hidden");
  loadOverview();
}
function logout() {
  TOKEN = null;
  sessionStorage.removeItem("tk_token");
  $("dash-view").classList.add("hidden");
  $("logout-btn").classList.add("hidden");
  $("login-view").classList.remove("hidden");
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("login-email").value.trim();
  const pin = $("login-pin").value.trim();
  const msg = $("login-message");
  try {
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, pin }),
    });
    const data = await res.json();
    if (!res.ok) {
      msg.textContent = data.error || "Login failed.";
      msg.className = "message error";
      return;
    }
    TOKEN = data.token;
    sessionStorage.setItem("tk_token", TOKEN);
    msg.className = "message hidden";
    showDash();
  } catch (err) {
    msg.textContent = "Network error.";
    msg.className = "message error";
  }
});

$("logout-btn").addEventListener("click", logout);

// --- tabs -------------------------------------------------------------------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const name = tab.dataset.tab;
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.add("hidden"));
    $("tab-" + name).classList.remove("hidden");
    if (name === "overview") loadOverview();
    if (name === "entries") loadEntries();
    if (name === "employees") loadEmployees();
  });
});

// --- overview ---------------------------------------------------------------
async function loadOverview() {
  try {
    const empRes = await api("/api/admin/employees");
    const { employees } = await empRes.json();
    $("stat-total").textContent = employees.length;
    $("stat-in").textContent = employees.filter((e) => e.clocked_in).length;

    const qs = rangeQS("ov");
    const sumRes = await api("/api/admin/summary" + qs);
    const { summary } = await sumRes.json();
    let totalSec = 0;
    const body = $("summary-body");
    body.innerHTML = "";
    if (!summary.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">No data for this range.</td></tr>';
    }
    for (const s of summary) {
      totalSec += s.seconds;
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${esc(s.name)}</td><td>${esc(s.email)}</td><td>${s.sessions}</td>` +
        `<td>${(s.seconds / 3600).toFixed(2)}</td>` +
        `<td>${s.open ? '<span class="badge in">Clocked in</span>' : '<span class="badge out">Out</span>'}</td>`;
      body.appendChild(tr);
    }
    $("stat-hours").textContent = (totalSec / 3600).toFixed(1);
  } catch (err) {
    alert(err.message);
  }
}
$("ov-apply").addEventListener("click", loadOverview);

// --- entries ----------------------------------------------------------------
async function loadEntries() {
  try {
    const qs = rangeQS("en");
    const res = await api("/api/admin/entries" + qs);
    const { entries } = await res.json();
    const body = $("entries-body");
    body.innerHTML = "";
    if (!entries.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">No entries for this range.</td></tr>';
    }
    for (const e of entries) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${esc(e.employee_name)}</td><td>${fmt(e.clock_in)}</td>` +
        `<td>${e.clock_out ? fmt(e.clock_out) : '<span class="badge in">In progress</span>'}</td>` +
        `<td>${hours(e.clock_in, e.clock_out)}</td><td>${esc(e.note || "")}</td>`;
      body.appendChild(tr);
    }
    $("en-export").href = "/api/admin/export.csv" + rangeQS("en");
  } catch (err) {
    alert(err.message);
  }
}
$("en-apply").addEventListener("click", loadEntries);
$("en-export").addEventListener("click", async (e) => {
  // fetch with auth header, then trigger a download (href alone can't send the token)
  e.preventDefault();
  try {
    const res = await api("/api/admin/export.csv" + rangeQS("en"));
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "timekeeping-export.csv";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(err.message);
  }
});

// --- employees --------------------------------------------------------------
async function loadEmployees() {
  try {
    const res = await api("/api/admin/employees");
    const { employees } = await res.json();
    const body = $("employees-body");
    body.innerHTML = "";
    for (const e of employees) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${esc(e.name)}</td><td>${esc(e.email)}</td>` +
        `<td>${e.is_admin ? '<span class="badge admin">Admin</span>' : "Employee"}</td>` +
        `<td>${e.active ? '<span class="badge in">Active</span>' : '<span class="badge inactive">Inactive</span>'}</td>` +
        `<td>${e.clocked_in ? '<span class="badge in">In</span>' : '<span class="badge out">Out</span>'}</td>` +
        `<td><button class="btn small edit-btn">Edit</button></td>`;
      tr.querySelector(".edit-btn").addEventListener("click", () => openModal(e));
      body.appendChild(tr);
    }
  } catch (err) {
    alert(err.message);
  }
}

// --- modal ------------------------------------------------------------------
function openModal(emp) {
  $("emp-message").className = "message hidden";
  if (emp) {
    $("emp-modal-title").textContent = "Edit employee";
    $("emp-id").value = emp.id;
    $("emp-name").value = emp.name;
    $("emp-email").value = emp.email;
    $("emp-pin").value = "";
    $("emp-pin-label").childNodes[0].nodeValue = "New PIN (leave blank to keep) ";
    $("emp-admin").checked = emp.is_admin;
    $("emp-active").checked = emp.active;
    $("emp-active-label").classList.remove("hidden");
  } else {
    $("emp-modal-title").textContent = "Add employee";
    $("emp-id").value = "";
    $("emp-form").reset();
    $("emp-pin-label").childNodes[0].nodeValue = "PIN (4+ digits) ";
    $("emp-active").checked = true;
    $("emp-active-label").classList.add("hidden");
  }
  $("emp-modal").classList.remove("hidden");
}
function closeModal() { $("emp-modal").classList.add("hidden"); }
$("add-emp-btn").addEventListener("click", () => openModal(null));
$("emp-cancel").addEventListener("click", closeModal);

$("emp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("emp-id").value;
  const payload = {
    name: $("emp-name").value.trim(),
    email: $("emp-email").value.trim(),
    is_admin: $("emp-admin").checked,
  };
  const pin = $("emp-pin").value.trim();
  if (pin) payload.pin = pin;
  const msg = $("emp-message");
  try {
    let res;
    if (id) {
      payload.active = $("emp-active").checked;
      res = await api("/api/admin/employees/" + id, { method: "PATCH", body: JSON.stringify(payload) });
    } else {
      if (!pin || pin.length < 4) {
        msg.textContent = "PIN must be at least 4 digits."; msg.className = "message error"; return;
      }
      res = await api("/api/admin/employees", { method: "POST", body: JSON.stringify(payload) });
    }
    const data = await res.json();
    if (!res.ok) {
      msg.textContent = data.error || "Save failed."; msg.className = "message error"; return;
    }
    closeModal();
    loadEmployees();
  } catch (err) {
    msg.textContent = err.message; msg.className = "message error";
  }
});

// --- utils ------------------------------------------------------------------
function rangeQS(prefix) {
  const start = $(prefix + "-start").value;
  const end = $(prefix + "-end").value;
  const p = [];
  if (start) p.push("start=" + encodeURIComponent(start));
  if (end) p.push("end=" + encodeURIComponent(end));
  return p.length ? "?" + p.join("&") : "";
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// --- boot -------------------------------------------------------------------
if (TOKEN) {
  // verify token still valid by attempting a protected call
  api("/api/admin/employees").then((r) => { if (r.ok) showDash(); else logout(); }).catch(logout);
}
