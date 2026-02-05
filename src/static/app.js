const drugListEl = document.getElementById("drug-list");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

const addBtn = document.getElementById("add");
const swapBtn = document.getElementById("swap");
const clearBtn = document.getElementById("clear");
const checkBtn = document.getElementById("check");
const explainBtn = document.getElementById("explain");

let rows = [];

function setStatus(msg) {
  statusEl.textContent = msg || "";
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

  suggestions.addEventListener("click", async (e) => {
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

function renderResults(data, drugDetailsMap) {
  clearResults();
  const interactions = data?.interactions || [];
  if (!interactions.length) {
    resultsEl.innerHTML = `<div class="result"><div class="text">No results.</div></div>`;
    return;
  }

  interactions.forEach((it) => {
    const sev = (it.severity || "none").toLowerCase();
    const pair = (it.drug_pair || []);
    const pairText = pair.join(" + ");
    const explanation = it.llm_explanation;

    // Build per-drug details UI
    const detailsHtml = pair
      .map((drug) => {
        const info = drugDetailsMap?.[drug];
        if (!info) {
          return `<details><summary>${escapeHtml(drug)} — details unavailable</summary><div class="kv"><div><span>Note</span>Drug not found in dataset or details missing.</div></div></details>`;
        }
        const enz = info.enzymes || "—";
        const trn = info.transporters || "—";
        return `
          <details>
            <summary>${escapeHtml(drug)} — enzyme/transporter details</summary>
            <div class="kv">
              <div><span>Enzymes</span>${escapeHtml(enz)}</div>
              <div><span>Transporters</span>${escapeHtml(trn)}</div>
            </div>
          </details>
        `;
      })
      .join("");

    const div = document.createElement("div");
    div.className = "result";
    div.innerHTML = `
      <div class="badge ${sev}">severity: ${sev}</div>
      <div class="pair">${escapeHtml(pairText)}</div>
      <div class="text">${escapeHtml(it.interaction || "")}</div>
      ${explanation ? `<div class="small">${escapeHtml(explanation)}</div>` : ``}
      ${detailsHtml}
    `;
    resultsEl.appendChild(div);
  });
}

async function runCheck(explain = false) {
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

  setStatus(explain ? "Explaining…" : "Checking…");

  try {
    const path = explain ? "/check/explain" : "/check";
    const data = await postJson(path, { drugs });

    // fetch details to show enzyme/transporter breakdown
    const details = await hydrateDrugDetails(drugs);

    renderResults(data, details);
    setStatus("Done ✅");
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  }
}

// --- Button handlers
addBtn.addEventListener("click", () => createRow(""));
swapBtn.addEventListener("click", swapFirstTwo);
clearBtn.addEventListener("click", clearAll);
checkBtn.addEventListener("click", () => runCheck(false));
explainBtn.addEventListener("click", () => runCheck(true));

// init
createRow("");
createRow("");
