/* AeroRegu Interactive Rotorcraft Quotation Cockpit (Composite DAG + Z3 SMT + IDP + Exports) */
(function () {
  "use strict";

  const HEMS_STC_8_PRESET = [
    "Q-DES-02",
    "Q-DES-04",
    "Q-STR-01",
    "Q-STR-02",
    "Q-STR-03",
    "Q-FDT-01",
    "Q-DOA-02",
    "Q-TST-01",
  ];

  const FALLBACK_ARCHETYPES = [
    ["Q-DES-01", "Concepto Aeronave / Cabina"],
    ["Q-DES-02", "Detalle Metálico / Herrajes"],
    ["Q-DES-03", "Composites & Ply-Book CFRP"],
    ["Q-DES-04", "Configuración W&B / EBOM"],
    ["Q-STR-01", "Envolvente Cargas CS-27/29"],
    ["Q-STR-02", "GFEM Fuselaje & .f06 Audit"],
    ["Q-STR-03", "DFEM & Dossier Estático"],
    ["Q-STR-04", "Gatekeeper Proveedores"],
    ["Q-FDT-01", "Fatiga y Tolerancia Daño F&DT"],
    ["Q-FDT-02", "Safe-Life Dinámicos MRB/MGB"],
    ["Q-DYN-01", "Dinámica Modal / SOL 103"],
    ["Q-DYN-02", "Crashworthiness 29.561/562"],
    ["Q-DYN-03", "Bird-Strike & Ditching SPH"],
    ["Q-DOA-01", "Reparaciones MRB & SB"],
    ["Q-DOA-02", "STC HEMS / Grúa / Misión"],
    ["Q-DOA-03", "Propulsión / Firewall / HIRF"],
    ["Q-TST-01", "Utillaje & Banco Ensayos"],
    ["Q-TST-02", "FTI & Permit to Fly PtF"],
  ];

  let latestDossier = null;

  function tenantOf() {
    if (typeof window.currentTenant === "function") return window.currentTenant();
    return (document.getElementById("tenant-input")?.value || "demo").trim() || "demo";
  }

  function escapeHtml(raw) {
    return String(raw ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderArchetypeCheckboxes(archetypes) {
    const grid = document.getElementById("quote-archetype-grid");
    if (!grid) return;
    grid.replaceChildren();
    archetypes.forEach(([aid, title]) => {
      const wrap = document.createElement("label");
      wrap.style.cssText =
        "display:flex;align-items:center;gap:0.4rem;font-size:0.84rem;padding:0.25rem 0.4rem;border:1px solid var(--border);border-radius:6px;cursor:pointer;";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.name = "archetype_ids";
      cb.value = aid;
      cb.checked = HEMS_STC_8_PRESET.includes(aid);
      const span = document.createElement("span");
      span.textContent = `${aid} — ${title}`;
      wrap.appendChild(cb);
      wrap.appendChild(span);
      grid.appendChild(wrap);
    });
  }

  async function hydrateCatalog() {
    renderArchetypeCheckboxes(FALLBACK_ARCHETYPES);
    try {
      const resp = await fetch("/quotations/rotorcraft/catalog", { credentials: "same-origin" });
      if (!resp.ok) return;
      const json = await resp.json();
      const archs = json?.result?.archetypes;
      if (Array.isArray(archs) && archs.length > 0) {
        renderArchetypeCheckboxes(archs.map((a) => [a.archetype_id, a.title]));
      }
    } catch {
      // Retain offline fallback list cleanly
    }
  }

  function selectedArchetypes() {
    return [...document.querySelectorAll('#quote-archetype-grid input[type="checkbox"]:checked')].map(
      (el) => el.value
    );
  }

  async function readFileAttachments() {
    const att = {};
    const bdfFile = document.getElementById("quote-bdf-file")?.files?.[0];
    const f06File = document.getElementById("quote-f06-file")?.files?.[0];
    const stepFile = document.getElementById("quote-step-file")?.files?.[0];
    if (bdfFile) att.bdf_text = await bdfFile.text();
    if (f06File) att.f06_text = await f06File.text();
    if (stepFile) att.step_text = await stepFile.text();
    return att;
  }

  function buildPayload(attachments) {
    return {
      tenant_id: tenantOf(),
      rfq_text: document.getElementById("quote-rfq-text")?.value || "",
      archetype_ids: selectedArchetypes(),
      country_code: document.getElementById("quote-country")?.value || "EU_DEFAULT",
      nearshore_country: document.getElementById("quote-nearshore")?.value || "ES",
      cert_basis: document.getElementById("quote-cert-basis")?.value || "CS-29",
      material_family: document.getElementById("quote-material")?.value || "HYBRID_AL_CFRP",
      unit_count: Number(document.getElementById("quote-units")?.value || 1),
      program_years: Number(document.getElementById("quote-years")?.value || 3),
      learning_rate_pct: document.getElementById("quote-lr")?.value || "85.000",
      payment_terms_days: Number(document.getElementById("quote-pay-days")?.value || 60),
      target_margin_pct: document.getElementById("quote-target-margin")?.value || "22.000",
      min_acceptable_margin_pct: document.getElementById("quote-min-margin")?.value || "10.000",
      idp_attachments: attachments || {},
      enable_formal_smt: true,
      enforce_contract_gate: true,
    };
  }

  function renderDagSvg(dag) {
    const wrap = document.getElementById("quote-dag-svg-wrap");
    if (!wrap) return;
    const nodes = dag?.nodes || [];
    const edges = dag?.edges || [];
    if (!nodes.length) {
      wrap.textContent = "Sin nodos en el grafo WBS.";
      return;
    }

    const colW = 165;
    const boxW = 138;
    const boxH = 68;
    const padX = 20;
    const rowGap = 92;

    // Position nodes deterministically by topological index & predecessor depth
    const depthById = new Map();
    nodes.forEach((n) => {
      const preds = n.predecessors || [];
      const d = preds.length ? Math.max(...preds.map((p) => depthById.get(p) ?? 0)) + 1 : 0;
      depthById.set(n.archetype_id, d);
    });
    const byDepth = new Map();
    nodes.forEach((n) => {
      const d = depthById.get(n.archetype_id) || 0;
      if (!byDepth.has(d)) byDepth.set(d, []);
      byDepth.get(d).push(n);
    });
    const maxCols = Math.max(...byDepth.keys(), 0) + 1;
    const maxRows = Math.max(...[...byDepth.values()].map((arr) => arr.length), 1);
    const coords = new Map();
    byDepth.forEach((arr, d) => {
      arr.forEach((n, rIdx) => {
        coords.set(n.archetype_id, {
          x: padX + d * colW,
          y: 18 + rIdx * rowGap,
          node: n,
        });
      });
    });

    const svgW = Math.max(480, padX * 2 + maxCols * colW);
    const svgH = Math.max(130, 32 + maxRows * rowGap);

    const edgeSvg = edges
      .map((e) => {
        const a = coords.get(e.from);
        const b = coords.get(e.to);
        if (!a || !b) return "";
        const x1 = a.x + boxW;
        const y1 = a.y + boxH / 2;
        const x2 = b.x;
        const y2 = b.y + boxH / 2;
        const crit = a.node.is_critical && b.node.is_critical;
        const stroke = crit ? "#dc2626" : "#64748b";
        const sw = crit ? "2.4" : "1.4";
        return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${sw}" marker-end="url(#dag-arrow)" />`;
      })
      .join("");

    const nodeSvg = nodes
      .map((n) => {
        const p = coords.get(n.archetype_id);
        const crit = Boolean(n.is_critical);
        const stroke = crit ? "#dc2626" : "#0a58ca";
        const fill = crit ? "rgba(220,38,38,0.12)" : "rgba(10,88,202,0.08)";
        return `
          <g>
            <rect x="${p.x}" y="${p.y}" width="${boxW}" height="${boxH}" rx="8" fill="${fill}" stroke="${stroke}" stroke-width="${crit ? 2.2 : 1.3}" />
            <text x="${p.x + 8}" y="${p.y + 18}" font-size="11" font-weight="700" fill="currentColor">${escapeHtml(n.archetype_id)}</text>
            <text x="${p.x + 8}" y="${p.y + 34}" font-size="10" fill="currentColor">${escapeHtml(n.net_hours)}h | ${escapeHtml(n.duration_weeks)}w</text>
            <text x="${p.x + 8}" y="${p.y + 50}" font-size="10" fill="currentColor">${crit ? "RUTA CRÍTICA" : `Holgura: ${escapeHtml(n.total_float_weeks)}w`}</text>
          </g>
        `;
      })
      .join("");

    wrap.innerHTML = `
      <svg viewBox="0 0 ${svgW} ${svgH}" width="${svgW}" height="${svgH}" role="img" aria-label="Grafo DAG y Ruta Crítica WBS">
        <defs>
          <marker id="dag-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b" />
          </marker>
        </defs>
        ${edgeSvg}
        ${nodeSvg}
      </svg>
    `;
  }

  function renderTables(dossier) {
    const dag = dossier.composite_wbs_dag || {};
    const my = dossier.multiyear_cashflow_learning?.outputs || {};
    const z3m = dossier.formal_margin_proof || {};
    const z3n = dossier.formal_multiyear_npv_proof || {};
    const ca = dossier.contract_audit || {};

    const statusEl = document.getElementById("quote-live-status");
    if (statusEl) {
      statusEl.innerHTML = `
        <strong>ESTIMATE / ASSUMPTION — ${escapeHtml(dossier.rfq_id)} (${escapeHtml(dossier.country_profile?.country_code)})</strong>:
        Precio Plurianual <strong>${escapeHtml(my.quoted_price_eur)} EUR</strong> |
        NPV <strong>${escapeHtml(my.net_present_value_eur)} EUR</strong> |
        Peak Neg Cash Flow <strong>-${escapeHtml(my.peak_negative_cashflow_eur)} EUR</strong> |
        Duración CPM: <strong>${escapeHtml(dag.project_duration_weeks)} sem</strong> |
        Sinergia: <strong>-${escapeHtml(dag.synergy_savings_pct)}%</strong>
      `;
    }

    const badgesEl = document.getElementById("quote-z3-badges");
    if (badgesEl) {
      badgesEl.innerHTML = `
        <span class="status-pill">Z3 Margen P80: ${escapeHtml(z3m.status || "SKIPPED")}</span>
        <span class="status-pill">Z3 NPV Plurianual: ${escapeHtml(z3n.status || "SKIPPED")}</span>
        <span class="status-pill">Contrato: ${escapeHtml(ca.overall_contract_gate || "SUPPORTED")}</span>
        <span class="status-pill">Merkle: ${escapeHtml(String(dossier.merkle_root || "").slice(0, 14))}...</span>
      `;
    }

    const poisonEl = document.getElementById("quote-poison-alert");
    if (poisonEl) {
      const poisons = ca.poison_clauses_detected || [];
      if (poisons.length > 0) {
        poisonEl.innerHTML = `
          <div style="padding:0.6rem;border-radius:8px;border:1px solid var(--err);background:rgba(185,28,28,0.10);">
            <strong>⚠ Cláusulas Trampa Detectadas (${poisons.length}):</strong>
            ${poisons.map((p) => `<div>• <code>${escapeHtml(p.poison_id)}</code> (${escapeHtml(p.severity)}): ${escapeHtml(p.redline)}</div>`).join("")}
          </div>
        `;
      } else {
        poisonEl.replaceChildren();
      }
    }

    renderDagSvg(dag);

    const wbsBody = document.querySelector("#quote-wbs-table tbody");
    if (wbsBody) {
      wbsBody.innerHTML = (dag.nodes || [])
        .map(
          (n) => `
          <tr>
            <th scope="row">${escapeHtml(n.archetype_id)}</th>
            <td>${escapeHtml(n.standalone_hours)}</td>
            <td>-${escapeHtml(n.synergy_reduction_pct)}%</td>
            <td>${escapeHtml(n.net_hours)}</td>
            <td>${escapeHtml(n.early_start_week)} → ${escapeHtml(n.early_finish_week)}</td>
            <td>${n.is_critical ? "<strong>CRÍTICO</strong>" : `${escapeHtml(n.total_float_weeks)} sem`}</td>
            <td>${escapeHtml(n.net_price_eur)}</td>
          </tr>`
        )
        .join("");
    }

    const torBody = document.querySelector("#quote-tornado-table tbody");
    if (torBody) {
      torBody.innerHTML = (dossier.tornado_sensitivity || [])
        .map(
          (t) => `
          <tr>
            <th scope="row">${escapeHtml(t.driver_label)}</th>
            <td>${escapeHtml(t.low_price_eur)}</td>
            <td>${escapeHtml(t.high_price_eur)}</td>
            <td>+${escapeHtml(t.swing_pct_of_p80)}%</td>
          </tr>`
        )
        .join("");
    }

    const ctryBody = document.querySelector("#quote-countries-table tbody");
    if (ctryBody) {
      const comp = dossier.multi_country_comparison || {};
      const hyb = comp.onshore_nearshore_hybrid;
      const rows = (comp.countries || []).map(
        (c) => `
          <tr>
            <th scope="row">${escapeHtml(c.country_code)}</th>
            <td>${escapeHtml(c.blended_hourly_rate_eur)}</td>
            <td>${escapeHtml(c.quote_price_eur)}</td>
            <td>${escapeHtml(c.delta_vs_eu_default_pct)}%</td>
          </tr>`
      );
      if (hyb) {
        rows.push(`
          <tr>
            <th scope="row">HÍBRIDO (${escapeHtml(hyb.onshore_cve_country)}/${escapeHtml(hyb.nearshore_execution_country)})</th>
            <td>${escapeHtml(hyb.blended_hourly_rate_eur)}</td>
            <td>${escapeHtml(hyb.quote_price_eur)}</td>
            <td>${escapeHtml(hyb.delta_vs_onshore_pct)}%</td>
          </tr>`);
      }
      ctryBody.innerHTML = rows.join("");
    }

    const ctrBody = document.querySelector("#quote-contract-table tbody");
    if (ctrBody) {
      ctrBody.innerHTML = (ca.compliance_matrix || [])
        .map(
          (cl) => `
          <tr>
            <th scope="row">${escapeHtml(cl.clause_id)}</th>
            <td>${escapeHtml(cl.status)}</td>
            <td>${escapeHtml(cl.suggested_redline || cl.rationale)}</td>
          </tr>`
        )
        .join("");
    }
  }

  async function runCompositeQuote(evt) {
    if (evt) evt.preventDefault();
    const runBtn = document.getElementById("quote-run-btn");
    const statusEl = document.getElementById("quote-live-status");
    if (runBtn) runBtn.disabled = true;
    try {
      const att = await readFileAttachments();
      const payload = buildPayload(att);
      const resp = await fetch("/quotations/rotorcraft/composite-dag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (typeof window.setOutput === "function") {
        window.setOutput(JSON.stringify(data, null, 2), data.status === "abstain" ? "warn" : "ok", "Quote DAG+Z3");
      }
      if (data.status === "abstain" || data.abstain) {
        const reason = data?.abstain?.reason || data?.abstain_reason || "abstain";
        if (statusEl) {
          statusEl.textContent = `ABSTAIN (${reason}) — Requiere revisión humana / CVE / Legal.`;
        }
        if (data.contract_audit) {
          renderTables({
            rfq_id: payload.rfq_text.slice(0, 18),
            country_profile: { country_code: payload.country_code },
            composite_wbs_dag: { nodes: [], edges: [], project_duration_weeks: "0", synergy_savings_pct: "0" },
            multiyear_cashflow_learning: { outputs: {} },
            contract_audit: data.contract_audit,
          });
        }
        return;
      }
      latestDossier = data.result;
      renderTables(latestDossier);
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error al cotizar: ${err?.message || err}`;
    } finally {
      if (runBtn) runBtn.disabled = false;
    }
  }

  async function downloadBinaryArtifact(url, filename, method = "POST") {
    const statusEl = document.getElementById("quote-live-status");
    try {
      let opts = { method, credentials: "same-origin" };
      if (method === "POST") {
        const att = await readFileAttachments();
        const body = latestDossier ? { dossier: latestDossier } : buildPayload(att);
        opts = {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        };
      }
      const resp = await fetch(url, opts);
      if (!resp.ok) {
        if (statusEl) statusEl.textContent = `Error descargando ${filename} (${resp.status})`;
        return;
      }
      const blob = await resp.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objUrl);
      if (statusEl) statusEl.textContent = `Descargado correctamente: ${filename}`;
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error descargando ${filename}: ${err?.message || err}`;
    }
  }

  async function runKfoldCalibration() {
    const statusEl = document.getElementById("quote-live-status");
    const kBody = document.querySelector("#quote-kfold-table tbody");
    const arch = selectedArchetypes()[0] || "Q-STR-03";
    const country = document.getElementById("quote-country")?.value || "EU_DEFAULT";
    try {
      const resp = await fetch("/quotations/rotorcraft/advanced-calibration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ archetype_id: arch, country_code: country, k_folds: 5 }),
      });
      const json = await resp.json();
      const res = json?.result || {};
      const cv = res.kfold_cv || {};
      const wr = res.win_rate_calibration || {};
      if (statusEl) {
        statusEl.innerHTML = `K-Fold CV (5 Folds, ${escapeHtml(cv.evaluated_records_count)} bids): MAPE <strong>${escapeHtml(cv.global_pre_mape_pct)}% → ${escapeHtml(cv.global_post_mape_pct)}%</strong> | Drift: <strong>${escapeHtml(res.drift_diagnostics?.drift_status)}</strong> | Percentil Óptimo: <strong>${escapeHtml(wr.recommended_percentile)}</strong>`;
      }
      if (kBody) {
        kBody.innerHTML = (wr.percentile_curve || [])
          .map(
            (r) => `
            <tr>
              <th scope="row">${escapeHtml(r.percentile)}</th>
              <td>${escapeHtml(r.bid_price_eur)} EUR</td>
              <td>${escapeHtml(r.calibrated_win_rate_pct)}%</td>
              <td>${escapeHtml(r.expected_commercial_value_eur)} EUR</td>
            </tr>`
          )
          .join("");
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error calibración K-Fold: ${err?.message || err}`;
    }
  }

  function bindCockpit() {
    hydrateCatalog();

    document.getElementById("quote-preset-hems-btn")?.addEventListener("click", () => {
      document.querySelectorAll('#quote-archetype-grid input[type="checkbox"]').forEach((cb) => {
        cb.checked = HEMS_STC_8_PRESET.includes(cb.value);
      });
    });

    document.getElementById("quote-clear-archs-btn")?.addEventListener("click", () => {
      document.querySelectorAll('#quote-archetype-grid input[type="checkbox"]').forEach((cb) => {
        cb.checked = false;
      });
    });

    document.getElementById("quote-cockpit-form")?.addEventListener("submit", runCompositeQuote);
    document.getElementById("quote-export-xlsx-btn")?.addEventListener("click", () => {
      downloadBinaryArtifact("/quotations/rotorcraft/export-xlsx", "aeroregu_quotation.xlsx", "POST");
    });
    document.getElementById("quote-export-pdf-btn")?.addEventListener("click", () => {
      downloadBinaryArtifact("/quotations/rotorcraft/export-pdf", "aeroregu_signed_quote.pdf", "POST");
    });
    document.getElementById("quote-erp-template-btn")?.addEventListener("click", () => {
      downloadBinaryArtifact("/quotations/rotorcraft/erp-template?format=xlsx", "aeroregu_erp_sap_bids_template.xlsx", "GET");
    });
    document.getElementById("quote-kfold-btn")?.addEventListener("click", runKfoldCalibration);

    document.addEventListener("keydown", (e) => {
      if (e.altKey && e.key === "7") {
        const t = document.getElementById("tab-quote");
        if (t && typeof window.activateTab === "function") {
          e.preventDefault();
          window.activateTab(t);
          t.focus();
        }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindCockpit);
  } else {
    bindCockpit();
  }
})();
