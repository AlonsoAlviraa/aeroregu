/* AeroRegu Interactive WebGL / Three.js 3D Viewer for V-n Envelope and [X_cg, Y_cg, Z_cg] Cloud.
 * Air-gapped offline bundle: uses window.THREE when provided locally, otherwise uses native WebGL1
 * shaders + crisp 2D HUD overlay with automatic 3D-projected Canvas2D fallback.
 */
(function (global) {
  "use strict";

  const STATUS_COLORS = {
    calc: [0.22, 0.83, 0.62, 0.95],
    gap: [1.0, 0.74, 0.29, 0.92],
    cad_reference: [0.21, 0.82, 1.0, 1.0],
    justified_not_critical: [0.65, 0.55, 0.98, 0.95],
    not_in_envelope: [0.55, 0.62, 0.72, 0.78],
    out_of_limits: [1.0, 0.42, 0.42, 1.0],
    fem_node: [0.46, 0.68, 0.95, 0.55],
    fem_load: [1.0, 0.48, 0.32, 0.95],
  };

  function rgbaCss(arr, alphaOverride) {
    const r = Math.round(arr[0] * 255);
    const g = Math.round(arr[1] * 255);
    const b = Math.round(arr[2] * 255);
    const a = alphaOverride !== undefined ? alphaOverride : arr[3];
    return "rgba(" + r + "," + g + "," + b + "," + a.toFixed(2) + ")";
  }

  function num(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback || 0;
  }

  /* Simple 4x4 column-major matrix math for offline WebGL & HUD projection */
  function mat4Identity() {
    return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  }

  function mat4Mul(a, b) {
    const out = new Float32Array(16);
    for (let c = 0; c < 4; c++) {
      for (let r = 0; r < 4; r++) {
        out[c * 4 + r] =
          a[0 * 4 + r] * b[c * 4 + 0] +
          a[1 * 4 + r] * b[c * 4 + 1] +
          a[2 * 4 + r] * b[c * 4 + 2] +
          a[3 * 4 + r] * b[c * 4 + 3];
      }
    }
    return out;
  }

  function mat4Perspective(fovyRad, aspect, near, far) {
    const f = 1.0 / Math.tan(fovyRad / 2);
    const nf = 1 / (near - far);
    const out = new Float32Array(16);
    out[0] = f / Math.max(aspect, 0.1);
    out[5] = f;
    out[10] = (far + near) * nf;
    out[11] = -1;
    out[14] = 2 * far * near * nf;
    return out;
  }

  function mat4Translate(tx, ty, tz) {
    const m = mat4Identity();
    m[12] = tx;
    m[13] = ty;
    m[14] = tz;
    return m;
  }

  function mat4RotateX(rad) {
    const c = Math.cos(rad);
    const s = Math.sin(rad);
    const m = mat4Identity();
    m[5] = c;
    m[6] = s;
    m[9] = -s;
    m[10] = c;
    return m;
  }

  function mat4RotateY(rad) {
    const c = Math.cos(rad);
    const s = Math.sin(rad);
    const m = mat4Identity();
    m[0] = c;
    m[2] = -s;
    m[8] = s;
    m[10] = c;
    return m;
  }

  function projectPoint(mvp, x, y, z, vpX, vpY, vpW, vpH) {
    const cx = mvp[0] * x + mvp[4] * y + mvp[8] * z + mvp[12];
    const cy = mvp[1] * x + mvp[5] * y + mvp[9] * z + mvp[13];
    const cz = mvp[2] * x + mvp[6] * y + mvp[10] * z + mvp[14];
    const cw = mvp[3] * x + mvp[7] * y + mvp[11] * z + mvp[15];
    if (cw <= 0.0001) return null;
    const ndcX = cx / cw;
    const ndcY = cy / cw;
    const ndcZ = cz / cw;
    return {
      sx: vpX + (ndcX * 0.5 + 0.5) * vpW,
      sy: vpY + (0.5 - ndcY * 0.5) * vpH,
      depth: ndcZ,
    };
  }

  function normVal(val, minV, maxV) {
    const span = maxV - minV;
    if (Math.abs(span) < 1e-9) return 0;
    return ((val - minV) / span) * 2.0 - 1.0;
  }

  function createShader(gl, type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      gl.deleteShader(sh);
      return null;
    }
    return sh;
  }

  function createProgram(gl, vsSrc, fsSrc) {
    const vs = createShader(gl, gl.VERTEX_SHADER, vsSrc);
    const fs = createShader(gl, gl.FRAGMENT_SHADER, fsSrc);
    if (!vs || !fs) return null;
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      gl.deleteProgram(prog);
      return null;
    }
    return prog;
  }

  class AeroRegu3DViewer {
    constructor(container, options) {
      this.container = typeof container === "string" ? document.getElementById(container) : container;
      this.options = options || {};
      this.data = null;
      this.mode = "combined"; // 'combined' | 'vn' | 'cg'
      this.layers = {
        surface: true,
        gust: true,
        cgBox: true,
        cadPoints: true,
        femMesh: true,
        labels: true,
      };
      this.camera = {
        yaw: 0.62,
        pitch: 0.38,
        distance: 4.1,
        panX: 0,
        panY: 0,
      };
      this.hovered = null;
      this.selected = null;
      this._pickTargets = [];
      this._onSelect = typeof this.options.onSelect === "function" ? this.options.onSelect : null;

      this._initCanvases();
      this._initWebGL();
      this._bindEvents();
      this.resize();
    }

    _initCanvases() {
      this.container.innerHTML = "";
      this.container.style.position = "relative";
      this.container.style.overflow = "hidden";
      this.container.style.userSelect = "none";

      this.glCanvas = document.createElement("canvas");
      this.glCanvas.id = "vn-cg-3d-canvas";
      this.glCanvas.style.width = "100%";
      this.glCanvas.style.height = "100%";
      this.glCanvas.style.display = "block";
      this.glCanvas.style.cursor = "grab";

      this.hudCanvas = document.createElement("canvas");
      this.hudCanvas.style.position = "absolute";
      this.hudCanvas.style.left = "0";
      this.hudCanvas.style.top = "0";
      this.hudCanvas.style.width = "100%";
      this.hudCanvas.style.height = "100%";
      this.hudCanvas.style.pointerEvents = "none";

      this.container.appendChild(this.glCanvas);
      this.container.appendChild(this.hudCanvas);
      this.hudCtx = this.hudCanvas.getContext("2d");
    }

    _initWebGL() {
      let gl = null;
      try {
        gl =
          this.glCanvas.getContext("webgl", { antialias: true, alpha: true }) ||
          this.glCanvas.getContext("experimental-webgl", { antialias: true, alpha: true });
      } catch (_err) {
        gl = null;
      }
      this.gl = gl;
      if (!gl) {
        this._hasWebGL = false;
        return;
      }

      const vsSrc = [
        "attribute vec3 aPos;",
        "attribute vec4 aCol;",
        "attribute float aSize;",
        "uniform mat4 uMvp;",
        "varying vec4 vCol;",
        "void main(void) {",
        "  gl_Position = uMvp * vec4(aPos, 1.0);",
        "  gl_PointSize = aSize;",
        "  vCol = aCol;",
        "}",
      ].join("\n");

      const fsMeshSrc = [
        "precision mediump float;",
        "varying vec4 vCol;",
        "void main(void) {",
        "  gl_FragColor = vCol;",
        "}",
      ].join("\n");

      const fsPointSrc = [
        "precision mediump float;",
        "varying vec4 vCol;",
        "void main(void) {",
        "  vec2 c = gl_PointCoord - vec2(0.5, 0.5);",
        "  float d = dot(c, c);",
        "  if (d > 0.25) discard;",
        "  float rim = 1.0 - smoothstep(0.14, 0.25, d);",
        "  float spec = pow(max(0.0, 1.0 - length(c + vec2(0.15, 0.15)) * 2.1), 2.0);",
        "  vec3 rgb = vCol.rgb * (0.78 + 0.28 * (1.0 - d * 3.0)) + vec3(spec * 0.35);",
        "  gl_FragColor = vec4(rgb, vCol.a * rim);",
        "}",
      ].join("\n");

      this.progMesh = createProgram(gl, vsSrc, fsMeshSrc);
      this.progPoint = createProgram(gl, vsSrc, fsPointSrc);
      this._hasWebGL = Boolean(this.progMesh && this.progPoint);
      if (this._hasWebGL) {
        this.vboPos = gl.createBuffer();
        this.vboCol = gl.createBuffer();
        this.vboSize = gl.createBuffer();
        this.ibo = gl.createBuffer();
      }
    }

    _bindEvents() {
      let dragging = false;
      let panning = false;
      let lastX = 0;
      let lastY = 0;
      let moved = false;

      this.glCanvas.addEventListener("mousedown", (e) => {
        dragging = true;
        panning = e.shiftKey || e.button === 2;
        lastX = e.clientX;
        lastY = e.clientY;
        moved = false;
        this.glCanvas.style.cursor = "grabbing";
      });
      this.glCanvas.addEventListener("contextmenu", (e) => e.preventDefault());

      window.addEventListener("mousemove", (e) => {
        const rect = this.glCanvas.getBoundingClientRect();
        if (dragging) {
          const dx = e.clientX - lastX;
          const dy = e.clientY - lastY;
          if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
          lastX = e.clientX;
          lastY = e.clientY;
          if (panning) {
            this.camera.panX += dx * 0.004;
            this.camera.panY -= dy * 0.004;
          } else {
            this.camera.yaw += dx * 0.008;
            this.camera.pitch = Math.max(-1.45, Math.min(1.45, this.camera.pitch + dy * 0.008));
          }
          this.render();
          return;
        }
        if (
          e.clientX >= rect.left &&
          e.clientX <= rect.right &&
          e.clientY >= rect.top &&
          e.clientY <= rect.bottom
        ) {
          this._pickAt(e.clientX - rect.left, e.clientY - rect.top, false);
        }
      });

      window.addEventListener("mouseup", (e) => {
        if (!dragging) return;
        dragging = false;
        this.glCanvas.style.cursor = "grab";
        if (!moved) {
          const rect = this.glCanvas.getBoundingClientRect();
          this._pickAt(e.clientX - rect.left, e.clientY - rect.top, true);
        }
      });

      this.glCanvas.addEventListener(
        "wheel",
        (e) => {
          e.preventDefault();
          const factor = e.deltaY > 0 ? 1.1 : 0.91;
          this.camera.distance = Math.max(1.8, Math.min(10.0, this.camera.distance * factor));
          this.render();
        },
        { passive: false }
      );
    }

    resize() {
      const w = Math.max(300, this.container.clientWidth || 720);
      const h = Math.max(260, this.container.clientHeight || 420);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.cssWidth = w;
      this.cssHeight = h;
      this.dpr = dpr;
      this.glCanvas.width = Math.round(w * dpr);
      this.glCanvas.height = Math.round(h * dpr);
      this.hudCanvas.width = Math.round(w * dpr);
      this.hudCanvas.height = Math.round(h * dpr);
      this.render();
    }

    setMode(mode) {
      if (mode === "combined" || mode === "vn" || mode === "cg") {
        this.mode = mode;
        this.render();
      }
    }

    setLayer(name, visible) {
      if (name in this.layers) {
        this.layers[name] = Boolean(visible);
        this.render();
      }
    }

    setPreset(preset) {
      if (preset === "iso") {
        this.camera.yaw = 0.62;
        this.camera.pitch = 0.38;
      } else if (preset === "front") {
        this.camera.yaw = 0.0;
        this.camera.pitch = 0.0;
      } else if (preset === "top") {
        this.camera.yaw = 0.0;
        this.camera.pitch = 1.42;
      } else if (preset === "side") {
        this.camera.yaw = Math.PI / 2;
        this.camera.pitch = 0.05;
      }
      this.camera.panX = 0;
      this.camera.panY = 0;
      this.camera.distance = 4.1;
      this.render();
    }

    setData(payload) {
      this.data = payload;
      this.hovered = null;
      this.selected = null;
      this.render();
    }

    _buildMvp(vpW, vpH) {
      const proj = mat4Perspective((42 * Math.PI) / 180, vpW / Math.max(1, vpH), 0.1, 40.0);
      const trans = mat4Translate(this.camera.panX, this.camera.panY, -this.camera.distance);
      const rx = mat4RotateX(this.camera.pitch);
      const ry = mat4RotateY(this.camera.yaw);
      return mat4Mul(proj, mat4Mul(trans, mat4Mul(rx, ry)));
    }

    _vnBounds() {
      const env = this.data && this.data.vn_envelope ? this.data.vn_envelope : null;
      const slices = env && Array.isArray(env.mass_slices) ? env.mass_slices : [];
      let vMax = 90;
      let nzMin = -2.0;
      let nzMax = 3.5;
      let mMin = 750;
      let mMax = 1250;
      if (slices.length > 0) {
        const masses = slices.map((s) => num(s.mass_kg, 900));
        mMin = Math.min.apply(null, masses) - 40;
        mMax = Math.max.apply(null, masses) + 40;
        if (Math.abs(mMax - mMin) < 10) {
          mMin -= 100;
          mMax += 100;
        }
        slices.forEach((s) => {
          const all = (s.maneuver_upper || [])
            .concat(s.maneuver_lower || [])
            .concat(s.gust_upper || [])
            .concat(s.gust_lower || []);
          all.forEach((p) => {
            vMax = Math.max(vMax, num(p.v_mps, 82) + 8);
            nzMin = Math.min(nzMin, num(p.nz, -1) - 0.4);
            nzMax = Math.max(nzMax, num(p.nz, 2.5) + 0.4);
          });
        });
      }
      return { vMin: 0, vMax, nzMin, nzMax, mMin, mMax };
    }

    _cgBounds() {
      const cloud = this.data && this.data.cg_cloud ? this.data.cg_cloud : null;
      const lim = (cloud && cloud.limits_box_m) || {
        x_min_m: -0.25,
        x_max_m: 0.25,
        y_min_m: -0.25,
        y_max_m: 0.25,
        z_min_m: 0.0,
        z_max_m: 0.35,
      };
      let xMin = num(lim.x_min_m, -0.25);
      let xMax = num(lim.x_max_m, 0.25);
      let yMin = num(lim.y_min_m, -0.22);
      let yMax = num(lim.y_max_m, 0.22);
      let zMin = num(lim.z_min_m, 0.0);
      let zMax = num(lim.z_max_m, 0.35);

      const pts = (cloud && cloud.points) || [];
      pts.forEach((p) => {
        xMin = Math.min(xMin, num(p.x_cg_m, 0));
        xMax = Math.max(xMax, num(p.x_cg_m, 0));
        yMin = Math.min(yMin, num(p.y_cg_m, 0));
        yMax = Math.max(yMax, num(p.y_cg_m, 0));
        zMin = Math.min(zMin, num(p.z_cg_m, 0));
        zMax = Math.max(zMax, num(p.z_cg_m, 0));
      });
      const padX = Math.max(0.05, (xMax - xMin) * 0.2);
      const padY = Math.max(0.05, (yMax - yMin) * 0.2);
      const padZ = Math.max(0.05, (zMax - zMin) * 0.2);
      return {
        xMin: xMin - padX,
        xMax: xMax + padX,
        yMin: yMin - padY,
        yMax: yMax + padY,
        zMin: zMin - padZ,
        zMax: zMax + padZ,
      };
    }

    _prepareVnPrimitives() {
      const tris = [];
      const lines = [];
      const pts = [];
      const labels = [];
      const b = this._vnBounds();

      const mapVn = (v, nz, m) => [
        normVal(v, b.vMin, b.vMax),
        normVal(nz, b.nzMin, b.nzMax),
        normVal(m, b.mMin, b.mMax),
      ];

      // 3D bounding grid & axes
      const axisPairs = [
        [[-1, -1, -1], [1, -1, -1], [0.95, 0.45, 0.45, 0.85]],
        [[-1, -1, -1], [-1, 1, -1], [0.45, 0.95, 0.65, 0.85]],
        [[-1, -1, -1], [-1, -1, 1], [0.45, 0.72, 1.0, 0.85]],
      ];
      axisPairs.forEach((ap) => lines.push({ p0: ap[0], p1: ap[1], col: ap[2] }));

      // Base grid on bottom plane (nz = nzMin) and nz=0 reference plane
      for (let i = -4; i <= 4; i++) {
        const t = i / 4;
        lines.push({ p0: [t, -1, -1], p1: [t, -1, 1], col: [0.3, 0.4, 0.55, 0.24] });
        lines.push({ p0: [-1, -1, t], p1: [1, -1, t], col: [0.3, 0.4, 0.55, 0.24] });
      }
      const nzZero = normVal(0, b.nzMin, b.nzMax);
      lines.push({ p0: [-1, nzZero, -1], p1: [1, nzZero, -1], col: [0.55, 0.68, 0.85, 0.35] });
      lines.push({ p0: [-1, nzZero, 1], p1: [1, nzZero, 1], col: [0.55, 0.68, 0.85, 0.35] });

      labels.push({ pos: [1.08, -1, -1], text: "V [0.." + Math.round(b.vMax) + " m/s]", col: "#f78c8c" });
      labels.push({ pos: [-1, 1.08, -1], text: "nz [" + b.nzMin.toFixed(1) + ".." + b.nzMax.toFixed(1) + " g]", col: "#6ee7b7" });
      labels.push({ pos: [-1, -1, 1.08], text: "Mass [" + Math.round(b.mMin) + ".." + Math.round(b.mMax) + " kg]", col: "#7dd3fc" });

      const env = this.data && this.data.vn_envelope;
      if (!env) return { tris, lines, pts, labels };

      const slices = env.mass_slices || [];
      if (this.layers.surface && env.surface_mesh) {
        const verts = env.surface_mesh.vertices || [];
        const triIdx = env.surface_mesh.triangles || [];
        const normVerts = verts.map((v) => mapVn(num(v.v_mps), num(v.nz), num(v.mass_kg)));
        triIdx.forEach((tri) => {
          const p0 = normVerts[tri[0]];
          const p1 = normVerts[tri[1]];
          const p2 = normVerts[tri[2]];
          if (p0 && p1 && p2) {
            tris.push({ p0, p1, p2, col: [0.22, 0.72, 0.96, 0.22] });
          }
        });
      }

      slices.forEach((sl, idx) => {
        const loop = sl.closed_loop || [];
        const sliceCol = idx === 0 ? [0.22, 0.83, 0.62, 0.95] : [0.32, 0.78, 1.0, 0.9];
        for (let i = 0; i < loop.length; i++) {
          const a = loop[i];
          const bPt = loop[(i + 1) % loop.length];
          const p0 = mapVn(num(a.v_mps), num(a.nz), num(a.mass_kg));
          const p1 = mapVn(num(bPt.v_mps), num(bPt.nz), num(bPt.mass_kg));
          lines.push({ p0, p1, col: sliceCol });
        }
        // Speed vertex markers on slice
        (sl.maneuver_upper || []).concat(sl.maneuver_lower || []).forEach((vp, vIdx) => {
          const pos = mapVn(num(vp.v_mps), num(vp.nz), num(vp.mass_kg));
          pts.push({
            pos,
            col: sliceCol,
            size: vIdx === 0 ? 7 : 6,
            meta: {
              kind: "V-n Boundary Vertex",
              point_id: "M=" + sl.mass_kg + "kg @ V=" + vp.v_mps + "m/s",
              v_mps: vp.v_mps,
              nz: vp.nz,
              mass_kg: vp.mass_kg,
              status: "maneuver_envelope",
            },
          });
        });

        if (this.layers.gust) {
          const drawChain = (chain, col) => {
            for (let i = 0; i < chain.length - 1; i++) {
              lines.push({
                p0: mapVn(num(chain[i].v_mps), num(chain[i].nz), num(chain[i].mass_kg)),
                p1: mapVn(num(chain[i + 1].v_mps), num(chain[i + 1].nz), num(chain[i + 1].mass_kg)),
                col,
              });
            }
          };
          drawChain(sl.gust_upper || [], [1.0, 0.74, 0.29, 0.88]);
          drawChain(sl.gust_lower || [], [1.0, 0.56, 0.29, 0.88]);
        }

        if (idx === slices.length - 1 && sl.characteristic_speeds_mps) {
          const sp = sl.characteristic_speeds_mps;
          const massV = num(sl.mass_kg);
          labels.push({
            pos: mapVn(num(sp.v_a), 2.5, massV),
            text: "Va=" + sp.v_a,
            col: "#9be7c4",
          });
          labels.push({
            pos: mapVn(num(sp.v_d), 1.2, massV),
            text: "Vd=" + sp.v_d,
            col: "#7dd3fc",
          });
        }
      });

      return { tris, lines, pts, labels };
    }

    _prepareCgPrimitives() {
      const tris = [];
      const lines = [];
      const pts = [];
      const labels = [];
      const b = this._cgBounds();

      const mapCg = (x, y, z) => [
        normVal(x, b.xMin, b.xMax),
        normVal(z, b.zMin, b.zMax), // vertical Z_cg plotted UP in WebGL Y
        normVal(y, b.yMin, b.yMax),
      ];

      // Axes
      lines.push({ p0: [-1, -1, -1], p1: [1, -1, -1], col: [0.95, 0.45, 0.45, 0.85] });
      lines.push({ p0: [-1, -1, -1], p1: [-1, 1, -1], col: [0.45, 0.95, 0.65, 0.85] });
      lines.push({ p0: [-1, -1, -1], p1: [-1, -1, 1], col: [0.45, 0.72, 1.0, 0.85] });
      for (let i = -4; i <= 4; i++) {
        const t = i / 4;
        lines.push({ p0: [t, -1, -1], p1: [t, -1, 1], col: [0.3, 0.4, 0.55, 0.22] });
        lines.push({ p0: [-1, -1, t], p1: [1, -1, t], col: [0.3, 0.4, 0.55, 0.22] });
      }

      labels.push({ pos: [1.08, -1, -1], text: "X_cg [" + b.xMin.toFixed(2) + ".." + b.xMax.toFixed(2) + "m]", col: "#f78c8c" });
      labels.push({ pos: [-1, 1.08, -1], text: "Z_cg [" + b.zMin.toFixed(2) + ".." + b.zMax.toFixed(2) + "m]", col: "#6ee7b7" });
      labels.push({ pos: [-1, -1, 1.08], text: "Y_cg [" + b.yMin.toFixed(2) + ".." + b.yMax.toFixed(2) + "m]", col: "#7dd3fc" });

      const cloud = this.data && this.data.cg_cloud;
      if (!cloud) return { tris, lines, pts, labels };

      // CG limits wireframe box
      const lim = cloud.limits_box_m;
      if (this.layers.cgBox && lim) {
        const x0 = num(lim.x_min_m, -0.2);
        const x1 = num(lim.x_max_m, 0.2);
        const y0 = num(lim.y_min_m, -0.18);
        const y1 = num(lim.y_max_m, 0.18);
        const z0 = num(lim.z_min_m, 0.05);
        const z1 = num(lim.z_max_m, 0.3);
        const corners = [
          mapCg(x0, y0, z0),
          mapCg(x1, y0, z0),
          mapCg(x1, y1, z0),
          mapCg(x0, y1, z0),
          mapCg(x0, y0, z1),
          mapCg(x1, y0, z1),
          mapCg(x1, y1, z1),
          mapCg(x0, y1, z1),
        ];
        const edges = [
          [0, 1], [1, 2], [2, 3], [3, 0],
          [4, 5], [5, 6], [6, 7], [7, 4],
          [0, 4], [1, 5], [2, 6], [3, 7],
        ];
        const boxCol = [0.22, 0.83, 0.62, 0.72];
        edges.forEach((e) => lines.push({ p0: corners[e[0]], p1: corners[e[1]], col: boxCol }));

        // Translucent top/bottom caps
        tris.push({ p0: corners[0], p1: corners[1], p2: corners[2], col: [0.22, 0.83, 0.62, 0.08] });
        tris.push({ p0: corners[0], p1: corners[2], p2: corners[3], col: [0.22, 0.83, 0.62, 0.08] });
      }

      // CG cloud points
      (cloud.points || []).forEach((pt) => {
        const isCad = pt.source === "cad_cae" || pt.status === "cad_reference";
        if (isCad && !this.layers.cadPoints) return;
        const pos = mapCg(num(pt.x_cg_m), num(pt.y_cg_m), num(pt.z_cg_m));
        let col = STATUS_COLORS[pt.status] || STATUS_COLORS.gap;
        if (!pt.within_cg_limits && !isCad) col = STATUS_COLORS.out_of_limits;
        const size = isCad ? 13 : 8;
        pts.push({ pos, col, size, meta: pt });
        if (isCad) {
          labels.push({
            pos,
            text: pt.label || pt.point_id,
            col: pt.within_cg_limits ? "#35d0ff" : "#ff6b6b",
          });
        }
      });

      // Optional FEM mesh overlay scaled onto CG frame
      const fem = this.data && this.data.fem_overlay;
      if (this.layers.femMesh && fem && Array.isArray(fem.nodes) && fem.nodes.length > 0) {
        const xs = fem.nodes.map((n) => num(n.x));
        const ys = fem.nodes.map((n) => num(n.y));
        const zs = fem.nodes.map((n) => num(n.z));
        const fxMin = Math.min.apply(null, xs);
        const fxMax = Math.max.apply(null, xs);
        const fyMin = Math.min.apply(null, ys);
        const fyMax = Math.max.apply(null, ys);
        const fzMin = Math.min.apply(null, zs);
        const fzMax = Math.max.apply(null, zs);
        const mapFem = (x, y, z) => [
          normVal(x, fxMin - 0.1, fxMax + 0.1) * 0.82,
          normVal(z, fzMin - 0.1, fzMax + 0.1) * 0.82,
          normVal(y, fyMin - 0.1, fyMax + 0.1) * 0.82,
        ];
        const nodeMap = {};
        fem.nodes.forEach((n) => {
          const p = mapFem(num(n.x), num(n.y), num(n.z));
          nodeMap[String(n.id)] = p;
          pts.push({
            pos: p,
            col: STATUS_COLORS.fem_node,
            size: 5,
            meta: {
              kind: "FEM Node",
              point_id: "GRID/NODE #" + n.id,
              x_cg_m: n.x,
              y_cg_m: n.y,
              z_cg_m: n.z,
              status: "fem_node",
              within_cg_limits: true,
            },
          });
        });
        (fem.edges || []).forEach((edge) => {
          const a = nodeMap[String(edge[0])];
          const bNode = nodeMap[String(edge[1])];
          if (a && bNode) {
            lines.push({ p0: a, p1: bNode, col: [0.46, 0.68, 0.95, 0.42] });
          }
        });
        (fem.load_vectors || []).forEach((lv) => {
          const base = nodeMap[String(lv.node_id)];
          if (base) {
            const tip = [
              base[0] + num(lv.dx, 0) * 0.25,
              base[1] + num(lv.dz, 0.25) * 0.25,
              base[2] + num(lv.dy, 0) * 0.25,
            ];
            lines.push({ p0: base, p1: tip, col: STATUS_COLORS.fem_load });
          }
        });
      }

      return { tris, lines, pts, labels };
    }

    _drawWebGLScene(prims, vpX, vpY, vpW, vpH, mvp) {
      const gl = this.gl;
      gl.viewport(vpX, vpY, vpW, vpH);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.enable(gl.DEPTH_TEST);

      const uploadAndDraw = (prog, coords, colors, sizes, drawMode, count) => {
        if (count === 0) return;
        gl.useProgram(prog);
        const uMvp = gl.getUniformLocation(prog, "uMvp");
        gl.uniformMatrix4fv(uMvp, false, mvp);

        const aPos = gl.getAttribLocation(prog, "aPos");
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vboPos);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(coords), gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(aPos);
        gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);

        const aCol = gl.getAttribLocation(prog, "aCol");
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vboCol);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(colors), gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(aCol);
        gl.vertexAttribPointer(aCol, 4, gl.FLOAT, false, 0, 0);

        const aSize = gl.getAttribLocation(prog, "aSize");
        if (aSize >= 0 && sizes) {
          gl.bindBuffer(gl.ARRAY_BUFFER, this.vboSize);
          gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(sizes), gl.DYNAMIC_DRAW);
          gl.enableVertexAttribArray(aSize);
          gl.vertexAttribPointer(aSize, 1, gl.FLOAT, false, 0, 0);
        }
        gl.drawArrays(drawMode, 0, count);
      };

      // Triangles (depth write off so translucent envelope doesn't occlude interior lines/points)
      if (prims.tris.length > 0) {
        const triPos = [];
        const triCol = [];
        prims.tris.forEach((t) => {
          triPos.push(t.p0[0], t.p0[1], t.p0[2], t.p1[0], t.p1[1], t.p1[2], t.p2[0], t.p2[1], t.p2[2]);
          triCol.push.apply(triCol, t.col);
          triCol.push.apply(triCol, t.col);
          triCol.push.apply(triCol, t.col);
        });
        gl.depthMask(false);
        uploadAndDraw(this.progMesh, triPos, triCol, null, gl.TRIANGLES, prims.tris.length * 3);
        gl.depthMask(true);
      }

      // Lines
      if (prims.lines.length > 0) {
        const linePos = [];
        const lineCol = [];
        prims.lines.forEach((l) => {
          linePos.push(l.p0[0], l.p0[1], l.p0[2], l.p1[0], l.p1[1], l.p1[2]);
          lineCol.push.apply(lineCol, l.col);
          lineCol.push.apply(lineCol, l.col);
        });
        uploadAndDraw(this.progMesh, linePos, lineCol, null, gl.LINES, prims.lines.length * 2);
      }

      // Points
      if (prims.pts.length > 0) {
        const ptPos = [];
        const ptCol = [];
        const ptSize = [];
        prims.pts.forEach((pt) => {
          ptPos.push(pt.pos[0], pt.pos[1], pt.pos[2]);
          ptCol.push.apply(ptCol, pt.col);
          ptSize.push((pt.size || 7) * this.dpr);
        });
        uploadAndDraw(this.progPoint, ptPos, ptCol, ptSize, gl.POINTS, prims.pts.length);
      }
    }

    _drawCanvas2DFallback(ctx, prims, vpX, vpY, vpW, vpH, mvp) {
      prims.lines.forEach((l) => {
        const a = projectPoint(mvp, l.p0[0], l.p0[1], l.p0[2], vpX, vpY, vpW, vpH);
        const b = projectPoint(mvp, l.p1[0], l.p1[1], l.p1[2], vpX, vpY, vpW, vpH);
        if (!a || !b) return;
        ctx.strokeStyle = rgbaCss(l.col);
        ctx.lineWidth = 1.25;
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.lineTo(b.sx, b.sy);
        ctx.stroke();
      });
      const sortedPts = prims.pts
        .map((pt) => ({
          pt,
          scr: projectPoint(mvp, pt.pos[0], pt.pos[1], pt.pos[2], vpX, vpY, vpW, vpH),
        }))
        .filter((x) => x.scr !== null)
        .sort((a, b) => b.scr.depth - a.scr.depth);
      sortedPts.forEach((item) => {
        ctx.fillStyle = rgbaCss(item.pt.col);
        ctx.beginPath();
        ctx.arc(item.scr.sx, item.scr.sy, (item.pt.size || 6) * 0.45, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    _drawHudAndRegisterPick(prims, cssVpX, cssVpY, cssVpW, cssVpH, mvp, title) {
      const ctx = this.hudCtx;
      ctx.save();
      ctx.beginPath();
      ctx.rect(cssVpX, cssVpY, cssVpW, cssVpH);
      ctx.clip();

      // Viewport header pill
      ctx.fillStyle = "rgba(10, 17, 30, 0.72)";
      ctx.fillRect(cssVpX + 10, cssVpY + 10, Math.min(260, cssVpW - 20), 24);
      ctx.strokeStyle = "rgba(86, 134, 198, 0.35)";
      ctx.strokeRect(cssVpX + 10, cssVpY + 10, Math.min(260, cssVpW - 20), 24);
      ctx.fillStyle = "#dbeafe";
      ctx.font = "600 11px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.fillText(title, cssVpX + 18, cssVpY + 26);

      if (this.layers.labels) {
        ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
        prims.labels.forEach((lb) => {
          const p = projectPoint(mvp, lb.pos[0], lb.pos[1], lb.pos[2], cssVpX, cssVpY, cssVpW, cssVpH);
          if (!p) return;
          ctx.fillStyle = "rgba(8, 13, 24, 0.78)";
          const w = ctx.measureText(lb.text).width + 8;
          ctx.fillRect(p.sx + 4, p.sy - 11, w, 15);
          ctx.fillStyle = lb.col || "#e2e8f0";
          ctx.fillText(lb.text, p.sx + 8, p.sy);
        });
      }

      prims.pts.forEach((pt) => {
        const scr = projectPoint(mvp, pt.pos[0], pt.pos[1], pt.pos[2], cssVpX, cssVpY, cssVpW, cssVpH);
        if (!scr) return;
        this._pickTargets.push({ sx: scr.sx, sy: scr.sy, meta: pt.meta, size: pt.size || 7 });
        const isSel = this.selected && pt.meta && this.selected.point_id === pt.meta.point_id;
        const isHov = this.hovered && pt.meta && this.hovered.point_id === pt.meta.point_id;
        if (isSel || isHov) {
          ctx.strokeStyle = isSel ? "#35d0ff" : "#ffffff";
          ctx.lineWidth = isSel ? 2.2 : 1.5;
          ctx.beginPath();
          ctx.arc(scr.sx, scr.sy, (pt.size || 7) * 0.75 + 3, 0, Math.PI * 2);
          ctx.stroke();
        }
      });

      ctx.restore();
    }

    _pickAt(cx, cy, select) {
      let best = null;
      let bestDist = 14;
      for (let i = 0; i < this._pickTargets.length; i++) {
        const t = this._pickTargets[i];
        const d = Math.hypot(t.sx - cx, t.sy - cy);
        if (d < bestDist) {
          bestDist = d;
          best = t.meta;
        }
      }
      if (select) {
        this.selected = best;
        if (this._onSelect) this._onSelect(best);
      } else {
        this.hovered = best;
      }
      this.render();
    }

    render() {
      const ctx = this.hudCtx;
      const w = this.cssWidth || 720;
      const h = this.cssHeight || 420;
      const gw = this.glCanvas.width;
      const gh = this.glCanvas.height;

      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      this._pickTargets = [];

      if (this._hasWebGL) {
        const gl = this.gl;
        gl.viewport(0, 0, gw, gh);
        gl.clearColor(0.032, 0.055, 0.098, 1.0);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      } else {
        const gctx = this.glCanvas.getContext("2d");
        if (gctx) {
          gctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
          gctx.fillStyle = "#080e19";
          gctx.fillRect(0, 0, w, h);
        }
      }

      if (!this.data) {
        ctx.fillStyle = "#9fb3c8";
        ctx.font = "13px system-ui, sans-serif";
        ctx.fillText("Cargando envolvente 3D V-n y nube CG...", 24, 38);
        return;
      }

      const drawViewport = (prims, cssX, cssY, cssW, cssH, title) => {
        const mvp = this._buildMvp(cssW, cssH);
        if (this._hasWebGL) {
          this._drawWebGLScene(
            prims,
            Math.round(cssX * this.dpr),
            Math.round((h - cssY - cssH) * this.dpr),
            Math.round(cssW * this.dpr),
            Math.round(cssH * this.dpr),
            mvp
          );
        } else {
          const gctx = this.glCanvas.getContext("2d");
          if (gctx) {
            gctx.save();
            gctx.beginPath();
            gctx.rect(cssX, cssY, cssW, cssH);
            gctx.clip();
            this._drawCanvas2DFallback(gctx, prims, cssX, cssY, cssW, cssH, mvp);
            gctx.restore();
          }
        }
        this._drawHudAndRegisterPick(prims, cssX, cssY, cssW, cssH, mvp, title);
      };

      if (this.mode === "vn") {
        drawViewport(this._prepareVnPrimitives(), 0, 0, w, h, "3D V-n-Mass Envelope [V, nz, kg]");
      } else if (this.mode === "cg") {
        drawViewport(this._prepareCgPrimitives(), 0, 0, w, h, "3D CG Cloud [X_cg, Y_cg, Z_cg]");
      } else {
        const half = Math.floor(w / 2);
        drawViewport(this._prepareVnPrimitives(), 0, 0, half, h, "V-n-Mass Envelope [V, nz, kg]");
        drawViewport(
          this._prepareCgPrimitives(),
          half,
          0,
          w - half,
          h,
          "CG Cloud [X_cg, Y_cg, Z_cg]"
        );
        ctx.strokeStyle = "rgba(86, 134, 198, 0.35)";
        ctx.beginPath();
        ctx.moveTo(half, 0);
        ctx.lineTo(half, h);
        ctx.stroke();
      }

      const active = this.hovered || this.selected;
      if (active) {
        const line1 = active.label || active.point_id || "Point";
        const line2 =
          active.x_cg_m !== undefined
            ? "CG=[" + active.x_cg_m + ", " + active.y_cg_m + ", " + active.z_cg_m + "] m  status=" + active.status
            : "V=" + active.v_mps + " m/s  nz=" + active.nz + "  m=" + active.mass_kg + " kg";
        ctx.fillStyle = "rgba(8, 14, 25, 0.90)";
        ctx.fillRect(12, h - 52, Math.min(w - 24, 460), 40);
        ctx.strokeStyle = "#35d0ff";
        ctx.strokeRect(12, h - 52, Math.min(w - 24, 460), 40);
        ctx.fillStyle = "#e6f4ff";
        ctx.font = "600 11px ui-monospace, monospace";
        ctx.fillText(line1, 20, h - 34);
        ctx.fillStyle = "#9fd4ff";
        ctx.font = "11px ui-monospace, monospace";
        ctx.fillText(line2, 20, h - 18);
      }
    }
  }

  global.AeroRegu3DViewer = AeroRegu3DViewer;
})(window);
