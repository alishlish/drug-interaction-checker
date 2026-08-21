const drugListEl = document.getElementById("drug-list");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

const addBtn = document.getElementById("add");
const swapBtn = document.getElementById("swap");
const clearBtn = document.getElementById("clear");
const checkBtn = document.getElementById("check");
const explainBtn = document.getElementById("explain");
const renalEl = document.getElementById("renal");
const hepaticEl = document.getElementById("hepatic");
const exampleBtns = [...document.querySelectorAll(".example")];

let rows = [];

function setStatus(msg) {
  statusEl.textContent = msg || "";
}

// Disable the action buttons and show a spinner-ish status while a request runs.
function setBusy(busy, label) {
  [checkBtn, explainBtn, swapBtn, clearBtn, addBtn, ...exampleBtns].forEach(
    (b) => b && (b.disabled = busy)
  );
  if (busy && label) setStatus(`${label}…`);
}

// Turn any failure into a human-readable line (503 = agent off, etc.).
function friendlyError(err) {
  const msg = String(err?.message || err);
  if (msg.startsWith("503")) return "AI analysis is not configured on this server (missing API keys).";
  if (msg.startsWith("400")) return "Please enter at least 2 valid drug names.";
  if (/Failed to fetch|NetworkError/i.test(msg)) return "Network error — is the server running?";
  return `Error: ${msg}`;
}

function clearResults() {
  resultsEl.innerHTML = "";
}

function escapeHtml(str) {
  return (str || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return await res.json();
}

async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return await res.json();
}

function getDrugValues() {
  return rows
    .map((r) => (r.value || "").trim().toLowerCase())
    .filter((v) => v.length > 0);
}

// --- Validation: mark "not found" inline using /drug/{name}
async function validateDrug(name) {
  const n = (name || "").trim().toLowerCase();
  if (!n) return { ok: false, reason: "empty" };

  try {
    const data = await fetchJson(`/drug/${encodeURIComponent(n)}`);
    return { ok: true, data };
  } catch (e) {
    // 404 -> not found
    return { ok: false, reason: "not_found" };
  }
}

function updateRowValidity(el, ok) {
  const pill = el.querySelector(".small-pill");
  if (ok) {
    el.classList.remove("invalid");
    pill.style.display = "none";
  } else {
    el.classList.add("invalid");
    pill.style.display = "inline-flex";
  }
}

function createRow(initialValue = "") {
  const id = crypto.randomUUID();
  const row = { id, value: initialValue, valid: null, details: null };

  const el = document.createElement("div");
  el.className = "drug-row";
  el.dataset.id = id;

  el.innerHTML = `
    <div class="row-top">
      <div class="label">
        Drug
        <span class="small-pill bad" style="display:none">Not found</span>
      </div>
      <button class="remove" type="button">remove</button>
    </div>
    <div class="input-wrap">
      <input type="text" placeholder="Start typing… (e.g., omeprazole)" value="${escapeHtml(initialValue)}" />
      <div class="suggestions" style="display:none"></div>
    </div>
  `;

  const input = el.querySelector("input");
  const suggestions = el.querySelector(".suggestions");
  const removeBtn = el.querySelector(".remove");

  let debounceTimer = null;

  async function fetchSuggestions(q) {
    if (!q || q.length < 2) return [];
    const data = await fetchJson(`/drugs?search=${encodeURIComponent(q)}`);
    return (data.matches || []).slice(0, 12);
  }

  function showSuggestions(items) {
    if (!items.length) {
      suggestions.style.display = "none";
      suggestions.innerHTML = "";
      return;
    }
    suggestions.style.display = "block";
    suggestions.innerHTML = items
      .map((x) => `<button type="button" data-val="${escapeHtml(x)}">${escapeHtml(x)}</button>`)
      .join("");
  }

  async function runValidation() {
    const q = (row.value || "").trim().toLowerCase();
    if (!q) {
      row.valid = null;
      row.details = null;
      updateRowValidity(el, true);
      return;
    }
    const v = await validateDrug(q);
    // If RxNorm resolved a brand/synonym to a dataset drug, swap the row to the
    // generic so /check and /analyze (which key on dataset names) both work.
    if (v.ok && v.data?.resolved_from && v.data.name && v.data.name !== q) {
      input.value = v.data.name;
      row.value = v.data.name;
      setStatus(`${v.data.resolved_from.input} → ${v.data.name} (via RxNorm)`);
    }
    row.valid = v.ok;
    row.details = v.ok ? v.data : null;
    updateRowValidity(el, v.ok);
  }

  input.addEventListener("input", () => {
    row.value = input.value;

    // clear invalid state while typing
    updateRowValidity(el, true);

    const q = input.value.trim().toLowerCase();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      try {
        const items = await fetchSuggestions(q);
        showSuggestions(items);
      } catch {
        showSuggestions([]);
      }
    }, 150);
  });

  suggestions.addEventListener("mousedown", async (e) => {
    e.preventDefault(); // prevents input blur before click registers
    const btn = e.target.closest("button");
    if (!btn) return;
    const val = btn.dataset.val;
    input.value = val;
    row.value = val;
    showSuggestions([]);
    await runValidation();
  });

  input.addEventListener("blur", async () => {
    setTimeout(() => showSuggestions([]), 120);
    await runValidation();
  });

  removeBtn.addEventListener("click", () => {
    rows = rows.filter((r) => r.id !== id);
    el.remove();
  });

  drugListEl.appendChild(el);
  rows.push(row);
}

function setRowValue(index, value) {
  const row = rows[index];
  if (!row) return;
  row.value = value;

  const el = [...drugListEl.children].find((x) => x.dataset.id === row.id);
  if (!el) return;
  const input = el.querySelector("input");
  input.value = value;
}

function ensureTwoRows() {
  while (rows.length < 2) createRow("");
}

function clearAll() {
  ensureTwoRows();
  // remove extra rows beyond 2
  while (rows.length > 2) {
    const r = rows.pop();
    const el = [...drugListEl.children].find((x) => x.dataset.id === r.id);
    if (el) el.remove();
  }
  // clear both
  setRowValue(0, "");
  setRowValue(1, "");
  // reset validity UI
  [...drugListEl.children].forEach((el) => {
    el.classList.remove("invalid");
    const pill = el.querySelector(".small-pill");
    if (pill) pill.style.display = "none";
  });
  clearResults();
  setStatus("");
}

function swapFirstTwo() {
  ensureTwoRows();
  const a = (rows[0].value || "");
  const b = (rows[1].value || "");
  setRowValue(0, b);
  setRowValue(1, a);
  // clear results since it’s a new query
  clearResults();
  setStatus("swapped ✅");
}

async function hydrateDrugDetails(drugs) {
  // fetch /drug/{name} for each entered drug (only those that exist)
  const map = {};
  for (const d of drugs) {
    try {
      map[d] = await fetchJson(`/drug/${encodeURIComponent(d)}`);
    } catch {
      map[d] = null;
    }
  }
  return map;
}

function renderResults(data, drugDetailsMap, clear = true) {
  if (clear) clearResults();
  const interactions = data?.interactions || [];
  if (!interactions.length) {
    resultsEl.innerHTML = `<div class="result"><div class="text">No results.</div></div>`;
    return;
  }

  interactions.forEach((it) => {
    const sev = (it.severity || "none").toLowerCase();
    const pair = it.drug_pair || [];
    const pairText = pair.join(" + ");
    const explanation = it.llm_explanation;
    const ev = it.evidence || {};

    // Guardrail made visible: an unknown drug means the pair was NOT screened —
    // shown as an explicit state, not a hidden error or a silent substitution.
    if (ev.type === "missing_drug") {
      const g = document.createElement("div");
      g.className = "result guardrail";
      g.innerHTML = `
        <div class="badge guard">not screened</div>
        <div class="pair">${escapeHtml(pairText)}</div>
        <div class="text">One or more of these drugs is not in the dataset, so this pair was not screened. No substitution or guess was made.</div>`;
      resultsEl.appendChild(g);
      return;
    }

    // ✅ reference DDI callout (per interaction)
    let evHtml = "";
    if (ev.type === "reference_ddi") {
      evHtml = `
        <div class="callout">
          <div class="callout-title">Dataset reference interaction</div>
          <div class="kv">
            <div><span>Direction</span>${escapeHtml(ev.direction || "—")}</div>
            <div><span>ΔAUC (%)</span>${escapeHtml(ev.delta_auc_pct || "—")}</div>
            <div><span>PMID / Ref</span>${escapeHtml(ev.ref_ddi || "—")}</div>
            <div><span>Route</span>${escapeHtml(ev.route_of_admin || "—")}</div>
            <div><span>Route (ref)</span>${escapeHtml(ev.route_of_admin_ref || "—")}</div>
          </div>
        </div>
      `;
    }

    // Build per-drug details UI (enzymes/transporters + attributes)
    const detailsHtml = pair
      .map((drug) => {
        const info = drugDetailsMap?.[drug];
        if (!info) {
          return `<details><summary>${escapeHtml(drug)} — details unavailable</summary><div class="kv"><div><span>Note</span>Drug not found in dataset or details missing.</div></div></details>`;
        }

        const enz = info.enzymes || "—";
        const trn = info.transporters || "—";

        // attributes can be either:
        // - a flat object (old)
        // - OR grouped object (recommended): { "Organ considerations": {...}, ... }
        const attrs = info.attributes || {};
        let attrsHtml = "";

        const isGrouped =
          attrs &&
          typeof attrs === "object" &&
          Object.values(attrs).some((v) => v && typeof v === "object" && !Array.isArray(v));

        if (!attrs || Object.keys(attrs).length === 0) {
          attrsHtml = `<div><span>Notes</span>—</div>`;
        } else if (isGrouped) {
          // grouped display
          attrsHtml = Object.entries(attrs)
            .map(([group, obj]) => {
              if (!obj || typeof obj !== "object") return "";
              const rows = Object.entries(obj)
                .map(([k, v]) => `<div><span>${escapeHtml(k)}</span>${escapeHtml(v ?? "—")}</div>`)
                .join("");
              if (!rows) return "";
              return `
                <div class="group">
                  <div class="group-title">${escapeHtml(group)}</div>
                  <div class="kv">${rows}</div>
                </div>
              `;
            })
            .join("");
        } else {
          // flat display
          attrsHtml = Object.entries(attrs)
            .map(([k, v]) => `<div><span>${escapeHtml(k)}</span>${escapeHtml(v ?? "—")}</div>`)
            .join("");
        }

        return `
          <details>
            <summary>${escapeHtml(drug)} — details</summary>
            <div class="kv">
              <div><span>Enzymes</span>${escapeHtml(enz)}</div>
              <div><span>Transporters</span>${escapeHtml(trn)}</div>
            </div>
            <div class="subhead">Organ / PK / reference fields</div>
            ${isGrouped ? attrsHtml : `<div class="kv">${attrsHtml}</div>`}
          </details>
        `;
      })
      .join("");

    // DDInter — second, curated clinical source (independent of our PK data)
    const dd = it.ddinter || {};
    const ddHtml = dd.listed
      ? `<div class="callout ddinter">
           <div class="callout-title">DDInter 2.0 — curated clinical interaction</div>
           <div class="kv"><div><span>Severity</span>${escapeHtml(dd.level || "—")}</div></div>
         </div>`
      : "";

    // Sources / provenance — which dataset backs this verdict (linked PMIDs)
    const cites = it.citations || [];
    const citesHtml = cites.length
      ? `<div class="sources"><span class="sources-label">Sources</span>${cites
          .map((c) => {
            const lvl = c.level ? ` (${escapeHtml(c.level)})` : "";
            const det = c.detail ? `: ${escapeHtml(c.detail)}` : "";
            let ref = "";
            if (c.pmid) {
              ref = /^\d+$/.test(c.pmid)
                ? ` · <a href="https://pubmed.ncbi.nlm.nih.gov/${c.pmid}" target="_blank" rel="noopener">PMID ${escapeHtml(c.pmid)}</a>`
                : ` · ref ${escapeHtml(c.pmid)}`;
            }
            return `<span class="source-chip">${escapeHtml(c.source)} — ${escapeHtml(c.evidence)}${lvl}${det}${ref}</span>`;
          })
          .join("")}</div>`
      : "";

    const div = document.createElement("div");
    div.className = "result";

    div.innerHTML = `
      <div class="badge ${sev}">severity: ${escapeHtml(sev)}</div>
      <div class="pair">${escapeHtml(pairText)}</div>
      <div class="text">${escapeHtml(it.interaction || "")}</div>
      ${ddHtml}
      ${evHtml}
      ${citesHtml}
      ${explanation ? `<div class="small">${escapeHtml(explanation)}</div>` : ``}
      ${detailsHtml}
    `;

    resultsEl.appendChild(div);
  });
}


async function runCheck() {
  clearResults();
  const drugs = getDrugValues();

  if (drugs.length < 2) {
    setStatus("Add at least 2 drugs.");
    return;
  }

  // quick inline validation check: if any row is explicitly invalid, warn
  const anyInvalid = rows.some((r) => r.value?.trim() && r.valid === false);
  if (anyInvalid) {
    setStatus("One or more drugs are not found. Select from autocomplete or fix spelling.");
    return;
  }

  setBusy(true, "Checking");

  try {
    const data = await postJson("/check", { drugs });

    // fetch details to show enzyme/transporter breakdown
    const details = await hydrateDrugDetails(drugs);

    renderResults(data, details);
    setStatus("Done ✅");
  } catch (err) {
    setStatus(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

async function runAnalyze({ bypassInvalid = false } = {}) {
  clearResults();
  const drugs = getDrugValues();

  if (drugs.length < 2) {
    setStatus("Add at least 2 drugs.");
    return;
  }

  // Skipped for example queries: we WANT the "nothing found" example to reach
  // the server so the refusal behaviour is visible, not blocked client-side.
  const anyInvalid = rows.some((r) => r.value?.trim() && r.valid === false);
  if (!bypassInvalid && anyInvalid) {
    setStatus("One or more drugs are not found. Select from autocomplete, fix spelling, or run anyway to see how it's handled.");
    return;
  }

  setBusy(true, "Analyzing (running RAG + LLM, ~5–15s)");

  try {
    const data = await postJson("/analyze", {
      drugs,
      renal_impairment: renalEl?.value || "none",
      hepatic_impairment: hepaticEl?.value || "none",
    });

    const details = await hydrateDrugDetails(drugs);

    if (data.synthesis || data.key_flags?.length) {
      const synthDiv = document.createElement("div");
      synthDiv.className = "result";

      const flagsHtml = (data.key_flags || []).length
        ? `<div class="subhead">Key flags</div><ul class="key-flags">${(data.key_flags).map((f) => `<li>${escapeHtml(f)}</li>`).join("")}</ul>`
        : "";

      synthDiv.innerHTML = `
        <div class="badge mild">AI Analysis</div>
        <div class="subhead" style="margin-top:10px">Summary</div>
        <div class="text">${escapeHtml(data.synthesis || "")}</div>
        ${flagsHtml}
      `;
      resultsEl.appendChild(synthDiv);
    }

    renderResults({ interactions: data.interactions }, details, false);
    setStatus("Done ✅");
  } catch (err) {
    setStatus(friendlyError(err));
  } finally {
    setBusy(false);
  }
}

// Load a pre-filled example (drugs + organ state) and run the AI analysis.
async function loadExample(btn) {
  const drugs = (btn.dataset.drugs || "").split(",").map((d) => d.trim()).filter(Boolean);
  clearAll();
  while (rows.length < drugs.length) createRow("");
  drugs.forEach((d, i) => setRowValue(i, d));
  if (renalEl) renalEl.value = btn.dataset.renal || "none";
  if (hepaticEl) hepaticEl.value = btn.dataset.hepatic || "none";
  // Validate for the inline pills, then run anyway (bypass the block) so the
  // "nothing found" example demonstrates the server-side refusal.
  await Promise.all(rows.map((r) => (r.value?.trim() ? validateDrug(r.value).then((v) => (r.valid = v.ok)) : null)));
  await runAnalyze({ bypassInvalid: true });
}

// --- Button handlers
addBtn.addEventListener("click", () => createRow(""));
swapBtn.addEventListener("click", swapFirstTwo);
clearBtn.addEventListener("click", clearAll);
checkBtn.addEventListener("click", () => runCheck());
explainBtn.addEventListener("click", () => runAnalyze());
exampleBtns.forEach((b) => b.addEventListener("click", () => loadExample(b)));

// init
createRow("");
createRow("");
