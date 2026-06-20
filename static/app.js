// Employee kiosk logic

const $ = (id) => document.getElementById(id);

// --- live clock -------------------------------------------------------------
function tick() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString();
  $("today").textContent = now.toLocaleDateString(undefined, {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
}
setInterval(tick, 1000);
tick();

// --- helpers ----------------------------------------------------------------
function showMessage(text, kind) {
  const el = $("message");
  el.textContent = text;
  el.className = "message " + kind;
}

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function hoursBetween(a, b) {
  if (!a || !b) return "";
  const ms = new Date(b) - new Date(a);
  return (ms / 3600000).toFixed(2);
}

// --- clock in / out ---------------------------------------------------------
$("clock-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("email").value.trim();
  const pin = $("pin").value.trim();
  if (!email || !pin) return;

  $("clock-btn").disabled = true;
  try {
    const res = await fetch("/api/clock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, pin }),
    });
    const data = await res.json();
    if (!res.ok) {
      showMessage(data.error || "Something went wrong.", "error");
    } else {
      const verb = data.action === "in" ? "Clocked IN" : "Clocked OUT";
      const t = new Date(data.timestamp).toLocaleTimeString();
      showMessage(`${verb} — ${data.employee.name} at ${t}`, "success");
      $("pin").value = "";
    }
  } catch (err) {
    showMessage("Network error. Is the server running?", "error");
  } finally {
    $("clock-btn").disabled = false;
  }
});

// --- recent activity --------------------------------------------------------
$("history-btn").addEventListener("click", async () => {
  const email = $("email").value.trim();
  const pin = $("pin").value.trim();
  if (!email || !pin) {
    showMessage("Enter your email and PIN to view activity.", "info");
    return;
  }
  try {
    const res = await fetch("/api/history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, pin }),
    });
    const data = await res.json();
    if (!res.ok) {
      showMessage(data.error || "Could not load activity.", "error");
      return;
    }
    $("history-title").textContent = `Recent activity — ${data.employee.name}`;
    const body = $("history-body");
    body.innerHTML = "";
    if (!data.entries.length) {
      body.innerHTML = '<tr><td colspan="3" class="muted">No entries yet.</td></tr>';
    } else {
      for (const en of data.entries) {
        const tr = document.createElement("tr");
        tr.innerHTML =
          `<td>${fmtTime(en.clock_in)}</td>` +
          `<td>${en.clock_out ? fmtTime(en.clock_out) : '<span class="badge in">In progress</span>'}</td>` +
          `<td>${hoursBetween(en.clock_in, en.clock_out)}</td>`;
        body.appendChild(tr);
      }
    }
    $("history").classList.remove("hidden");
  } catch (err) {
    showMessage("Network error.", "error");
  }
});
