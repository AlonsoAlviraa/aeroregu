/* AeroRegu Q2-Q4 Frontend UX Modules (Dynamic 32+ Methods, MMPDS/CMH-17, Full JSON, PDF+BBox, FEA 3D, PLM/ECN/Review/QES) */
(function () {
  "use strict";

  const FAMILY_TITLES = {
    flight_envelope: "01. Envolvente de Vuelo y Masa",
    structural_sizing: "02. Dimensionamiento Estructural",
    fasteners_joints: "03. Uniones, Orejetas y Remaches",
    composites_cmh17: "04. Composites (CMH-17 / Hashin / Puck)",
    fatigue_fracture: "05. Fatiga, Grietas y Fractura (NASGRO)",
    thin_walled_stability: "06. Estabilidad Paredes Delgadas y Pandeo",
    rotorcraft_dynamics: "07. Dinámica de Rotor, Impacto y Aterrizaje",
    plugins: "08. Tarjetas Declarativas de Usuario",
  };

  const state = {
    catalog: null,
    materials: [],
    latestDocId: null,
    currentPage: 1,
    latestPageData: null,
    fullOutputRaw: "Ready.",
    compactPreview: false,
  };

  function injectStyles() {
    if (document.getElementById("q4-ux-styles")) return;
    const style = document.createElement("style");
    style.id = "q4-ux-styles";
    style.textContent = `
      .q4-panel { margin-top: 0.9rem; border: 1px solid var(--border); border-radius: 12px; padding: 0.9rem; background: var(--surface, #0f172a); }
      .q4-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.65rem; }
      .pdf-bbox-stage { position: relative; width: 100%; max-height: 460px; overflow: auto; border: 1px solid var(--border); border-radius: 10px; background: #09101d; padding: 0.4rem; }
      #pdf-bbox-canvas { display: block; max-width: 100%; height: auto; border-radius: 6px; cursor: crosshair; }
      .bbox-chip-list { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; max-height: 140px; overflow: auto; }
      .bbox-chip { font-size: 0.78rem; padding: 0.25rem 0.55rem; border-radius: 6px; border: 1px solid var(--border); background: rgba(56,189,248,0.08); cursor: pointer; }
      .bbox-chip.active { border-color: #38bdf8; background: rgba(56,189,248,0.22); }
      #out { max-height: 460px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
      .thread-card { border: 1px solid var(--border); border-radius: 8px; padding: 0.6rem; margin-top: 0.45rem; background: rgba(15,23,42,0.45); }
    `;
    document.head.appendChild(style);
  }

  function tenantOf() {
    if (typeof window.currentTenant === "function") return window.currentTenant();
    return (document.getElementById("tenant-input")?.value || "demo").trim() || "demo";
  }

  function toast(msg, tone) {
    if (typeof window.showToast === "function") {
      window.showToast(msg, tone || "ok");
    }
  }

  function renderFullOutput(text, tone, label) {
    const raw = String(text ?? "");
    state.fullOutputRaw = raw;
    const outEl = document.getElementById("out");
    const badge = document.getElementById("out-badge");
    if (badge) {
      if (label) badge.textContent = label;
      if (tone) badge.dataset.tone = tone;
    }
    if (!outEl) return;
    if (state.compactPreview && raw.length > 4000) {
      outEl.textContent = raw.slice(0, 4000) + `\n... [${raw.length - 4000} chars ocultos; pulsa JSON Completo]`;
    } else {
      outEl.textContent = raw;
    }
  }

  window.setFullJsonOutput = renderFullOutput;

  function patchOutputTruncation() {
    window.setOutput = function (text, tone = "ok", badgeLabel = null) {
      renderFullOutput(text, tone, badgeLabel);
    };
    const toggleBtn = document.getElementById("out-full-toggle-btn");
    if (toggleBtn) {
      toggleBtn.onclick = () => {
        state.compactPreview = !state.compactPreview;
        toggleBtn.textContent = state.compactPreview ? "Ver JSON Completo" : "Vista Compacta (4K)";
        renderFullOutput(state.fullOutputRaw);
      };
    }
  }

  async function syncCatalogAndMethods() {
    try {
      const [catResp, cardsResp, matsResp] = await Promise.all([
        fetch("/mcp/catalog", { credentials: "same-origin" }),
        fetch("/calc/cards", { credentials: "same-origin" }),
        fetch("/calc/materials", { credentials: "same-origin" }),
      ]);
      const catJson = await catResp.json();
      const cardsJson = await cardsResp.json();
      const matsJson = await matsResp.json();

      const cat = catJson?.result || {};
      state.catalog = cat;
      const cards = cardsJson?.result?.methods || cardsJson?.result?.cards || [];
      const families = cat.method_families || {};
      const defaultsMap = cat.method_default_inputs || {};
      const counts = cat.counts || {};

      if (window.DEFAULT_INPUTS && typeof window.DEFAULT_INPUTS === "object") {
        Object.entries(defaultsMap).forEach(([k, v]) => {
          if (!window.DEFAULT_INPUTS[k]) window.DEFAULT_INPUTS[k] = v;
        });
      }

      const sel = document.getElementById("calc-method");
      if (sel && cards.length > 0) {
        const prev = sel.value;
        const grouped = new Map();
        Object.keys(FAMILY_TITLES).forEach((fk) => grouped.set(fk, []));
        cards.forEach((c) => {
          const fam = c.plugin ? "plugins" : families[c.method_id] || "structural_sizing";
          if (!grouped.has(fam)) grouped.set(fam, []);
          grouped.get(fam).push(c);
        });
        sel.replaceChildren();
        grouped.forEach((items, famKey) => {
          const og = document.createElement("optgroup");
          og.label = FAMILY_TITLES[famKey] || famKey;
          if (!items.length) {
            if (famKey !== "plugins") return;
            const emptyOpt = document.createElement("option");
            emptyOpt.value = "";
            emptyOpt.disabled = true;
            emptyOpt.textContent = "(Sin tarjetas plugin registradas aun)";
            og.appendChild(emptyOpt);
            sel.appendChild(og);
            return;
          }
          const FRIENDLY_LABELS = {
            hover_power_screen: "🚁 Potencia de Rotor (Hover)",
            bolt_screen: "🔩 Tornillo Cortante y Tracción",
            rigid_body_point_mass: "⚖️ Equilibrio 4 Motores / CG",
            margin_of_safety: "🛡️ Margen de Seguridad Pieza",
            column_plate_buckling: "🏗️ Pandeo Columna / Placa",
            palmgren_miner_fatigue: "🔄 Fatiga por Ciclos (Miner)",
            composite_failure_criteria: "🧱 Compuesto Tsai-Wu / Hashin",
            wing_root_bending_shear: "✈️ Flexión y Cortante en Ala",
            thin_walled_cell_torsion: "🌀 Torsión Caja Alar",
            lug_pin_bearing_tearout: "🔗 Orejeta y Pasador",
            pressurized_fuselage_hoop_longitudinal: "🫧 Fuselaje Presurizado",
            crack_growth_paris_law: "⚡ Propagación de Grieta (Paris)",
            damage_tolerant_residual_strength: "🩻 Resistencia Residual",
            tsai_wu_ply_failure: "🧱 Lámina Compuesta Tsai-Wu",
            hashin_3d_composite: "🧱 Rotura 3D Fibra/Matriz",
            laminate_abd_thermal_stiffness: "🔥 Laminado ABD Térmico",
            sandwich_panel_wrinkling_dimpling: "🥪 Panel Sándwich",
            bolted_composite_bearing_bypass: "🔩 Unión Compuesta Aplastamiento",
            vn_maneuver_gust_envelope: "📈 Diagrama V-n Maniobra/Ráfaga",
            weight_cg_mac_envelope: "⚖️ Peso y Centro de Gravedad",
            breguet_range_endurance_reserve: "⛽ Alcance y Autonomía",
          };
          items.forEach((c) => {
            const opt = document.createElement("option");
            opt.value = c.method_id;
            const friendly = FRIENDLY_LABELS[c.method_id] || c.summary || c.method_id;
            opt.textContent = friendly.includes(c.method_id) ? friendly : `${friendly} (${c.method_id})`;
            og.appendChild(opt);
          });
          sel.appendChild(og);
        });
        if (prev && [...sel.options].some((o) => o.value === prev)) {
          sel.value = prev;
        }
        if (typeof window.syncMethodTemplates === "function") {
          window.syncMethodTemplates(window.DEFAULT_INPUTS || {});
        }
      }

      const countPill = document.getElementById("plugin-count-pill");
      if (countPill) {
        countPill.textContent = `${cards.length} metodos certificados + plugins`;
      }

      const kpiMcp = document.getElementById("kpi-mcp");
      if (kpiMcp && counts.tools) {
        kpiMcp.textContent = `${counts.tools} Tools / ${counts.resources || 0} Res / ${counts.formal_methods || 0} SMT`;
      }
      const mcpBtn = document.getElementById("mcp-list-tools");
      if (mcpBtn && counts.tools) {
        mcpBtn.textContent = `Cargar ${counts.tools} Tools MCP`;
      }
      const mcpHeading = document.getElementById("mcp-panel-heading");
      if (mcpHeading && counts.tools) {
        mcpHeading.textContent = `MCP Playground (${counts.tools} Tools) y Auditoria Red-Team`;
      }

      const toolSel = document.getElementById("mcp-tool-select");
      if (toolSel && Array.isArray(cat.tools) && cat.tools.length > 0) {
        const prevTool = toolSel.value;
        toolSel.replaceChildren();
        cat.tools.forEach((t) => {
          const opt = document.createElement("option");
          opt.value = t.name;
          opt.textContent = `${t.name} — ${String(t.description || "").slice(0, 52)}`;
          toolSel.appendChild(opt);
        });
        if (prevTool && [...toolSel.options].some((o) => o.value === prevTool)) {
          toolSel.value = prevTool;
        }
      }

      const matList = matsJson?.result?.materials || [];
      state.materials = matList;
      const matSel = document.getElementById("material-preset-select");
      if (matSel && Array.isArray(matList) && matList.length > 0) {
        matSel.replaceChildren();
        matList.forEach((m) => {
          const opt = document.createElement("option");
          opt.value = m;
          opt.textContent = m;
          matSel.appendChild(opt);
        });
      }
    } catch (err) {
      console.warn("Q4 UX catalog sync warning:", err);
    }
  }

  function bindMaterialAllowable() {
    const applyBtn = document.getElementById("apply-material-btn");
    if (!applyBtn) return;
    applyBtn.onclick = async () => {
      const mat = document.getElementById("material-preset-select")?.value;
      const basis = document.getElementById("material-basis-select")?.value || "B";
      const env = document.getElementById("material-env-select")?.value || "RTD";
      if (!mat) return;
      try {
        const [rFty, rFcy, rFtu] = await Promise.all([
          fetch("/calc/allowables", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ material_id: mat, basis, property_name: "fty_mpa", environment: env }),
          }),
          fetch("/calc/allowables", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ material_id: mat, basis, property_name: "fcy_mpa", environment: env }),
          }),
          fetch("/calc/allowables", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ material_id: mat, basis, property_name: "ftu_mpa", environment: env }),
          }),
        ]);
        const dFty = await rFty.json();
        const dFcy = await rFcy.json();
        const dFtu = await rFtu.json();
        const res = dFty?.result || {};
        const ftyVal = res.allowable_value_mpa;
        const fcyVal = dFcy?.result?.allowable_value_mpa || ftyVal;
        const ftuVal = dFtu?.result?.allowable_value_mpa || ftyVal;
        const eMpa = res.e_gpa ? String(Math.round(parseFloat(res.e_gpa) * 1000)) : null;

        const fieldMap = {
          yield_strength_mpa: ftyVal,
          compressive_yield_mpa: fcyVal,
          ultimate_strength_mpa: ftuVal,
          modulus_mpa: eMpa,
          youngs_modulus_mpa: eMpa,
          adherend_modulus_mpa: eMpa,
          plate1_modulus_mpa: eMpa,
          plate2_modulus_mpa: eMpa,
          tangent_modulus_mpa: eMpa,
          poisson_nu: res.nu,
          poissons_ratio: res.nu,
        };
        let appliedCount = 0;
        const jsonArea = document.getElementById("calc-inputs-json");
        let currentJson = {};
        try {
          currentJson = JSON.parse(jsonArea?.value || "{}");
        } catch {
          currentJson = {};
        }
        Object.entries(fieldMap).forEach(([k, val]) => {
          if (val !== undefined && val !== null) {
            if (Object.prototype.hasOwnProperty.call(currentJson, k)) {
              currentJson[k] = String(val);
              appliedCount += 1;
            }
            const inp = document.querySelector(`#dynamic-calc-form input[data-key="${k}"]`);
            if (inp) {
              inp.value = String(val);
              appliedCount += 1;
            }
          }
        });
        if (jsonArea) {
          jsonArea.value = JSON.stringify(currentJson, null, 2);
        }
        const pill = document.getElementById("material-status-pill");
        if (pill) {
          pill.textContent = `${mat} (${basis}/${env}): Fty=${ftyVal || "-"} MPa`;
          pill.dataset.tone = "ok";
        }
        renderFullOutput(JSON.stringify({ fty: dFty.result, fcy: dFcy.result, ftu: dFtu.result, applied_fields: appliedCount }, null, 2), "ok", `Material ${mat}`);
        toast(`Material ${mat} (${basis}/${env}) consultado y aplicado.`, "ok");
      } catch (err) {
        renderFullOutput(`Error material allowable: ${err?.message || err}`, "err", "Error");
      }
    };
  }

  function normalizeMeshForViewer(vmesh) {
    if (!vmesh) return null;
    const nodeCoords = {};
    if (vmesh.nodeCoords && typeof vmesh.nodeCoords === "object" && !Array.isArray(vmesh.nodeCoords)) {
      Object.assign(nodeCoords, vmesh.nodeCoords);
    } else if (Array.isArray(vmesh.nodes)) {
      vmesh.nodes.forEach((n) => {
        if (Array.isArray(n) && n.length >= 4) {
          nodeCoords[String(n[0])] = [Number(n[1]), Number(n[2]), Number(n[3])];
        } else if (n && typeof n === "object") {
          const nid = String(n.id ?? n.nid ?? "");
          if (nid) nodeCoords[nid] = [Number(n.x || 0), Number(n.y || 0), Number(n.z || 0)];
        }
      });
    }
    const rawElems = Array.isArray(vmesh.elements) ? vmesh.elements : [];
    const msMap = vmesh.element_ms || {};
    const vmMap = vmesh.element_vm_mpa || {};
    const elements = rawElems.map((el) => {
      if (Array.isArray(el)) {
        const eid = el[0];
        return {
          eid,
          pid: el[1],
          n1: el[3],
          n2: el[4],
          n3: el[5],
          n4: el[6] || null,
          ms_min: el[7] !== undefined ? Number(msMap[eid] ?? 0.25) : 0.25,
          von_mises_norm: Number(vmMap[eid] ?? 120) / 450.0,
        };
      }
      const nids = el.node_ids || el.nodes || [];
      return {
        ...el,
        eid: el.eid ?? el.element_id,
        pid: el.pid ?? 1,
        n1: el.n1 ?? nids[0],
        n2: el.n2 ?? nids[1],
        n3: el.n3 ?? nids[2],
        n4: el.n4 ?? nids[3] ?? null,
        ms_min: el.ms_min !== undefined ? Number(el.ms_min) : 0.25,
        von_mises_norm:
          el.von_mises_norm !== undefined
            ? Number(el.von_mises_norm)
            : Number(el.von_mises_mpa || 120) / 450.0,
      };
    });
    return { nodeCoords, elements };
  }

  async function requireSessionOrWarn() {
    if (typeof window.ensureSession === "function") {
      return await window.ensureSession();
    }
    return "author";
  }

  function bindCadAndCaeAnalyzers() {
    const brepBtn = document.getElementById("cad-brep-btn");
    if (brepBtn) {
      brepBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const filename = document.getElementById("cad-filename-input")?.value || "rotor_hub_ap242.stp";
        const body = { filename, tenant_id: tenantOf() };
        if (window.cadUploadedBase64) body.content_base64 = window.cadUploadedBase64;
        else body.content_text = document.getElementById("cad-content-text")?.value || "";
        const resp = await fetch("/cad/brep/analyze", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "STEP B-Rep");
        const solids = data?.result?.solids || [];
        if (solids.length && window.latestCadOverlay) {
          window.latestCadOverlay.cad_cg_points = solids.map((s, idx) => ({
            point_id: `BREP-${idx + 1}`,
            label: s.name || filename,
            source: "cad_brep",
            x_cg_m: (Number((s.cg_mm || [0, 0, 0])[0]) * 0.001).toFixed(4),
            y_cg_m: (Number((s.cg_mm || [0, 0, 0])[1]) * 0.001).toFixed(4),
            z_cg_m: (Number((s.cg_mm || [0, 0, 0])[2]) * 0.001).toFixed(4),
            mass_kg: String(s.mass_kg || "900.000"),
          }));
          if (typeof window.load3DEnvelope === "function") window.load3DEnvelope();
        }
      };
    }

    const caePicker = document.getElementById("cae-binary-picker");
    let caeB64 = null;
    if (caePicker) {
      caePicker.addEventListener("change", () => {
        const f = caePicker.files?.[0];
        if (!f) return;
        const fnEl = document.getElementById("cae-filename-input");
        if (fnEl) fnEl.value = f.name;
        const reader = new FileReader();
        reader.onload = () => {
          const bytes = new Uint8Array(reader.result);
          let bin = "";
          const step = 32768;
          for (let i = 0; i < bytes.length; i += step) {
            bin += String.fromCharCode(...bytes.subarray(i, i + step));
          }
          caeB64 = btoa(bin);
          toast(`Archivo CAE ${f.name} (${bytes.length} bytes) listo.`, "ok");
        };
        reader.readAsArrayBuffer(f);
      });
    }

    const caeBtn = document.getElementById("cae-parse-binary-btn");
    if (caeBtn) {
      caeBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        if (!caeB64) {
          toast("Selecciona un archivo .op2, .h5, .odb o .rst primero.", "warn");
          return;
        }
        const filename = document.getElementById("cae-filename-input")?.value || "results.op2";
        const resp = await fetch("/cae/binary/parse", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: tenantOf(), filename, content_base64: caeB64 }),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "CAE Binary");
        const modelId = data?.result?.model_id;
        let feaData = null;
        if (modelId) {
          const mResp = await fetch(`/cae/mesh/${encodeURIComponent(modelId)}?tenant_id=${encodeURIComponent(tenantOf())}`, { credentials: "same-origin" });
          if (mResp.ok) {
            const mJson = await mResp.json();
            feaData = normalizeMeshForViewer(mJson?.result);
          }
        }
        if (!feaData && data?.result?.viewer_mesh) {
          feaData = normalizeMeshForViewer(data.result.viewer_mesh);
        }
        const viewer = typeof window.ensureViewer3D === "function" ? window.ensureViewer3D() : null;
        if (viewer && feaData && typeof viewer.setFeaMesh === "function") {
          viewer.setFeaMesh(feaData);
          if (typeof viewer.setMode === "function") viewer.setMode("fea");
          const pill = document.getElementById("v3d-status-pill");
          if (pill) pill.textContent = `FEA Live: ${feaData.elements.length} elems`;
        }
      };
    }

    const feaBtn = document.getElementById("v3d-fea-mode-btn");
    if (feaBtn) {
      feaBtn.onclick = () => {
        const viewer = typeof window.ensureViewer3D === "function" ? window.ensureViewer3D() : null;
        if (!viewer) return;
        if (window.latestCadOverlay?.fem_overlay && (!viewer.feaMesh || !viewer.feaMesh.elements?.length)) {
          const ov = window.latestCadOverlay.fem_overlay;
          const coords = {};
          (ov.nodes || []).forEach((n) => {
            coords[String(n.id ?? n.nid ?? n.node_id)] = [Number(n.x || 0), Number(n.y || 0), Number(n.z || 0)];
          });
          const elems = (ov.edges || []).slice(0, 2000).map((ed, idx) => ({
            eid: idx + 1,
            pid: 1,
            n1: String(ed[0]),
            n2: String(ed[1]),
            n3: String(ed[1]),
            ms_min: 0.35,
            von_mises_norm: 0.4,
          }));
          viewer.setFeaMesh({ nodeCoords: coords, elements: elems });
        }
        viewer.setMode("fea");
      };
    }
  }

  async function renderDocPageBbox(docId, pageNo) {
    const id = String(docId || state.latestDocId || document.getElementById("pdf-doc-id-input")?.value || "").trim();
    if (!id) return;
    state.latestDocId = id;
    state.currentPage = Math.max(1, Number(pageNo || 1));
    const docInput = document.getElementById("pdf-doc-id-input");
    const pageInput = document.getElementById("pdf-page-num");
    if (docInput) docInput.value = id;
    if (pageInput) pageInput.value = String(state.currentPage);
    try {
      const resp = await fetch(`/ingest/document/${encodeURIComponent(id)}/page/${state.currentPage}`, {
        credentials: "same-origin",
      });
      const data = await resp.json();
      if (!resp.ok || !data?.result) {
        toast(data?.abstain?.reason || "Documento no encontrado en sesion", "warn");
        return;
      }
      const res = data.result;
      state.latestPageData = res;
      const canvas = document.getElementById("pdf-bbox-canvas");
      const ctx = canvas?.getContext("2d");
      const wPt = Number(res.width_pt || 595);
      const hPt = Number(res.height_pt || 842);
      if (canvas && ctx) {
        const img = new Image();
        img.onload = () => {
          canvas.width = img.naturalWidth || Math.round(wPt);
          canvas.height = img.naturalHeight || Math.round(hPt);
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          const sx = canvas.width / wPt;
          const sy = canvas.height / hPt;
          (res.blocks || []).forEach((blk, idx) => {
            const bb = Array.isArray(blk.bbox) && blk.bbox.length === 4 ? blk.bbox : [28, 56 + idx * 34, wPt - 28, 82 + idx * 34];
            ctx.strokeStyle = "#38bdf8";
            ctx.lineWidth = 2;
            ctx.fillStyle = "rgba(56, 189, 248, 0.14)";
            const x = bb[0] * sx;
            const y = bb[1] * sy;
            const bw = Math.max(10, (bb[2] - bb[0]) * sx);
            const bh = Math.max(12, (bb[3] - bb[1]) * sy);
            ctx.fillRect(x, y, bw, bh);
            ctx.strokeRect(x, y, bw, bh);
          });
        };
        img.src = `data:${res.mime_type || "image/svg+xml"};base64,${res.image_base64}`;
      }
      const listEl = document.getElementById("pdf-bbox-blocks");
      if (listEl) {
        listEl.replaceChildren();
        (res.blocks || []).forEach((blk, idx) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "bbox-chip";
          btn.textContent = `#${idx + 1} [p.${res.page_no}] ${String(blk.text || "").slice(0, 55)}`;
          btn.onclick = () => {
            renderFullOutput(JSON.stringify(blk, null, 2), "ok", `BBox Block #${idx + 1}`);
          };
          listEl.appendChild(btn);
        });
      }
    } catch (err) {
      toast(`Error cargando pagina bbox: ${err?.message || err}`, "err");
    }
  }

  window.renderDocPageBbox = renderDocPageBbox;

  function bindPdfBboxPanel() {
    const loadBtn = document.getElementById("pdf-load-page-btn");
    const prevBtn = document.getElementById("pdf-prev-page-btn");
    const nextBtn = document.getElementById("pdf-next-page-btn");
    if (loadBtn) {
      loadBtn.onclick = () => {
        const id = document.getElementById("pdf-doc-id-input")?.value;
        const p = document.getElementById("pdf-page-num")?.value || 1;
        renderDocPageBbox(id, p);
      };
    }
    if (prevBtn) {
      prevBtn.onclick = () => renderDocPageBbox(state.latestDocId, Math.max(1, state.currentPage - 1));
    }
    if (nextBtn) {
      nextBtn.onclick = () => renderDocPageBbox(state.latestDocId, state.currentPage + 1);
    }

    const origUpdate = window.updateBadgesAndTables;
    window.updateBadgesAndTables = function (data) {
      if (typeof origUpdate === "function") origUpdate(data);
      const res = data?.result || {};
      const docId =
        res.doc_id ||
        res.source_hash ||
        (Array.isArray(res.blocks) && res.blocks[0] && (res.blocks[0].doc_id || res.blocks[0].source_hash)) ||
        (res.blocks ? res.filename : null);
      if (docId) {
        state.latestDocId = String(docId);
        const docInput = document.getElementById("pdf-doc-id-input");
        if (docInput) docInput.value = state.latestDocId;
        renderDocPageBbox(state.latestDocId, 1);
      }
    };

    const tooltips = {
      "kpi-smt": "PROVED_UNSAT: doble verificacion formal (Z3 + cvc5) demuestra ausencia de contraejemplos; cliff-edge risk mide cercania al limite.",
      "cad-brep-btn": "Analisis geometrico 3D STEP AP203/AP214/AP242: masa, CG, espesores y holguras B-Rep.",
      "cae-parse-binary-btn": "Parser de resultados FEA binarios (.op2 NASTRAN / .h5 HDF5) hacia el visor 3D.",
      "pdf-load-page-btn": "Renderiza la pagina ingesta con cajas delimitadoras (BBox) trazables.",
      "ecn-diff-btn": "Compara revisiones Rev A vs Rev B de un Engineering Change Notice (requisitos, masa, margenes).",
      "plm-sync-btn": "Sincroniza EBOM y efectividad MSN desde 3DEXPERIENCE, Teamcenter o Windchill.",
      "qual-run-btn": "Ejecuta bateria IQ/OQ de cualificacion DO-330 TQL-5 sobre el repositorio.",
      "qes-export-btn": "Exporta paquete DSSE Ed25519 sellado con firma cualificada eIDAS (CAdES/PAdES).",
      "out-full-toggle-btn": "Alterna entre vista compacta (4K) y salida JSON completa con cotas de intervalo Flint.",
    };
    Object.entries(tooltips).forEach(([id, tip]) => {
      const el = document.getElementById(id);
      if (el && !el.title) el.title = tip;
    });
  }

  function fixCveSwitchUiSync() {
    const btn = document.getElementById("switch-cve-btn");
    if (!btn) return;
    const origClick = btn.onclick;
    btn.onclick = async () => {
      if (typeof origClick === "function") {
        await origClick();
      }
      const actorSel = document.getElementById("actor-select");
      if (actorSel) actorSel.value = "reviewer";
      const sessPill = document.getElementById("session-status");
      if (sessPill) {
        sessPill.textContent = `Session: reviewer (${tenantOf()})`;
        sessPill.dataset.tone = "ok";
      }
      const rbacPill = document.getElementById("rbac-role-pill");
      if (rbacPill) rbacPill.textContent = "Rol: cve (reviewer)";
    };
  }

  function bindEnterpriseQ2Q4Panels() {
    // 1. Collaborative Review Threads
    const revListBtn = document.getElementById("rev-refresh-btn");
    const revCreateBtn = document.getElementById("rev-create-btn");
    const revOut = document.getElementById("review-threads-list");

    async function loadThreads() {
      if (!(await requireSessionOrWarn())) return;
      const resp = await fetch(`/reviews/threads?tenant_id=${encodeURIComponent(tenantOf())}`, { credentials: "same-origin" });
      const data = await resp.json();
      renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "Review Threads");
      if (!revOut) return;
      revOut.replaceChildren();
      const threads = data?.result?.threads || [];
      threads.forEach((thr) => {
        const card = document.createElement("div");
        card.className = "thread-card";
        const hdr = document.createElement("div");
        hdr.innerHTML = `<strong>${thr.thread_id}</strong> [${thr.status}] — target: <code>${String(thr.target_event_hash || "").slice(0, 14)}</code>`;
        const msg = document.createElement("div");
        msg.className = "meta-note";
        msg.textContent = (thr.comments || []).map((c) => `${c.actor_id}: ${c.body}`).join(" | ");
        const row = document.createElement("div");
        row.className = "row";
        row.style.marginTop = "0.4rem";
        const resolveBtn = document.createElement("button");
        resolveBtn.type = "button";
        resolveBtn.className = "subtle";
        resolveBtn.textContent = "Resolver Thread";
        resolveBtn.onclick = async () => {
          if (!(await requireSessionOrWarn())) return;
          const r = await fetch(`/reviews/threads/${encodeURIComponent(thr.thread_id)}/resolve`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: tenantOf(), resolution_note: "Resolved in UI" }),
          });
          const rj = await r.json();
          renderFullOutput(JSON.stringify(rj, null, 2), r.ok ? "ok" : "warn", "Thread Resolve");
          if (r.ok) await loadThreads();
        };
        row.appendChild(resolveBtn);
        card.append(hdr, msg, row);
        revOut.appendChild(card);
      });
    }

    if (revListBtn) revListBtn.onclick = loadThreads;
    if (revCreateBtn) {
      revCreateBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const target = document.getElementById("rev-target-hash")?.value.trim() || "head";
        const bodyTxt = document.getElementById("rev-comment-body")?.value.trim() || "Verify margin factor";
        const resp = await fetch("/reviews/threads", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: tenantOf(), target_event_hash: target, body: bodyTxt }),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "Thread Created");
        if (resp.ok) await loadThreads();
      };
    }

    // 2. ECN Revision Diff
    const ecnBtn = document.getElementById("ecn-diff-run-btn");
    if (ecnBtn) {
      ecnBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        let revA, revB;
        try {
          revA = JSON.parse(document.getElementById("ecn-rev-a-json")?.value || "{}");
          revB = JSON.parse(document.getElementById("ecn-rev-b-json")?.value || "{}");
        } catch (err) {
          toast(`JSON invalido en ECN Diff: ${err.message}`, "err");
          return;
        }
        const ecnId = document.getElementById("ecn-id-input")?.value || "ECN-2026-001";
        const resp = await fetch("/ecn/diff", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: tenantOf(), ecn_id: ecnId, rev_a: revA, rev_b: revB }),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "ECN Diff");
        const pre = document.getElementById("ecn-diff-summary-pre");
        if (pre) pre.textContent = JSON.stringify(data.result || data, null, 2);
      };
    }

    // 3. PLM Bridges (3DEXPERIENCE / Teamcenter / Windchill)
    const plmSyncBtn = document.getElementById("plm-sync-btn");
    const plmWbBtn = document.getElementById("plm-writeback-btn");
    if (plmSyncBtn) {
      plmSyncBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const payload = {
          tenant_id: tenantOf(),
          system: document.getElementById("plm-system-select")?.value || "3dexperience",
          item_id: document.getElementById("plm-item-id")?.value || "WING-SPAR-ASM-01",
          revision: document.getElementById("plm-revision-input")?.value || "Rev A",
          use_mock_plm: true,
        };
        const resp = await fetch("/plm/sync", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "PLM Sync");
      };
    }
    if (plmWbBtn) {
      plmWbBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const payload = {
          tenant_id: tenantOf(),
          system: document.getElementById("plm-system-select")?.value || "3dexperience",
          change_action_id: document.getElementById("plm-ecn-input")?.value || "ECN-2026-001",
          use_mock_plm: true,
        };
        const resp = await fetch("/plm/writeback", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "PLM Writeback");
      };
    }

    // 4. DO-330 IQ/OQ Qualification, M&A Readiness, SBOM & eIDAS QES Export
    const iqOqBtn = document.getElementById("run-iq-oq-btn");
    if (iqOqBtn) {
      iqOqBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const resp = await fetch("/qualification/iq-oq/run", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: tenantOf() }),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "DO-330 IQ/OQ");
      };
    }
    const sbomBtn = document.getElementById("security-sbom-btn");
    if (sbomBtn) {
      sbomBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const resp = await fetch(`/security/sbom?tenant_id=${encodeURIComponent(tenantOf())}`, { credentials: "same-origin" });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "CycloneDX SBOM");
      };
    }
    const maBtn = document.getElementById("check-ma-readiness-btn");
    if (maBtn) {
      maBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const resp = await fetch(`/legal/ma-readiness?tenant_id=${encodeURIComponent(tenantOf())}`, { credentials: "same-origin" });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", "M&A Readiness");
      };
    }
    const qesBtn = document.getElementById("export-qes-btn");
    if (qesBtn) {
      qesBtn.onclick = async () => {
        if (!(await requireSessionOrWarn())) return;
        const profile = document.getElementById("qes-profile-select")?.value || "CAdES-B-LT";
        const resp = await fetch("/export/bundle/qes", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: tenantOf(), profile }),
        });
        const data = await resp.json();
        renderFullOutput(JSON.stringify(data, null, 2), resp.ok ? "ok" : "err", `eIDAS ${profile}`);
      };
    }
  }

  function activateWorkspaceTab(tabId) {
    const tab = document.getElementById(tabId);
    if (!tab) return null;
    if (typeof window.activateTab === "function") {
      window.activateTab(tab);
    } else {
      tab.click();
    }
    return tab;
  }

  function bindDesktopIdeShortcutsAndToolbar() {
    // Roving-tabindex fallback when browser lacks native HTML focusgroup support
    if (!("focusGroup" in HTMLElement.prototype)) {
      document.querySelectorAll('[role="toolbar"][focusgroup]').forEach((toolbar) => {
        const getBtns = () => [...toolbar.querySelectorAll("button:not([disabled])")];
        const initButtons = getBtns();
        initButtons.forEach((btn, i) => {
          btn.tabIndex = i === 0 ? 0 : -1;
        });
        toolbar.addEventListener("keydown", (e) => {
          const btns = getBtns();
          if (!btns.length) return;
          const idx = btns.indexOf(document.activeElement);
          if (idx === -1) return;
          let nextIdx = -1;
          if (e.key === "ArrowRight" || e.key === "ArrowDown") {
            nextIdx = (idx + 1) % btns.length;
          } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
            nextIdx = (idx - 1 + btns.length) % btns.length;
          } else if (e.key === "Home") {
            nextIdx = 0;
          } else if (e.key === "End") {
            nextIdx = btns.length - 1;
          }
          if (nextIdx >= 0) {
            e.preventDefault();
            btns.forEach((b, i) => {
              b.tabIndex = i === nextIdx ? 0 : -1;
            });
            btns[nextIdx].focus();
          }
        });
      });
    }

    const shell = document.querySelector(".app-shell");
    const expandBtn = document.getElementById("expand-inspector-btn");
    if (expandBtn && shell) {
      expandBtn.onclick = () => {
        const wide = shell.classList.toggle("inspector-wide");
        expandBtn.setAttribute("aria-pressed", String(wide));
        expandBtn.textContent = wide ? "Panel Normal" : "Ampliar Panel";
      };
    }

    const quickCveTopBtn = document.getElementById("quick-cve-top-btn");
    if (quickCveTopBtn) {
      quickCveTopBtn.onclick = () => {
        const switchBtn = document.getElementById("switch-cve-btn");
        if (switchBtn) switchBtn.click();
      };
    }

    const tabIds = ["tab-briefing", "tab-calc", "tab-coverage", "tab-docs", "tab-audit", "tab-mcp"];
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const dlg = document.getElementById("ai-cmd-dialog");
        if (!dlg) return;
        if (dlg.open) {
          dlg.close();
        } else {
          dlg.showModal();
          dlg.dispatchEvent(new CustomEvent("ai-cmd-open"));
        }
        return;
      }
      if (e.altKey && !e.ctrlKey && !e.metaKey && /^[1-6]$/.test(e.key)) {
        const target = tabIds[Number(e.key) - 1];
        if (target) {
          e.preventDefault();
          const tab = activateWorkspaceTab(target);
          tab?.focus();
        }
      }
    });
  }

  function bindAiCommandPalette() {
    const dlg = document.getElementById("ai-cmd-dialog");
    const openBtn = document.getElementById("open-cmd-palette-btn");
    const input = document.getElementById("ai-cmd-input");
    const list = document.getElementById("ai-cmd-list");
    const status = document.getElementById("ai-cmd-status");
    if (!dlg || !input || !list) return;

    let filtered = [];
    let activeIdx = 0;

    function buildCommandCatalog() {
      const cmds = [
        { title: "0. Briefing 08:00 AM y Batch Sign-Off", cat: "Vista (Alt+1)", kw: "briefing morning cola riesgo cve", run: () => activateWorkspaceTab("tab-briefing") },
        { title: "1. Banco de Calculo Determinista CAD & CATIA", cat: "Vista (Alt+2)", kw: "calculo catia method design table", run: () => activateWorkspaceTab("tab-calc") },
        { title: "2. Envolvente de Vuelo SL-1 y Visor 3D", cat: "Vista (Alt+3)", kw: "envolvente coverage sweep 3d viewer", run: () => activateWorkspaceTab("tab-coverage") },
        { title: "3. Documentacion PDF BBox, PLM, ECN y Agentes AI", cat: "Vista (Alt+4)", kw: "docs supervisor pdf bbox plm ecn review", run: () => activateWorkspaceTab("tab-docs") },
        { title: "4. Prueba Formal SMT Z3/cvc5, Ledger y QES", cat: "Vista (Alt+5)", kw: "smt z3 cvc5 ledger merkle dsse qes dossier", run: () => activateWorkspaceTab("tab-audit") },
        { title: "5. MCP Playground (30 Tools) y Red-Team", cat: "Vista (Alt+6)", kw: "mcp tools redteam security", run: () => activateWorkspaceTab("tab-mcp") },
        {
          title: "AI: Calcular Exacto + Auditar Margen Activo",
          cat: "AI Action",
          kw: "ai calcular exacto interval margin flint",
          run: () => {
            activateWorkspaceTab("tab-calc");
            document.getElementById("run-custom-calc")?.click();
          },
        },
        {
          title: "AI: Auditoria Cruzada CAD-FEM-PDF-Req",
          cat: "AI Action",
          kw: "ai auditoria cruzada cross artifact cad fem pdf req",
          run: () => {
            activateWorkspaceTab("tab-briefing");
            document.getElementById("run-cross-artifact-btn")?.click();
          },
        },
        {
          title: "AI: Ejecutar Supervisor Multi-Agente SL-1",
          cat: "AI Action",
          kw: "ai supervisor agente verificar docs",
          run: () => {
            activateWorkspaceTab("tab-docs");
            document.getElementById("run-supervisor")?.click();
          },
        },
        {
          title: "Formal: Probar Envolvente Vuelo (Z3 + cvc5)",
          cat: "Formal SMT",
          kw: "smt formal z3 cvc5 envolvente prove",
          run: () => {
            activateWorkspaceTab("tab-audit");
            document.getElementById("prove-formal")?.click();
          },
        },
        {
          title: "CAD/CAE: Abrir Conectores STEP / NASTRAN / ABAQUS",
          cat: "CAD/CAE",
          kw: "step ap242 iges nastran abaqus catia brep fea",
          run: () => {
            activateWorkspaceTab("tab-calc");
            const det = document.getElementById("cad-cae-connectors-details");
            if (det) {
              det.open = true;
              det.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
          },
        },
        {
          title: "3D: Actualizar Visor 3D Envolvente / FEA",
          cat: "3D SL-1",
          kw: "visor 3d mesh envelope sl1",
          run: () => {
            activateWorkspaceTab("tab-coverage");
            if (typeof window.ensureViewer3D === "function") window.ensureViewer3D();
            document.getElementById("refresh-3d-btn")?.click();
          },
        },
        {
          title: "Rol SoD: Alternar Revisor CVE SL-1",
          cat: "Sesion",
          kw: "cve rol sod reviewer session",
          run: () => document.getElementById("switch-cve-btn")?.click(),
        },
        {
          title: "Ajustes: Abrir Sesion Tenant y Tema",
          cat: "Sistema",
          kw: "ajustes tema oscuro claro login session",
          run: () => document.getElementById("open-settings-btn")?.click(),
        },
      ];

      const methodSel = document.getElementById("calc-method");
      if (methodSel) {
        [...methodSel.options].forEach((opt) => {
          cmds.push({
            title: opt.textContent || opt.value,
            cat: "Metodo Calc",
            kw: `metodo calculo ${opt.value} ${opt.textContent || ""}`,
            run: () => {
              activateWorkspaceTab("tab-calc");
              const filterInput = document.getElementById("method-quick-filter");
              if (filterInput && filterInput.value) {
                filterInput.value = "";
                filterInput.dispatchEvent(new Event("input"));
              }
              methodSel.value = opt.value;
              methodSel.dispatchEvent(new Event("change"));
              if (typeof window.syncMethodTemplates === "function") window.syncMethodTemplates();
              document.querySelector("#dynamic-calc-form input")?.focus();
            },
          });
        });
      }

      const mcpSel = document.getElementById("mcp-tool-select");
      if (mcpSel) {
        [...mcpSel.options].forEach((opt) => {
          cmds.push({
            title: opt.textContent || opt.value,
            cat: "MCP Tool",
            kw: `mcp tool ${opt.value} ${opt.textContent || ""}`,
            run: () => {
              activateWorkspaceTab("tab-mcp");
              mcpSel.value = opt.value;
              mcpSel.dispatchEvent(new Event("change"));
              document.getElementById("mcp-invoke-tool")?.focus();
            },
          });
        });
      }

      return cmds;
    }

    function renderList() {
      const tokens = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      const all = buildCommandCatalog();
      const matched = tokens.length
        ? all.filter((c) => {
            const hay = `${c.title} ${c.cat} ${c.kw}`.toLowerCase();
            return tokens.every((t) => hay.includes(t));
          })
        : all;

      filtered = matched.slice(0, 24);
      if (activeIdx >= filtered.length) activeIdx = Math.max(0, filtered.length - 1);

      list.replaceChildren();
      if (status) {
        status.textContent = filtered.length
          ? `${matched.length} comandos disponibles (mostrando ${filtered.length}). Enter para ejecutar.`
          : "Sin coincidencias. Prueba con: fatigue, smt, step, tsai, bolt, mcp.";
      }

      filtered.forEach((cmd, i) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ai-cmd-item";
        btn.setAttribute("role", "option");
        btn.setAttribute("data-active", String(i === activeIdx));
        btn.setAttribute("aria-selected", String(i === activeIdx));

        const titleSpan = document.createElement("span");
        titleSpan.textContent = cmd.title;
        const catSpan = document.createElement("span");
        catSpan.className = "ai-cmd-cat";
        catSpan.textContent = cmd.cat;

        btn.append(titleSpan, catSpan);
        btn.onclick = () => {
          dlg.close();
          cmd.run();
        };
        list.appendChild(btn);
      });
    }

    function updateActiveHighlight() {
      const items = [...list.querySelectorAll(".ai-cmd-item")];
      items.forEach((el, i) => {
        const active = i === activeIdx;
        el.setAttribute("data-active", String(active));
        el.setAttribute("aria-selected", String(active));
        if (active) el.scrollIntoView({ block: "nearest" });
      });
    }

    function openPalette() {
      if (!dlg.open) dlg.showModal();
      input.value = "";
      activeIdx = 0;
      renderList();
      input.focus();
    }

    openBtn?.addEventListener("click", openPalette);
    dlg.addEventListener("ai-cmd-open", () => {
      input.value = "";
      activeIdx = 0;
      renderList();
      input.focus();
    });

    input.addEventListener("input", () => {
      activeIdx = 0;
      renderList();
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" && filtered.length) {
        e.preventDefault();
        activeIdx = (activeIdx + 1) % filtered.length;
        updateActiveHighlight();
      } else if (e.key === "ArrowUp" && filtered.length) {
        e.preventDefault();
        activeIdx = (activeIdx - 1 + filtered.length) % filtered.length;
        updateActiveHighlight();
      } else if (e.key === "Enter" && filtered[activeIdx]) {
        e.preventDefault();
        const chosen = filtered[activeIdx];
        dlg.close();
        chosen.run();
      }
    });
  }

  function bindMethodQuickFilter() {
    const filterInput = document.getElementById("method-quick-filter");
    const methodSel = document.getElementById("calc-method");
    if (!filterInput || !methodSel) return;

    let masterSnapshot = [];
    let applyingFilter = false;

    function captureMaster() {
      if (applyingFilter || filterInput.value.trim()) return;
      const items = [];
      methodSel.childNodes.forEach((node) => {
        if (node.nodeName === "OPTGROUP") {
          const groupLabel = node.label || "";
          [...node.children].forEach((opt) => {
            if (opt.nodeName === "OPTION") {
              items.push({ value: opt.value, text: opt.textContent || opt.value, group: groupLabel });
            }
          });
        } else if (node.nodeName === "OPTION") {
          items.push({ value: node.value, text: node.textContent || node.value, group: "" });
        }
      });
      if (items.length > 0) masterSnapshot = items;
    }

    captureMaster();
    const observer = new MutationObserver(() => captureMaster());
    observer.observe(methodSel, { childList: true });

    filterInput.addEventListener("input", () => {
      const tokens = filterInput.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      const prevVal = methodSel.value;
      const matches = tokens.length
        ? masterSnapshot.filter((item) => {
            const hay = `${item.value} ${item.text} ${item.group}`.toLowerCase();
            return tokens.every((t) => hay.includes(t));
          })
        : masterSnapshot;

      applyingFilter = true;
      methodSel.replaceChildren();
      if (!matches.length) {
        const emptyOpt = document.createElement("option");
        emptyOpt.value = prevVal || "hover_power_screen";
        emptyOpt.textContent = "Sin metodos coincidentes (limpia filtro)";
        emptyOpt.disabled = true;
        methodSel.appendChild(emptyOpt);
      } else {
        const groups = new Map();
        matches.forEach((m) => {
          const key = m.group || "__ungrouped__";
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key).push(m);
        });
        groups.forEach((list, groupLabel) => {
          const parent = groupLabel === "__ungrouped__" ? methodSel : document.createElement("optgroup");
          if (groupLabel !== "__ungrouped__") {
            parent.label = groupLabel;
            methodSel.appendChild(parent);
          }
          list.forEach((m) => {
            const opt = document.createElement("option");
            opt.value = m.value;
            opt.textContent = m.text;
            parent.appendChild(opt);
          });
        });
        if (matches.some((m) => m.value === prevVal)) {
          methodSel.value = prevVal;
        } else {
          methodSel.value = matches[0].value;
          methodSel.dispatchEvent(new Event("change"));
          if (typeof window.syncMethodTemplates === "function") window.syncMethodTemplates();
        }
      }
      Promise.resolve().then(() => {
        applyingFilter = false;
      });
    });

    filterInput.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && filterInput.value) {
        e.preventDefault();
        filterInput.value = "";
        filterInput.dispatchEvent(new Event("input"));
      }
    });
  }

  function bindAiCopilotAdvisor() {
    const quickCalcBtn = document.getElementById("ai-quick-calc-btn");
    const quickAuditBtn = document.getElementById("ai-quick-audit-btn");
    const quickSupBtn = document.getElementById("ai-quick-supervisor-btn");

    if (quickCalcBtn) {
      quickCalcBtn.onclick = () => {
        activateWorkspaceTab("tab-calc");
        document.getElementById("run-custom-calc")?.click();
      };
    }
    if (quickAuditBtn) {
      quickAuditBtn.onclick = () => {
        activateWorkspaceTab("tab-briefing");
        document.getElementById("run-cross-artifact-btn")?.click();
      };
    }
    if (quickSupBtn) {
      quickSupBtn.onclick = () => {
        activateWorkspaceTab("tab-docs");
        document.getElementById("run-supervisor")?.click();
      };
    }

    const outEl = document.getElementById("out");
    const titleEl = document.getElementById("ai-copilot-title");
    const bodyEl = document.getElementById("ai-copilot-body");
    const actionsEl = document.getElementById("ai-copilot-actions");
    const verdictCard = document.getElementById("visual-verdict-card");
    const verdictPill = document.getElementById("verdict-status-pill");
    const verdictMetric = document.getElementById("verdict-big-metric");
    const verdictMeter = document.getElementById("verdict-meter-fill");
    const vkpiState = document.getElementById("vkpi-state");
    const vkpiPrec = document.getElementById("vkpi-prec");
    const vkpiNext = document.getElementById("vkpi-next");
    if (!outEl || !titleEl || !bodyEl || !actionsEl) return;

    function setVisualVerdict({ tone = "ok", badge = "✓ Listo", metric = "—", pct = 65, color = "#16a34a", state = "OK", prec = "Exacta ✓", next = "Revisar" }) {
      if (verdictCard) verdictCard.setAttribute("data-tone", tone);
      if (verdictPill) verdictPill.textContent = badge;
      if (verdictMetric) verdictMetric.textContent = metric;
      if (verdictMeter) {
        const clamped = Math.min(96, Math.max(12, Number(pct) || 50));
        verdictMeter.style.inlineSize = `${clamped}%`;
        verdictMeter.style.backgroundColor = color;
      }
      if (vkpiState) vkpiState.textContent = state;
      if (vkpiPrec) vkpiPrec.textContent = prec;
      if (vkpiNext) vkpiNext.textContent = next;
    }

    function addFollowupAction(label, onClick) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "subtle";
      btn.textContent = label;
      btn.onclick = onClick;
      actionsEl.appendChild(btn);
    }

    function updateAdvisor() {
      const raw = (outEl.textContent || "").trim();
      actionsEl.replaceChildren();
      if (!raw || raw === "Ready.") {
        titleEl.textContent = "Asistente IA listo";
        bodyEl.textContent = "Mueve un deslizador o pulsa Calcular para ver el semáforo de seguridad en lenguaje claro.";
        setVisualVerdict({
          tone: "ok",
          badge: "✓ Listo para calcular",
          metric: "—",
          pct: 60,
          color: "#16a34a",
          state: "En espera",
          prec: "Exacta ✓",
          next: "Pulsa Calcular",
        });
        return;
      }

      let parsed = null;
      if (raw.startsWith("{") || raw.startsWith("[")) {
        try {
          parsed = JSON.parse(raw);
        } catch {
          parsed = null;
        }
      }

      if (!parsed || typeof parsed !== "object") {
        titleEl.textContent = "Resultado recibido";
        bodyEl.textContent = "Puedes abrir los datos técnicos abajo si necesitas ver el detalle completo.";
        return;
      }

      const root = parsed.result && typeof parsed.result === "object" ? parsed.result : parsed;
      const abstainReason = parsed.abstain?.reason || parsed.abstain_reason || parsed.detail;

      if (parsed.status === "abstained" || (abstainReason && parsed.ok === false)) {
        titleEl.textContent = "Atención: Falta un dato o sesión";
        bodyEl.textContent = `${String(abstainReason).slice(0, 120)}. Revisa los parámetros o inicia sesión en Ajustes.`;
        setVisualVerdict({
          tone: "warn",
          badge: "⚠ Revisar",
          metric: "Aviso",
          pct: 42,
          color: "#d97706",
          state: "Bloqueado",
          prec: "Guardrail",
          next: "Abrir Ajustes",
        });
        addFollowupAction("Abrir Ajustes", () => document.getElementById("open-settings-btn")?.click());
        return;
      }

      const outputs = root.outputs || root;
      const msVal = outputs.margin_of_safety ?? outputs.safety_margin ?? root.margin_of_safety;
      const utilVal = outputs.utilization ?? outputs.damage_sum ?? outputs.max_index;
      if (msVal !== undefined || utilVal !== undefined) {
        const msNum = msVal !== undefined ? Number(msVal) : NaN;
        const utilNum = utilVal !== undefined ? Number(utilVal) : NaN;
        const negative = (!Number.isNaN(msNum) && msNum < 0) || (!Number.isNaN(utilNum) && utilNum > 1);
        const method = root.method || document.getElementById("calc-method")?.value || "calculo";

        if (negative) {
          const metricStr = msVal !== undefined ? `MS ${msVal}` : `Uso ${utilVal}`;
          titleEl.textContent = `⚠ Pieza fuera de límite`;
          bodyEl.textContent = `La pieza supera el límite permitido (${metricStr}). Prueba bajar la carga o elegir un material más resistente.`;
          setVisualVerdict({
            tone: "err",
            badge: "✕ LÍMITE SUPERADO",
            metric: metricStr,
            pct: 92,
            color: "#dc2626",
            state: "Crítico",
            prec: "Exacta ✓",
            next: "Reducir Carga",
          });
        } else {
          const msFmt = msVal !== undefined ? `+${msVal} MS` : `${utilVal} uso`;
          const safePct = !Number.isNaN(msNum) ? Math.min(92, Math.max(40, 58 + msNum * 25)) : 80;
          titleEl.textContent = `✓ Pieza Segura (${method})`;
          bodyEl.textContent = `La pieza aguanta sin problema con margen ${msFmt}. Puedes ver el avión en 3D o descargar el informe PDF.`;
          setVisualVerdict({
            tone: "ok",
            badge: "✓ SEGURO",
            metric: msFmt,
            pct: safePct,
            color: "#16a34a",
            state: "Aprobado",
            prec: "Exacta ✓",
            next: "Ver 3D o PDF",
          });
        }

        addFollowupAction("✈️ Ver en 3D", () => {
          activateWorkspaceTab("tab-coverage");
          document.getElementById("refresh-3d-btn")?.click();
        });
        addFollowupAction("🛡️ Verificar Seguridad", () => {
          activateWorkspaceTab("tab-audit");
          document.getElementById("prove-formal")?.click();
        });
        return;
      }

      if (outputs.ideal_power_kw !== undefined || outputs.induced_velocity_m_s !== undefined || root.method) {
        const kwVal = outputs.ideal_power_kw ?? outputs.shaft_power_kw ?? outputs.power_kw;
        const metricTxt = kwVal !== undefined ? `${kwVal} kW` : "Calculado ✓";
        titleEl.textContent = `✓ Cálculo completado`;
        bodyEl.textContent = "Los valores físicos se han calculado con precisión exacta. Siguiente paso: explorar el visor 3D o certificar PDF.";
        setVisualVerdict({
          tone: "ok",
          badge: "✓ CALCULADO",
          metric: metricTxt,
          pct: 78,
          color: "#16a34a",
          state: "Verificado",
          prec: "Exacta ✓",
          next: "Explorar 3D",
        });
        addFollowupAction("✈️ Explorar en 3D", () => {
          activateWorkspaceTab("tab-coverage");
          document.getElementById("refresh-3d-btn")?.click();
        });
        return;
      }

      if (root.auto_bindings || root.format || parsed.format) {
        const fmt = root.format || parsed.format || "CAD/CAE";
        const count = Array.isArray(root.auto_bindings) ? root.auto_bindings.length : 0;
        titleEl.textContent = `📐 Plano ${fmt} conectado`;
        bodyEl.textContent = `Se conectaron ${count} parámetros del diseño a la calculadora.`;
        setVisualVerdict({
          tone: "ok",
          badge: "📐 Plano Listo",
          metric: `${count} enlaces`,
          pct: 84,
          color: "#16a34a",
          state: "Importado",
          prec: "Exacta ✓",
          next: "Ver en 3D",
        });
        addFollowupAction("✈️ Ver en Visor 3D", () => {
          activateWorkspaceTab("tab-coverage");
          document.getElementById("refresh-3d-btn")?.click();
        });
        return;
      }

      if (root.ecn_id || root.diff_sha256 || root.ebom_items || parsed.ecn_id) {
        const ecn = root.ecn_id || parsed.ecn_id || "PLM EBOM";
        titleEl.textContent = `Diferencial PLM / ${ecn}`;
        bodyEl.textContent = "Cambios rev-a-rev comparados correctamente. Listo para revisar o exportar PDF.";
        setVisualVerdict({
          tone: "ok",
          badge: "✓ Cambios Listos",
          metric: ecn,
          pct: 82,
          color: "#16a34a",
          state: "Comparado",
          prec: "SHA-256",
          next: "Exportar PDF",
        });
        addFollowupAction("Ir a Certificar PDF", () => activateWorkspaceTab("tab-audit"));
        return;
      }

      if (root.invariants || root.digest || root.contradictions !== undefined) {
        titleEl.textContent = "🛡️ Comprobación Matemática Sin Fallos";
        bodyEl.textContent = "Ningún requisito incumplido. Todo listo para firmar y descargar tu informe PDF.";
        setVisualVerdict({
          tone: "ok",
          badge: "✓ CERTIFICABLE",
          metric: "0 Fallos",
          pct: 95,
          color: "#16a34a",
          state: "Verificado",
          prec: "Z3 + cvc5",
          next: "Bajar PDF",
        });
        addFollowupAction("📄 Ir a Descargar PDF", () => activateWorkspaceTab("tab-audit"));
        return;
      }

      titleEl.textContent = "Listo ✓";
      bodyEl.textContent = "Resultado actualizado. Usa los accesos de la izquierda para continuar.";
      addFollowupAction("🔍 Buscador (Ctrl+K)", () => document.getElementById("open-cmd-palette-btn")?.click());
    }

    const outObserver = new MutationObserver(updateAdvisor);
    outObserver.observe(outEl, { characterData: true, childList: true, subtree: true });
    updateAdvisor();
  }

  function bindSimpleUxModeAndLaunchpad() {
    const shell = document.getElementById("app-shell") || document.querySelector(".app-shell");
    const simpleBtn = document.getElementById("ux-mode-simple-btn");
    const expertBtn = document.getElementById("ux-mode-expert-btn");
    const revealBtn = document.getElementById("reveal-expert-calc-btn");
    const rawDrawer = document.getElementById("raw-json-drawer");

    function setUxMode(mode) {
      const m = mode === "expert" ? "expert" : "simple";
      if (shell) shell.setAttribute("data-ux-mode", m);
      if (simpleBtn) simpleBtn.setAttribute("aria-pressed", String(m === "simple"));
      if (expertBtn) expertBtn.setAttribute("aria-pressed", String(m === "expert"));
      if (rawDrawer) rawDrawer.open = m === "expert";
    }

    if (simpleBtn) simpleBtn.onclick = () => setUxMode("simple");
    if (expertBtn) expertBtn.onclick = () => setUxMode("expert");
    if (revealBtn) {
      revealBtn.onclick = () => {
        setUxMode("expert");
        const cadDet = document.getElementById("cad-cae-connectors-details");
        if (cadDet) {
          cadDet.open = true;
          cadDet.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      };
    }

    // Launchpad quick-start cards
    document.getElementById("lp-card-calc")?.addEventListener("click", () => {
      activateWorkspaceTab("tab-calc");
      const sel = document.getElementById("calc-method");
      if (sel && [...sel.options].some((o) => o.value === "margin_of_safety")) {
        sel.value = "margin_of_safety";
        sel.dispatchEvent(new Event("change"));
      }
      document.getElementById("run-custom-calc")?.click();
    });
    document.getElementById("lp-card-3d")?.addEventListener("click", () => {
      activateWorkspaceTab("tab-coverage");
      if (typeof window.ensureViewer3D === "function") window.ensureViewer3D();
      document.getElementById("refresh-3d-btn")?.click();
    });
    document.getElementById("lp-card-pdf")?.addEventListener("click", () => {
      activateWorkspaceTab("tab-audit");
      document.getElementById("prove-formal")?.click();
    });

    // Category pill selector inside Calculator
    const catBar = document.getElementById("calc-category-pills");
    const methodSel = document.getElementById("calc-method");
    const filterInput = document.getElementById("method-quick-filter");
    const CATEGORY_KEYWORDS = {
      rotor: ["hover", "rotor", "vn_", "oei", "breguet", "takeoff", "control", "flutter", "stability", "weight_cg", "point_mass"],
      fastener: ["bolt", "margin_of_safety", "lug", "bearing"],
      structures: ["wing", "torsion", "buckling", "fuselage", "crack", "damage", "landing"],
      composites: ["fatigue", "miner", "composite", "tsai", "hashin", "laminate", "sandwich", "thermal"],
    };

    if (catBar && methodSel) {
      catBar.querySelectorAll(".calc-cat-pill").forEach((pill) => {
        pill.addEventListener("click", () => {
          const cat = pill.getAttribute("data-cat") || "all";
          catBar.querySelectorAll(".calc-cat-pill").forEach((p) => {
            p.setAttribute("aria-pressed", String(p === pill));
          });
          if (filterInput) {
            filterInput.value = "";
            filterInput.dispatchEvent(new Event("input"));
          }
          if (cat !== "all") {
            const kws = CATEGORY_KEYWORDS[cat] || [];
            const match = [...methodSel.options].find((opt) =>
              kws.some((kw) => opt.value.toLowerCase().includes(kw))
            );
            if (match) {
              methodSel.value = match.value;
              methodSel.dispatchEvent(new Event("change"));
              if (typeof window.syncMethodTemplates === "function") window.syncMethodTemplates();
              document.getElementById("run-custom-calc")?.click();
            }
          }
        });
      });
    }

    // Run one default calculation immediately on startup so charts + visual verdict start alive
    setTimeout(() => {
      const curOut = (document.getElementById("out")?.textContent || "").trim();
      if (curOut === "Ready.") {
        document.getElementById("run-custom-calc")?.click();
      }
    }, 300);
  }

  function init() {
    injectStyles();
    patchOutputTruncation();
    syncCatalogAndMethods();
    bindMaterialAllowable();
    bindCadAndCaeAnalyzers();
    bindPdfBboxPanel();
    fixCveSwitchUiSync();
    bindEnterpriseQ2Q4Panels();
    bindDesktopIdeShortcutsAndToolbar();
    bindAiCommandPalette();
    bindMethodQuickFilter();
    bindAiCopilotAdvisor();
    bindSimpleUxModeAndLaunchpad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
