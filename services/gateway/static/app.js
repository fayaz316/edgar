"use strict";
const $ = (id) => document.getElementById(id);
const EXAMPLES = [
  "How do NVIDIA's and Apple's supply-chain risk disclosures differ in emphasis?",
  "How much commercial paper did Apple have outstanding in March 2026 and September 2025?",
  "What did China's antitrust regulators conclude about NVIDIA's Mellanox acquisition?",
  "What was Tesla's total revenue in 2025?"
];
EXAMPLES.forEach((text) => {
  const b = document.createElement("button");
  b.type = "button"; b.className = "chip"; b.textContent = text;
  b.addEventListener("click", () => { $("q").value = text; $("q").focus(); });
  $("examples").appendChild(b);
});

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;   // never innerHTML: model/filing text is untrusted
  return n;
}

function addTrace(ev) {
  $("trace-empty").hidden = true;
  const li = el("li");
  li.appendChild(el("span", "badge b-" + ev.kind, ev.kind));
  li.appendChild(el("span", "detail", ev.detail));
  li.appendChild(el("span", "secs", ev.seconds.toFixed(2) + "s"));
  const w = $("working"); if (w) w.remove();
  $("trace").appendChild(li);
  if (!$("done")) $("trace").appendChild(workingRow());
}
function workingRow() { const li = el("li", "working", "working…"); li.id = "working"; li.className = "working working-row"; return li; }

function appendText(box, text) {
  // **bold** only; everything is built with DOM nodes, never parsed as HTML
  text.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) box.appendChild(el("strong", "", part.slice(2, -2)));
    else box.appendChild(document.createTextNode(part));
  });
}
function renderAnswer(text, hasCitations) {
  const box = $("answer"); box.className = ""; box.replaceChildren();
  text.split(/(\[\d{1,2}(?:\s*,\s*\d{1,2})*\])/).forEach((part) => {
    const m = /^\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]$/.exec(part);
    if (!m) { appendText(box, part); return; }
    // "[12, 14]" becomes one chip per cited passage that exists
    m[1].split(",").map((s) => Number(s.trim())).forEach((n) => {
      if (hasCitations.has(n)) {
        const b = el("button", "cite", "[" + n + "]"); b.type = "button";
        b.setAttribute("aria-label", "Show passage " + n);
        b.addEventListener("click", () => focusPassage(n));
        box.appendChild(b);
      } else box.appendChild(document.createTextNode("[" + n + "]"));
    });
  });
}
function focusPassage(n) {
  const d = $("p" + n); if (!d) return;
  document.querySelectorAll(".passage.hl").forEach((x) => x.classList.remove("hl"));
  d.classList.add("hl"); d.querySelector("details").open = true;
  d.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function renderResult(r) {
  const w = $("working"); if (w) w.remove();
  const marker = el("li"); marker.id = "done"; marker.hidden = true; $("trace").appendChild(marker);
  const slot = $("status-slot"); slot.replaceChildren();
  slot.appendChild(el("span", "status " + (r.refused ? "refused" : "ok"),
    r.refused ? "Refused: not supported by the filings" : "Answered with citations"));
  renderAnswer(r.answer, new Set(r.citations.map((c) => c.passage)));
  $("stats").textContent = r.steps + " model turns · " + r.tool_calls + " tool calls · " + r.repairs + " repairs";
  const ev = $("evidence"); ev.className = ""; ev.replaceChildren();
  if (!r.citations.length) { ev.className = "empty"; ev.textContent = "This answer cites no passages."; return; }
  r.citations.forEach((c) => {
    const wrap = el("div", "passage"); wrap.id = "p" + c.passage;
    const d = el("details");
    d.appendChild(el("summary", "", "[" + c.passage + "]  " + c.ticker + " · " + c.form_type + " · filed " + c.filed_at + " · " + c.section));
    d.appendChild(el("pre", "", c.text || c.excerpt));
    wrap.appendChild(d); ev.appendChild(wrap);
  });
}

function parseSSE(buffer, onEvent) {
  const blocks = buffer.split("\n\n"); const rest = blocks.pop();
  blocks.forEach((blk) => {
    let name = "message", data = "";
    blk.split("\n").forEach((line) => {
      if (line.startsWith("event: ")) name = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    });
    if (data) onEvent(name, JSON.parse(data));
  });
  return rest;
}

try { $("key").value = sessionStorage.getItem("ea_key") || ""; } catch (_) { /* ignore */ }
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("q").value.trim(); if (question.length < 8) return;
  $("go").disabled = true; $("err").hidden = true;
  $("trace").replaceChildren(); $("trace-empty").hidden = true; $("trace").appendChild(workingRow());
  $("status-slot").replaceChildren(); $("stats").textContent = "";
  $("answer").className = "empty"; $("answer").textContent = "Working…";
  $("evidence").className = "empty"; $("evidence").textContent = "Passages the answer cites appear here.";
  try {
    const key = $("key").value.trim();
    try { sessionStorage.setItem("ea_key", key); } catch (_) { /* storage may be unavailable */ }
    const headers = { "content-type": "application/json" };
    if (key) headers["authorization"] = "Bearer " + key;
    const res = await fetch("/agent/stream", { method: "POST", headers, body: JSON.stringify({ question }) });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const wait = res.headers.get("retry-after");
      const msg = res.status === 401 ? "Invalid or missing API key. Paste your key above."
        : res.status === 429 ? ((body.detail || "Too many requests") + (wait ? " Try again in " + wait + "s." : ""))
        : (body.detail || ("Request failed (" + res.status + ")"));
      throw new Error(msg);
    }
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "", finished = false;
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf = parseSSE(buf + dec.decode(value, { stream: true }), (name, data) => {
        if (name === "trace") addTrace(data);
        else if (name === "result") { finished = true; renderResult(data); }
        else if (name === "error") throw new Error(data.detail);
      });
    }
    if (!finished) throw new Error("The stream ended before an answer arrived.");
  } catch (err) {
    const w = $("working"); if (w) w.remove();
    $("answer").className = "empty"; $("answer").textContent = "No answer.";
    $("err").textContent = err.message; $("err").hidden = false;
  } finally { $("go").disabled = false; }
});
