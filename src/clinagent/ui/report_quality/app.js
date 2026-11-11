const state = {
  caseId: null,
  cases: [],
  workspace: null,
};

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(payload.error || "Request failed");
  }
  return response.json();
}

function toneClass(tone) {
  return tone || "neutral";
}

function renderCaseSelector() {
  const select = document.getElementById("case-select");
  select.innerHTML = state.cases
    .map(
      (item) => `
        <option value="${item.id}" ${item.id === state.caseId ? "selected" : ""}>
          ${item.title} · ${item.status_label}
        </option>
      `,
    )
    .join("");
}

function renderHero(workspace) {
  document.getElementById("rail-case-title").textContent = workspace.title;
  document.getElementById("rail-case-summary").textContent = workspace.summary;
  const railChip = document.getElementById("rail-status-chip");
  railChip.textContent = workspace.status_label;
  railChip.className = `status-chip ${toneClass(workspace.status_tone)}`;

  document.getElementById("case-title").textContent = workspace.title;
  document.getElementById("case-subtitle").textContent = workspace.summary;
  document.getElementById("focus-chip").textContent = workspace.focus;
  document.getElementById("signal-score").textContent = workspace.score;
  const heroChip = document.getElementById("hero-status-chip");
  heroChip.textContent = workspace.status_label;
  heroChip.className = `status-chip ${toneClass(workspace.status_tone)}`;
}

function renderSummary(workspace) {
  document.getElementById("summary-strip").innerHTML = workspace.summary_cards
    .map(
      (item) => `
        <div class="summary-card ${toneClass(item.tone)}">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
        </div>
      `,
    )
    .join("");
}

function renderFindings(workspace) {
  document.getElementById("findings-groups").innerHTML = workspace.findings_groups
    .map((group) => {
      if (!group.items.length) {
        return `
          <article class="finding-group">
            <h4>${group.title}</h4>
            <p>${group.empty}</p>
          </article>
        `;
      }
      return `
        <article class="finding-group">
          <h4>${group.title}</h4>
          <div class="finding-list">
            ${group.items
              .map(
                (item) => `
                  <div class="finding-item">
                    <div class="finding-head">
                      <strong>${item.label}</strong>
                      <span class="severity-pill ${toneClass(item.severity)}">${item.severity}</span>
                    </div>
                    <p>${item.detail}</p>
                    ${item.examples && item.examples.length ? `<ul>${item.examples.map((value) => `<li>${value}</li>`).join("")}</ul>` : ""}
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      `;
    })
    .join("");
}

function renderTimeline(workspace) {
  document.getElementById("timeline-list").innerHTML = workspace.timeline
    .map(
      (item) => `
        <article class="timeline-item">
          <strong>${item.title}</strong>
          <p>${item.detail}</p>
        </article>
      `,
    )
    .join("");
}

function renderReport(workspace) {
  document.getElementById("report-surface").innerHTML = workspace.report_html;
}

function renderInputPreview(workspace) {
  document.getElementById("input-preview").textContent = workspace.input_text;
}

function renderWorkspace(workspace) {
  state.workspace = workspace;
  renderCaseSelector();
  renderHero(workspace);
  renderSummary(workspace);
  renderFindings(workspace);
  renderTimeline(workspace);
  renderReport(workspace);
  renderInputPreview(workspace);
}

async function loadWorkspace(caseId = null) {
  if (caseId) {
    const workspace = await fetchJson(`/api/report-quality/cases/${caseId}`);
    state.caseId = caseId;
    renderWorkspace(workspace);
    return;
  }
  const payload = await fetchJson("/api/report-quality/workspace");
  state.caseId = payload.default_case_id;
  state.cases = payload.cases;
  renderWorkspace(payload.workspace);
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("case-select").addEventListener("change", async (event) => {
    await loadWorkspace(event.target.value);
  });
  try {
    await loadWorkspace();
  } catch (error) {
    document.getElementById("report-surface").innerHTML = `<p style="padding:16px;color:#b93f4d;">${error.message}</p>`;
  }
});
