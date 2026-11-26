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
  let baselineDossier = null;
  let latestCcn = null;
  let latestFxReport = null;
  let latestEvmReport = null;

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

  function safeSetHTML(el, html) {
    if (!el) return;
    const cfg = {
      elements: ["strong", "span", "em", "code", "br"],
      attributes: ["class"],
    };
    if (typeof el.setHTML === "function") {
      el.setHTML(html, { sanitizer: cfg });
      return;
    }
    el.innerHTML = html;
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

  async function fileToBase64(file) {
    const buf = await file.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let bin = "";
    const chunk = 8192;
    for (let i = 0; i < bytes.length; i += chunk) {
      bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    return btoa(bin);
  }

  async function readFileAttachments() {
    const att = {};
    const bdfFile = document.getElementById("quote-bdf-file")?.files?.[0];
    const f06File = document.getElementById("quote-f06-file")?.files?.[0];
    const op2File = document.getElementById("quote-op2-file")?.files?.[0];
    const h5File = document.getElementById("quote-h5-file")?.files?.[0];
    const stepFile = document.getElementById("quote-step-file")?.files?.[0];
    const bomFile = document.getElementById("quote-bom-file")?.files?.[0];
    const abqFile = document.getElementById("quote-abaqus-file")?.files?.[0];
    if (bdfFile) att.bdf_text = await bdfFile.text();
    if (f06File) att.f06_text = await f06File.text();
    if (op2File) att.op2_base64 = await fileToBase64(op2File);
    if (h5File) att.h5_base64 = await fileToBase64(h5File);
    if (stepFile) att.step_text = await stepFile.text();
    if (abqFile) att.abaqus_text = await abqFile.text();
    if (bomFile) {
      const b64 = await fileToBase64(bomFile);
      const low = bomFile.name.toLowerCase();
      if (low.endsWith(".xlsx")) {
        att.bom_xlsx_base64 = b64;
        att.bom_xlsx_filename = bomFile.name;
      } else if (low.endsWith(".docx")) {
        att.bom_docx_base64 = b64;
        att.bom_docx_filename = bomFile.name;
      } else {
        att.bom_pdf_base64 = b64;
        att.bom_pdf_filename = bomFile.name;
      }
    }
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

  function renderCashflowSvg(dossier) {
    const wrap = document.getElementById("quote-cf-svg-wrap");
    const tbody = document.querySelector("#quote-cashflow-table tbody");
    const sched = dossier?.multiyear_cashflow_learning?.diagnostics?.monthly_cashflow_schedule || [];
    if (!sched.length) {
      if (wrap) wrap.textContent = "Sin programación de flujo de caja mensual.";
      if (tbody) tbody.replaceChildren();
      return;
    }

    const vals = sched.map((m) => Number(m.cumulative_cash_eur || 0));
    const minV = Math.min(0, ...vals);
    const maxV = Math.max(1, ...vals);
    const span = Math.max(1, maxV - minV);
    const w = 640;
    const h = 160;
    const padX = 28;
    const padY = 18;
    const plotW = w - padX * 2;
    const plotH = h - padY * 2;
    const toX = (i) => padX + (sched.length === 1 ? plotW / 2 : (i / (sched.length - 1)) * plotW);
    const toY = (v) => padY + ((maxV - v) / span) * plotH;
    const zeroY = toY(0).toFixed(1);

    const pts = vals.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");
    const peakNeg = dossier?.multiyear_cashflow_learning?.outputs?.peak_negative_cashflow_eur || "0";

    if (wrap) {
      wrap.innerHTML = `
        <svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">
          <title>Curva mensual de caja acumulada: exposición negativa máxima -${escapeHtml(peakNeg)} EUR en ${sched.length} meses</title>
          <line x1="${padX}" y1="${zeroY}" x2="${w - padX}" y2="${zeroY}" stroke="#94a3b8" stroke-dasharray="4 3" stroke-width="1" />
          <polyline fill="none" stroke="#0a58ca" stroke-width="2.2" points="${pts}" />
        </svg>
      `;
    }

    if (tbody) {
      tbody.innerHTML = sched
        .filter((_, idx) => sched.length <= 12 || idx % 3 === 0 || idx === sched.length - 1)
        .map(
          (m) => `
          <tr>
            <th scope="row">M${escapeHtml(m.month)}</th>
            <td>${escapeHtml(m.outflow_eur)}</td>
            <td>${escapeHtml(m.inflow_eur)}</td>
            <td>${escapeHtml(m.net_eur)}</td>
            <td>${escapeHtml(m.cumulative_cash_eur)}</td>
          </tr>`
        )
        .join("");
    }
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
    renderCashflowSvg(dossier);

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

  async function runChangeOrderDelta() {
    const ccnStatus = document.getElementById("quote-ccn-status");
    const ccnBody = document.querySelector("#quote-ccn-table tbody");
    if (!baselineDossier) {
      if (latestDossier) {
        baselineDossier = latestDossier;
      } else {
        if (ccnStatus) ccnStatus.textContent = "Primero ejecuta una cotización base para fijar Baseline Rev A.";
        return;
      }
    }
    try {
      const att = await readFileAttachments();
      const revPayload = buildPayload(att);
      const body = {
        ...revPayload,
        baseline_dossier: baselineDossier,
        cr_id: document.getElementById("quote-ccn-id")?.value || "CCN-001",
        change_reason: document.getElementById("quote-ccn-reason")?.value || "Scope & lot update",
      };
      const resp = await fetch("/quotations/rotorcraft/change-order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const json = await resp.json();
      if (json.status === "abstain" || json.abstain) {
        if (ccnStatus) ccnStatus.textContent = `CCN ABSTAIN (${json?.abstain?.reason || "gate"}) — Bloqueo contractual o SMT.`;
        return;
      }
      latestCcn = json.result;
      const fin = latestCcn.financial_delta || {};
      const cpm = latestCcn.cpm_delta || {};
      if (ccnStatus) {
        ccnStatus.innerHTML = `CCN <strong>${escapeHtml(latestCcn.cr_id)}</strong> (${escapeHtml(latestCcn.decision_status)}): Delta Precio <strong>${escapeHtml(fin.delta_multiyear_quoted_price_eur)} EUR (${escapeHtml(fin.delta_price_pct)}%)</strong> | Delta Plazo <strong>${escapeHtml(cpm.delta_duration_weeks)} sem</strong> | Contrato: ${escapeHtml(latestCcn.contract_delta?.gate_transition)}`;
      }
      if (ccnBody) {
        ccnBody.innerHTML = (latestCcn.wbs_delta?.node_deltas || [])
          .map(
            (n) => `
            <tr>
              <th scope="row">${escapeHtml(n.archetype_id)}</th>
              <td>${escapeHtml(n.change_status)}</td>
              <td>${escapeHtml(n.delta_hours)}</td>
              <td>${escapeHtml(n.delta_price_eur)}</td>
            </tr>`
          )
          .join("");
      }
    } catch (err) {
      if (ccnStatus) ccnStatus.textContent = `Error CCN: ${err?.message || err}`;
    }
  }

  async function downloadCcnBinary(url, filename) {
    const ccnStatus = document.getElementById("quote-ccn-status");
    try {
      const body = latestCcn ? { ccn_dossier: latestCcn } : { baseline_dossier: baselineDossier, ...buildPayload({}) };
      const resp = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        if (ccnStatus) ccnStatus.textContent = `Error descargando ${filename} (${resp.status})`;
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
      if (ccnStatus) ccnStatus.textContent = `Descargado CCN: ${filename}`;
    } catch (err) {
      if (ccnStatus) ccnStatus.textContent = `Error descargando ${filename}: ${err?.message || err}`;
    }
  }

  async function runPortfolioCapacity() {
    const ccnStatus = document.getElementById("quote-ccn-status");
    const pBody = document.querySelector("#quote-portfolio-table tbody");
    const leadCve = Number(document.getElementById("quote-lead-cve-fte")?.value || 2);
    const fdtSpec = Number(document.getElementById("quote-fdt-fte")?.value || 2);
    const onshore = document.getElementById("quote-port-onshore")?.value || "DE";
    const nearshore = document.getElementById("quote-port-nearshore")?.value || "ES";
    const dossiers = [];
    if (baselineDossier) dossiers.push(baselineDossier);
    if (latestDossier && latestDossier !== baselineDossier) dossiers.push(latestDossier);
    const body = dossiers.length
      ? {
          dossiers,
          team_headcount: { LEAD_CVE: leadCve, FDT_SPEC: fdtSpec },
          optimize_nearshore: true,
          onshore_country: onshore,
          nearshore_country: nearshore,
        }
      : {
          tenant_id: tenantOf(),
          team_headcount: { LEAD_CVE: leadCve, FDT_SPEC: fdtSpec },
          optimize_nearshore: true,
          onshore_country: onshore,
          nearshore_country: nearshore,
          rfq_specs: [
            { rfq_id: "PORT-01", rfq_text: "CS-29 frame static & FDT Net 60.", archetype_ids: ["Q-DES-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"] },
            { rfq_id: "PORT-02", rfq_text: "CS-29 hoist STC & rig Net 60.", archetype_ids: ["Q-STR-03", "Q-DOA-02", "Q-TST-01"] },
          ],
        };
    try {
      const resp = await fetch("/quotations/rotorcraft/portfolio-capacity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const json = await resp.json();
      const res = json?.result || {};
      const ns = res.nearshore_optimization || {};
      if (ccnStatus) {
        safeSetHTML(
          ccnStatus,
          `Portfolio RCPSP (${escapeHtml(res.portfolio_rfq_count)} RFQs): Sobrecarga <strong>${escapeHtml(res.overloaded_weeks_before_leveling)} sem</strong> | Overflow: <strong>${escapeHtml(res.recommended_nearshore_overflow_hours)}h</strong> | Ahorro Nearshore (${escapeHtml(ns.onshore_country || onshore)}-&gt;${escapeHtml(ns.nearshore_country || nearshore)}): <strong>${escapeHtml(ns.net_savings_eur || "0.00")} EUR</strong> (CVE Onshore=${escapeHtml(String(ns.cve_governance_preserved ?? true))})`
        );
      }
      if (pBody) {
        pBody.innerHTML = (res.bottleneck_roles || [])
          .map(
            (r) => `
            <tr>
              <th scope="row">${escapeHtml(r.role)}</th>
              <td>${escapeHtml(r.headcount)}</td>
              <td>${escapeHtml(r.unconstrained_peak_utilization_pct)}%</td>
              <td>${escapeHtml(r.leveled_peak_utilization_pct)}%</td>
            </tr>`
          )
          .join("");
      }
    } catch (err) {
      if (ccnStatus) ccnStatus.textContent = `Error RCPSP portfolio: ${err?.message || err}`;
    }
  }

  async function downloadPortfolioBinary(url, filename) {
    const ccnStatus = document.getElementById("quote-ccn-status");
    const leadCve = Number(document.getElementById("quote-lead-cve-fte")?.value || 2);
    const fdtSpec = Number(document.getElementById("quote-fdt-fte")?.value || 2);
    const onshore = document.getElementById("quote-port-onshore")?.value || "DE";
    const nearshore = document.getElementById("quote-port-nearshore")?.value || "ES";
    const body = {
      tenant_id: tenantOf(),
      team_headcount: { LEAD_CVE: leadCve, FDT_SPEC: fdtSpec },
      optimize_nearshore: true,
      onshore_country: onshore,
      nearshore_country: nearshore,
      rfq_specs: [
        { rfq_id: "PORT-01", rfq_text: "CS-29 frame static & FDT Net 60.", archetype_ids: ["Q-DES-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"] },
        { rfq_id: "PORT-02", rfq_text: "CS-29 hoist STC & rig Net 60.", archetype_ids: ["Q-STR-03", "Q-DOA-02", "Q-TST-01"] },
      ],
    };
    try {
      const resp = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        if (ccnStatus) ccnStatus.textContent = `Error descargando ${filename} (${resp.status})`;
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
      if (ccnStatus) ccnStatus.textContent = `Descargado Portfolio: ${filename}`;
    } catch (err) {
      if (ccnStatus) ccnStatus.textContent = `Error descargando ${filename}: ${err?.message || err}`;
    }
  }

  async function runFxHedging() {
    const statusEl = document.getElementById("quote-fx-evm-status");
    const fxBody = document.querySelector("#quote-fx-table tbody");
    const myOut = latestDossier?.multiyear_cashflow_learning?.outputs || {};
    const quotedPrice = myOut.quoted_price_eur || "500000";
    const costEur = myOut.escalated_total_cost_eur || "375000";
    const body = {
      quoted_price_eur: quotedPrice,
      cost_eur: costEur,
      billing_currency: document.getElementById("quote-fx-billing-ccy")?.value || "USD",
      hedge_ratio_pct: document.getElementById("quote-fx-hedge-pct")?.value || "85",
      fx_shock_band_pct: document.getElementById("quote-fx-band-pct")?.value || "10",
      min_acceptable_margin_pct: document.getElementById("quote-min-margin")?.value || "10.000",
    };
    try {
      const resp = await fetch("/quotations/rotorcraft/fx-hedging", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const json = await resp.json();
      latestFxReport = json?.result || {};
      const z3fx = latestFxReport.formal_fx_margin_proof || {};
      if (statusEl) {
        statusEl.innerHTML = `FX (${escapeHtml(latestFxReport.billing_currency)}): Factura <strong>${escapeHtml(latestFxReport.invoice_amount_billing_ccy)}</strong> | Coste Carry <strong>${escapeHtml(latestFxReport.hedge_carry_cost_eur)} EUR</strong> | Z3: <strong>${escapeHtml(z3fx.status)}</strong> | Cobertura Min Rec: ${escapeHtml(latestFxReport.recommended_min_hedge_ratio_pct || "N/A")}%`;
      }
      if (fxBody) {
        fxBody.innerHTML = (latestFxReport.sensitivity_scenarios || [])
          .map(
            (s) => `
            <tr>
              <th scope="row">${escapeHtml(s.fx_shock_pct)}%</th>
              <td>${escapeHtml(s.unhedged_revenue_eur)}</td>
              <td>${escapeHtml(s.hedged_revenue_eur)}</td>
              <td>${escapeHtml(s.hedged_margin_pct)}%</td>
            </tr>`
          )
          .join("");
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error FX hedging: ${err?.message || err}`;
    }
  }

  async function runEvmPostmortem() {
    const statusEl = document.getElementById("quote-fx-evm-status");
    const evmBody = document.querySelector("#quote-evm-table tbody");
    const base = baselineDossier || latestDossier;
    const overrunPct = Number(document.getElementById("quote-evm-overrun-pct")?.value || 25);
    const ecnActual = Number(document.getElementById("quote-evm-ecn-actual")?.value || 4);
    const projId = document.getElementById("quote-evm-proj-id")?.value || "POST-H145-HOIST";
    const factor = 1 + overrunPct / 100;
    const baseNodes = base?.composite_wbs_dag?.nodes || [];
    const actuals = baseNodes.length
      ? baseNodes.map((n, idx) => ({
          archetype_id: n.archetype_id,
          actual_hours: (Number(n.net_hours || 0) * (idx === 0 ? factor : 1)).toFixed(2),
          earned_pct: "100",
        }))
      : [{ archetype_id: "Q-STR-03", actual_hours: "280.00", earned_pct: "100" }];

    const body = {
      tenant_id: tenantOf(),
      project_id: projId,
      baseline_dossier: base || undefined,
      actual_ecn_iterations: ecnActual,
      actuals,
    };
    try {
      const resp = await fetch("/quotations/rotorcraft/evm-postmortem", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const json = await resp.json();
      latestEvmReport = json?.result || {};
      const evm = latestEvmReport.evm_summary || {};
      if (statusEl) {
        statusEl.innerHTML = `EVM <strong>${escapeHtml(latestEvmReport.project_id)}</strong> (${escapeHtml(latestEvmReport.health_status)}): CPI=<strong>${escapeHtml(evm.cpi)}</strong> | SPI=<strong>${escapeHtml(evm.spi)}</strong> | EAC=<strong>${escapeHtml(evm.eac_eur)} EUR</strong> | Margen Real: ${escapeHtml(evm.realized_margin_pct)}%`;
      }
      if (evmBody) {
        evmBody.innerHTML = (latestEvmReport.per_node_evm || [])
          .map(
            (nd) => `
            <tr>
              <th scope="row">${escapeHtml(nd.archetype_id)}</th>
              <td>${escapeHtml(nd.quoted_hours)} / ${escapeHtml(nd.actual_hours)}</td>
              <td>${escapeHtml(nd.cpi)}</td>
              <td>${escapeHtml(nd.eac_eur)}</td>
            </tr>`
          )
          .join("");
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error EVM postmortem: ${err?.message || err}`;
    }
  }

  async function downloadEvmBinary(url, filename) {
    const statusEl = document.getElementById("quote-fx-evm-status");
    try {
      const body = latestEvmReport
        ? { postmortem_report: latestEvmReport, fx_report: latestFxReport }
        : {
            tenant_id: tenantOf(),
            project_id: document.getElementById("quote-evm-proj-id")?.value || "POST-H145-HOIST",
            billing_currency: document.getElementById("quote-fx-billing-ccy")?.value || "USD",
            hedge_ratio_pct: document.getElementById("quote-fx-hedge-pct")?.value || "85",
          };
      const resp = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
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
      if (statusEl) statusEl.textContent = `Descargado EVM: ${filename}`;
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error descargando ${filename}: ${err?.message || err}`;
    }
  }

  let latestStressDossier = null;
  let latestLoadEnvelope = null;
  let latestMocMatrix = null;
  let latestRiskReport = null;
  let reauthAbortController = new AbortController();

  async function runAllowableArbLookup() {
    const statusEl = document.getElementById("quote-stress-dossier-status");
    const mat = document.getElementById("quote-allow-mat")?.value || "AL-7075-T651";
    const temp = document.getElementById("quote-allow-temp")?.value || "85";
    const tempUnc = document.getElementById("quote-allow-temp-unc")?.value || "5";
    const thk = document.getElementById("quote-allow-thk")?.value || "20";
    const basis = document.getElementById("quote-allow-basis")?.value || "A";
    try {
      const resp = await fetch("/calc/allowables", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          material_id: mat,
          basis,
          property_name: "fty_mpa",
          thickness_mm: thk,
          temp_c: temp,
          environment: "RTD",
          include_intervals: true,
          temp_uncertainty_c: tempUnc,
        }),
      });
      const json = await resp.json();
      if (!resp.ok || json.abstain) {
        if (statusEl) statusEl.textContent = `ABSTAIN allowables (${mat}): ${json.abstain?.reason || resp.status}`;
        return;
      }
      const res = json.result || {};
      const iv = res.exact_intervals?.allowable_value_mpa || {};
      if (statusEl) {
        safeSetHTML(
          statusEl,
          `MMPDS/CMH-17 <strong>${escapeHtml(res.material_id)}</strong> (${escapeHtml(res.basis)}-Basis): Fty=<strong>${escapeHtml(res.allowable_value_mpa)} MPa</strong> | Intervalo Arb 50 dígitos=[<code>${escapeHtml(iv.lower || res.allowable_value_mpa)}</code>, <code>${escapeHtml(iv.upper || res.allowable_value_mpa)}</code>] | Catálogo SHA=${escapeHtml(String(res.catalog_sha256 || "").slice(0, 12))}...`
        );
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error allowables Arb: ${err?.message || err}`;
    }
  }

  async function runBatchStressDossier() {
    const statusEl = document.getElementById("quote-stress-dossier-status");
    const tbody = document.querySelector("#quote-stress-table tbody");
    const dossierId = document.getElementById("quote-stress-dossier-id")?.value || "STRESS-H145-V4";
    const mat = document.getElementById("quote-allow-mat")?.value || "AL-7075-T651";
    const checks = [
      {
        check_id: "SKID-01",
        component_name: "Skid Cross-Tube Aft",
        method_id: "cs29_skid_landing_gear_drop_energy",
        inputs: {
          gross_weight_kg: "2800",
          drop_height_m: "0.330",
          rotor_lift_fraction: "0.667",
          vertical_stroke_m: "0.220",
          gear_efficiency_eta: "0.750",
          cross_tube_od_mm: "76.0",
          cross_tube_wall_mm: "6.0",
          cantilever_arm_mm: "420.0",
          yield_allowable_mpa: "441.0",
          safety_factor: "1.000",
        },
        material_lookup: { target_field: "yield_allowable_mpa", material_id: mat, basis: "A", temp_c: "50", temp_uncertainty_c: "5" },
      },
      {
        check_id: "TRDS-02",
        component_name: "Tail Rotor Drive Shaft",
        method_id: "shaft_whirl_critical_speed_screen",
        inputs: {
          shaft_length_mm: "1450",
          outer_diameter_mm: "82.0",
          inner_diameter_mm: "76.0",
          youngs_modulus_mpa: "71700",
          density_kg_m3: "2810",
          bearing_fixity_lambda: "3.14159",
          operating_rpm: "4200",
          overspeed_factor: "1.200",
        },
      },
      {
        check_id: "FIRE-03",
        component_name: "CS 29.1191 Engine Firewall",
        method_id: "firewall_thermal_buckling_screen",
        inputs: {
          panel_width_b_mm: "75.0",
          panel_thickness_t_mm: "2.00",
          youngs_modulus_hot_mpa: "95000",
          poissons_ratio: "0.310",
          cte_per_c: "0.0000090",
          delta_temp_c: "220",
          restraint_factor: "0.650",
          plate_buckling_kc: "4.000",
          hot_yield_allowable_mpa: "520",
          safety_factor: "1.150",
        },
      },
    ];
    try {
      const resp = await fetch("/calc/batch-stress-dossier", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ dossier_id: dossierId, tenant_id: tenantOf(), record: false, checks }),
      });
      const json = await resp.json();
      latestStressDossier = json?.result || {};
      if (statusEl) {
        safeSetHTML(
          statusEl,
          `Stress Dossier <strong>${escapeHtml(latestStressDossier.dossier_id)}</strong>: ${escapeHtml(latestStressDossier.passed_margin_count)}/${escapeHtml(latestStressDossier.check_count)} MS>=0 | Z3=${escapeHtml(latestStressDossier.formal_proved_count)} | Min MS=<strong>${escapeHtml(latestStressDossier.global_ms_min)}</strong> (${escapeHtml(latestStressDossier.governing_check_id)})`
        );
      }
      if (tbody) {
        tbody.innerHTML = (latestStressDossier.checks_results || [])
          .map(
            (ch) => `
            <tr>
              <th scope="row">${escapeHtml(ch.check_id)}</th>
              <td>${escapeHtml(ch.component_name)}</td>
              <td><code>${escapeHtml(ch.method_id)}</code></td>
              <td>${escapeHtml(ch.governing_ms)} [${escapeHtml(ch.arb_interval?.lower || "-")}, ${escapeHtml(ch.arb_interval?.upper || "-")}]</td>
              <td>${escapeHtml(ch.formal_proof?.status || "N/A")}</td>
            </tr>`
          )
          .join("");
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error Stress Dossier: ${err?.message || err}`;
    }
  }

  async function downloadStressDossierBinary(url, filename) {
    const statusEl = document.getElementById("quote-stress-dossier-status");
    const dossierId = document.getElementById("quote-stress-dossier-id")?.value || "STRESS-H145-V4";
    const body = latestStressDossier
      ? { dossier: latestStressDossier }
      : { dossier_id: dossierId, tenant_id: tenantOf() };
    try {
      const resp = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
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
      if (statusEl) statusEl.textContent = `Descargado Stress Dossier: ${filename}`;
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error descargando ${filename}: ${err?.message || err}`;
    }
  }

  async function triggerPasskeyStepUpReauth() {
    const statusEl = document.getElementById("quote-stress-dossier-status");
    if (typeof window.PublicKeyCredential !== "function" || !navigator.credentials?.get) {
      if (statusEl) statusEl.textContent = "WebAuthn Passkey API no disponible en este navegador.";
      return;
    }
    reauthAbortController.abort();
    reauthAbortController = new AbortController();
    try {
      const optResp = await fetch("/auth/webauthn/reauth/options", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ user_id: tenantOf() }),
      });
      if (!optResp.ok) {
        if (statusEl) statusEl.textContent = `Sin passkeys registradas para step-up (${optResp.status}).`;
        return;
      }
      const optJson = await optResp.json();
      const optionsJSON = optJson.result || optJson;
      const publicKey = PublicKeyCredential.parseRequestOptionsFromJSON(optionsJSON);
      const credential = await navigator.credentials.get({
        publicKey,
        signal: reauthAbortController.signal,
      });
      if (!credential) return;
      const encoded = credential.toJSON();
      const verResp = await fetch("/auth/webauthn/reauth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ ...encoded, challenge: optionsJSON.challenge, user_id: tenantOf() }),
      });
      if (verResp.ok) {
        if (statusEl) statusEl.textContent = "Step-Up Passkey CVE verificado correctamente.";
      } else if (verResp.status === 404 && typeof PublicKeyCredential.signalUnknownCredential === "function") {
        await PublicKeyCredential.signalUnknownCredential({
          rpId: publicKey.rpId,
          credentialId: encoded.id,
        });
        if (statusEl) statusEl.textContent = "Credencial desconocida señalizada al gestor Passkey.";
      }
    } catch (err) {
      if (err?.name === "NotAllowedError") {
        if (statusEl) statusEl.textContent = "Reautenticación Passkey cancelada por el usuario.";
      } else if (statusEl) {
        statusEl.textContent = `Error Passkey step-up: ${err?.message || err}`;
      }
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

    document.getElementById("quote-set-baseline-btn")?.addEventListener("click", () => {
      const ccnStatus = document.getElementById("quote-ccn-status");
      if (!latestDossier) {
        if (ccnStatus) ccnStatus.textContent = "Primero genera una cotización DAG antes de fijar Baseline Rev A.";
        return;
      }
      baselineDossier = latestDossier;
      if (ccnStatus) ccnStatus.textContent = `Baseline Rev A fijado: ${baselineDossier.rfq_id} (${baselineDossier.merkle_root?.slice(0, 14)}...)`;
    });
    document.getElementById("quote-ccn-run-btn")?.addEventListener("click", runChangeOrderDelta);
    document.getElementById("quote-ccn-xlsx-btn")?.addEventListener("click", () => {
      downloadCcnBinary("/quotations/rotorcraft/change-order/export-xlsx", "aeroregu_change_order.xlsx");
    });
    document.getElementById("quote-ccn-pdf-btn")?.addEventListener("click", () => {
      downloadCcnBinary("/quotations/rotorcraft/change-order/export-pdf", "aeroregu_signed_ccn.pdf");
    });
    document.getElementById("quote-portfolio-btn")?.addEventListener("click", runPortfolioCapacity);
    document.getElementById("quote-portfolio-xlsx-btn")?.addEventListener("click", () => {
      downloadPortfolioBinary("/quotations/rotorcraft/portfolio-capacity/export-xlsx", "aeroregu_portfolio_rcpsp.xlsx");
    });
    document.getElementById("quote-portfolio-pdf-btn")?.addEventListener("click", () => {
      downloadPortfolioBinary("/quotations/rotorcraft/portfolio-capacity/export-pdf", "aeroregu_signed_portfolio.pdf");
    });
    document.getElementById("quote-fx-run-btn")?.addEventListener("click", runFxHedging);
    document.getElementById("quote-evm-run-btn")?.addEventListener("click", runEvmPostmortem);
    document.getElementById("quote-evm-xlsx-btn")?.addEventListener("click", () => {
      downloadEvmBinary("/quotations/rotorcraft/evm-postmortem/export-xlsx", "aeroregu_evm_postmortem.xlsx");
    });
    document.getElementById("quote-evm-pdf-btn")?.addEventListener("click", () => {
      downloadEvmBinary("/quotations/rotorcraft/evm-postmortem/export-pdf", "aeroregu_signed_evm.pdf");
    });
    document.getElementById("quote-allow-arb-btn")?.addEventListener("click", runAllowableArbLookup);
    document.getElementById("quote-stress-dossier-run-btn")?.addEventListener("click", runBatchStressDossier);
    document.getElementById("quote-stress-xlsx-btn")?.addEventListener("click", () => {
      downloadStressDossierBinary("/calc/batch-stress-dossier/export-xlsx", "aeroregu_stress_dossier.xlsx");
    });
    document.getElementById("quote-stress-pdf-btn")?.addEventListener("click", () => {
      downloadStressDossierBinary("/calc/batch-stress-dossier/export-pdf", "aeroregu_signed_stress_dossier.pdf");
    });
    document.getElementById("quote-passkey-reauth-btn")?.addEventListener("click", triggerPasskeyStepUpReauth);

    async function runLoadEnvelope() {
      const statusEl = document.getElementById("quote-env-status");
      const tbody = document.querySelector("#quote-env-table tbody");
      const envId = document.getElementById("quote-env-id")?.value || "ENV-H145-CS29-V5";
      try {
        const resp = await fetch("/calc/load-envelope/combine", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ envelope_id: envId, tenant_id: tenantOf(), record: false }),
        });
        const json = await resp.json();
        latestLoadEnvelope = json?.result || {};
        if (statusEl) {
          safeSetHTML(
            statusEl,
            `Envolvente <strong>${escapeHtml(latestLoadEnvelope.envelope_id)}</strong>: ${escapeHtml(latestLoadEnvelope.evaluated_pairs_count)} pares | MS Mín=<strong>${escapeHtml(latestLoadEnvelope.global_ms_min)}</strong> (${escapeHtml(latestLoadEnvelope.governing_component)} / ${escapeHtml(latestLoadEnvelope.governing_combo_id)})`
          );
        }
        if (tbody) {
          tbody.innerHTML = (latestLoadEnvelope.component_envelopes || [])
            .map(
              (c) => `
              <tr>
                <th scope="row">${escapeHtml(c.component_id)}</th>
                <td>${escapeHtml(c.material_id)}</td>
                <td>${escapeHtml(c.governing_combo_id)}</td>
                <td>${escapeHtml(c.governing_factored_stress_mpa)} / ${escapeHtml(c.allowable_mpa)}</td>
                <td>${escapeHtml(c.governing_ms)} (Arb ${escapeHtml(c.governing_arb_lower_ms)})</td>
              </tr>`
            )
            .join("");
        }
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error Load Envelope: ${err?.message || err}`;
      }
    }

    async function downloadEnvelopeBinary(url, filename) {
      const statusEl = document.getElementById("quote-env-status");
      const envId = document.getElementById("quote-env-id")?.value || "ENV-H145-CS29-V5";
      try {
        const payload = latestLoadEnvelope ? { envelope_report: latestLoadEnvelope } : { envelope_id: envId, tenant_id: tenantOf() };
        const resp = await fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
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
        if (statusEl) statusEl.textContent = `Descargado Envolvente: ${filename}`;
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error descargando ${filename}: ${err?.message || err}`;
      }
    }

    async function runMocMatrix() {
      const statusEl = document.getElementById("quote-moc-status");
      const tbody = document.querySelector("#quote-moc-table tbody");
      const programId = document.getElementById("quote-moc-program-id")?.value || "PROG-H145-STC";
      const rev = document.getElementById("quote-moc-revision")?.value || "REV-A";
      try {
        const resp = await fetch("/certification/moc-matrix", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            program_id: programId,
            active_ecn_revision: rev,
            stress_dossier: latestStressDossier || undefined,
            load_envelope: latestLoadEnvelope || undefined,
            tenant_id: tenantOf(),
            record: false,
          }),
        });
        const json = await resp.json();
        latestMocMatrix = json?.result || {};
        if (statusEl) {
          safeSetHTML(
            statusEl,
            `Matriz MoC <strong>${escapeHtml(latestMocMatrix.program_id)}</strong> (${escapeHtml(latestMocMatrix.active_ecn_revision)}): Readiness=<strong>${escapeHtml(latestMocMatrix.readiness_pct)}%</strong> (${escapeHtml(latestMocMatrix.ready_count)}/${escapeHtml(latestMocMatrix.requirement_count)}) | Gaps abiertos=${escapeHtml(latestMocMatrix.open_gap_count)}`
          );
        }
        if (tbody) {
          tbody.innerHTML = (latestMocMatrix.matrix_rows || [])
            .map(
              (r) => `
              <tr>
                <th scope="row">${escapeHtml(r.cs_paragraph)}</th>
                <td>${escapeHtml((r.required_mocs || []).join(", "))}</td>
                <td>${escapeHtml(r.min_governing_ms)}</td>
                <td>${escapeHtml(r.revision)}</td>
                <td>${escapeHtml(r.status)}</td>
              </tr>`
            )
            .join("");
        }
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error MoC Matrix: ${err?.message || err}`;
      }
    }

    async function downloadMocBinary(url, filename) {
      const statusEl = document.getElementById("quote-moc-status");
      const programId = document.getElementById("quote-moc-program-id")?.value || "PROG-H145-STC";
      const rev = document.getElementById("quote-moc-revision")?.value || "REV-A";
      try {
        const payload = latestMocMatrix
          ? { moc_matrix: latestMocMatrix }
          : { program_id: programId, active_ecn_revision: rev, stress_dossier: latestStressDossier || undefined, load_envelope: latestLoadEnvelope || undefined };
        const resp = await fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
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
        if (statusEl) statusEl.textContent = `Descargado MoC Matrix: ${filename}`;
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error descargando ${filename}: ${err?.message || err}`;
      }
    }

    async function runRiskFrontier() {
      const statusEl = document.getElementById("quote-risk-status");
      const tbody = document.querySelector("#quote-risk-table tbody");
      const baseCost = document.getElementById("quote-risk-base-cost")?.value || "375000";
      const basePrice = document.getElementById("quote-risk-base-price")?.value || "480000";
      const scenarios = Number(document.getElementById("quote-risk-scenarios")?.value || 500);
      try {
        const resp = await fetch("/quotations/rotorcraft/risk-frontier", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({
            base_cost_eur: baseCost,
            base_quote_price_eur: basePrice,
            num_scenarios: scenarios,
            baseline_dossier: latestDossier || undefined,
          }),
        });
        const json = await resp.json();
        latestRiskReport = json?.result || {};
        const rec = latestRiskReport.recommended_bid || {};
        const dist = latestRiskReport.cost_distribution || {};
        const z3p = latestRiskReport.formal_margin_floor_proof || {};
        if (statusEl) {
          safeSetHTML(
            statusEl,
            `Halton QMC (N=${escapeHtml(latestRiskReport.num_scenarios)}): Coste P50=<strong>${escapeHtml(dist.cost_p50_eur)} EUR</strong> / P80=<strong>${escapeHtml(dist.cost_p80_eur)} EUR</strong> | Oferta Óptima EMV=<strong>${escapeHtml(rec.recommended_bid_price_eur)} EUR</strong> (EMV=${escapeHtml(rec.max_expected_monetary_value_eur)} EUR, Win=${escapeHtml(rec.win_probability_pct)}%) | Z3=${escapeHtml(z3p.status)}`
          );
        }
        if (tbody) {
          tbody.innerHTML = (latestRiskReport.pareto_frontier || [])
            .map(
              (c) => `
              <tr>
                <th scope="row">${escapeHtml(c.candidate_id)}${c.recommended_max_emv ? " ★" : ""}</th>
                <td>${escapeHtml(c.bid_price_eur)}</td>
                <td>${escapeHtml(c.win_probability_pct)}%</td>
                <td>${escapeHtml(c.expected_margin_pct)}%</td>
                <td>${escapeHtml(c.expected_monetary_value_eur)}</td>
              </tr>`
            )
            .join("");
        }
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error Risk Frontier: ${err?.message || err}`;
      }
    }

    async function downloadRiskBinary(url, filename) {
      const statusEl = document.getElementById("quote-risk-status");
      const baseCost = document.getElementById("quote-risk-base-cost")?.value || "375000";
      const basePrice = document.getElementById("quote-risk-base-price")?.value || "480000";
      const scenarios = Number(document.getElementById("quote-risk-scenarios")?.value || 500);
      try {
        const payload = latestRiskReport
          ? { risk_report: latestRiskReport }
          : { base_cost_eur: baseCost, base_quote_price_eur: basePrice, num_scenarios: scenarios };
        const resp = await fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
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
        if (statusEl) statusEl.textContent = `Descargado Risk Frontier: ${filename}`;
      } catch (err) {
        if (statusEl) statusEl.textContent = `Error descargando ${filename}: ${err?.message || err}`;
      }
    }

    document.getElementById("quote-env-run-btn")?.addEventListener("click", runLoadEnvelope);
    document.getElementById("quote-env-xlsx-btn")?.addEventListener("click", () => {
      downloadEnvelopeBinary("/calc/load-envelope/export-xlsx", "aeroregu_load_envelope.xlsx");
    });
    document.getElementById("quote-env-pdf-btn")?.addEventListener("click", () => {
      downloadEnvelopeBinary("/calc/load-envelope/export-pdf", "aeroregu_signed_load_envelope.pdf");
    });
    document.getElementById("quote-moc-run-btn")?.addEventListener("click", runMocMatrix);
    document.getElementById("quote-moc-xlsx-btn")?.addEventListener("click", () => {
      downloadMocBinary("/certification/moc-matrix/export-xlsx", "aeroregu_moc_matrix.xlsx");
    });
    document.getElementById("quote-moc-pdf-btn")?.addEventListener("click", () => {
      downloadMocBinary("/certification/moc-matrix/export-pdf", "aeroregu_signed_moc_matrix.pdf");
    });
    document.getElementById("quote-risk-run-btn")?.addEventListener("click", runRiskFrontier);
    document.getElementById("quote-risk-xlsx-btn")?.addEventListener("click", () => {
      downloadRiskBinary("/quotations/rotorcraft/risk-frontier/export-xlsx", "aeroregu_risk_frontier.xlsx");
    });
    document.getElementById("quote-risk-pdf-btn")?.addEventListener("click", () => {
      downloadRiskBinary("/quotations/rotorcraft/risk-frontier/export-pdf", "aeroregu_signed_risk_frontier.pdf");
    });

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
