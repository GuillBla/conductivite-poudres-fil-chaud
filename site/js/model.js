// Portage JavaScript de hotwire/model.py et des fonctions d'analyse utiles au site.
// Même maillage, même schéma implicite : les résultats sont comparés à ceux de
// Python par tests/js/model.test.mjs (node --test).

export const DEFAULT_SETUP = {
  wire_radius: 0.25e-3,
  powder_radius: 14.5e-3,
  tube_thickness: 1.5e-3,
  length: 0.041,
  k_powder: 0.2,
  rhocp_powder: 1.2e6,
  k_tube: 0.19,
  rhocp_tube: 1.9e6,
  rhocp_wire: 3.8e6,
  power: 3.77,
  h_ext: 10.0,
  t_ambient: 20.0,
  sensor: "outer",
};

export const qLin = (s) => s.power / s.length;
export const outerRadius = (s) => s.powder_radius + s.tube_thickness;
export const alphaPowder = (s) => s.k_powder / s.rhocp_powder;

// --- Fonction intégrale exponentielle E1 (Abramowitz & Stegun / Numerical Recipes) ---
export function expint1(x) {
  if (x <= 0) return Infinity;
  if (x < 1) {
    // série : -γ - ln x - Σ (-x)^n / (n n!)
    let sum = 0, term = 1;
    for (let n = 1; n < 60; n++) {
      term *= -x / n;
      const add = term / n;
      sum += add;
      if (Math.abs(add) < 1e-16 * Math.abs(sum)) break;
    }
    return -0.5772156649015329 - Math.log(x) - sum;
  }
  // fraction continue de Lentz
  const tiny = 1e-300;
  let b = x + 1, c = 1 / tiny, d = 1 / b, h = d;
  for (let i = 1; i < 200; i++) {
    const a = -i * i;
    b += 2;
    d = 1 / (a * d + b);
    c = b + a / c;
    const del = c * d;
    h *= del;
    if (Math.abs(del - 1) < 1e-15) break;
  }
  return h * Math.exp(-x);
}

export function lineSourceRise(r, t, q, k, alpha) {
  return t > 0 ? (q / (4 * Math.PI * k)) * expint1((r * r) / (4 * alpha * t)) : 0;
}

// --- Maillage -------------------------------------------------------------
function geomspace(a, b, n) {
  const out = new Float64Array(n);
  const la = Math.log(a), lb = Math.log(b);
  for (let i = 0; i < n; i++) out[i] = Math.exp(la + ((lb - la) * i) / (n - 1));
  out[0] = a; out[n - 1] = b;
  return out;
}

export function buildGrid(s, nPowder = 60, nTube = 4) {
  const fP = geomspace(s.wire_radius, s.powder_radius, nPowder + 1);
  const R = outerRadius(s);
  const faces = [0, ...fP];
  for (let i = 1; i <= nTube; i++) faces.push(s.powder_radius + ((R - s.powder_radius) * i) / nTube);
  const n = faces.length - 1;
  const centers = new Float64Array(n), k = new Float64Array(n), cap = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let rhocp;
    if (i === 0) { centers[i] = 0; k[i] = Infinity; rhocp = s.rhocp_wire; }
    else if (i <= nPowder) { centers[i] = Math.sqrt(faces[i] * faces[i + 1]); k[i] = s.k_powder; rhocp = s.rhocp_powder; }
    else { centers[i] = 0.5 * (faces[i] + faces[i + 1]); k[i] = s.k_tube; rhocp = s.rhocp_tube; }
    cap[i] = rhocp * Math.PI * (faces[i + 1] ** 2 - faces[i] ** 2);
  }
  const G = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) {
    const rf = faces[i + 1];
    const rl = i === 0 ? 0 : Math.log(rf / centers[i]) / (2 * Math.PI * k[i]);
    const rr = Math.log(centers[i + 1] / rf) / (2 * Math.PI * k[i + 1]);
    G[i] = 1 / (rl + rr);
  }
  const rWall = Math.log(R / centers[n - 1]) / (2 * Math.PI * k[n - 1]);
  const rConv = s.h_ext > 0 ? 1 / (2 * Math.PI * R * s.h_ext) : Infinity;
  return { faces, centers, k, cap, G, rWall, rConv, gOut: 1 / (rWall + rConv), n };
}

// --- Simulation (Euler implicite, algorithme de Thomas) ---------------------
export function simulate(s, times, { maxDt = 5, heaterOffAt = null, nPowder = 60, nTube = 4, keepProfiles = false } = {}) {
  const g = buildGrid(s, nPowder, nTube);
  const n = g.n;
  const theta = new Float64Array(n);
  const diag = new Float64Array(n);
  for (let i = 0; i < n - 1; i++) { diag[i] += g.G[i]; diag[i + 1] += g.G[i]; }
  diag[n - 1] += g.gOut;
  const cp = new Float64Array(n), dp = new Float64Array(n);
  const q = qLin(s);

  function step(dt, src) {
    // a_i = -G[i-1], b_i = cap/dt + diag, c_i = -G[i]
    let b0 = g.cap[0] / dt + diag[0];
    cp[0] = -g.G[0] / b0;
    dp[0] = ((g.cap[0] / dt) * theta[0] + src) / b0;
    for (let i = 1; i < n; i++) {
      const a = -g.G[i - 1];
      const b = g.cap[i] / dt + diag[i];
      const c = i < n - 1 ? -g.G[i] : 0;
      const m = b - a * cp[i - 1];
      cp[i] = c / m;
      dp[i] = ((g.cap[i] / dt) * theta[i] - a * dp[i - 1]) / m;
    }
    theta[n - 1] = dp[n - 1];
    for (let i = n - 2; i >= 0; i--) theta[i] = dp[i] - cp[i] * theta[i + 1];
  }

  const surfRatio = Number.isFinite(g.rConv) ? g.rConv / (g.rWall + g.rConv) : 1;
  const R = outerRadius(s);
  const sensorR = s.sensor === "outer" || s.sensor === "wire" ? null : Number(s.sensor);
  let rNodes = null, lnR = null;
  if (sensorR !== null) {
    rNodes = [s.wire_radius, ...Array.from(g.centers).slice(1), R];
    lnR = rNodes.map(Math.log);
  }
  const out = { time: Float64Array.from(times), t_sensor: [], t_wire: [], t_surface: [], profiles: keepProfiles ? [] : null, grid: g };
  let tNow = 0;
  for (const tTarget of times) {
    while (tNow < tTarget - 1e-12) {
      let dt = Math.min(maxDt, Math.max(0.05 * tNow, 0.01), tTarget - tNow);
      if (heaterOffAt !== null && tNow < heaterOffAt && heaterOffAt < tNow + dt) dt = heaterOffAt - tNow;
      const heating = heaterOffAt === null || tNow < heaterOffAt;
      step(dt, heating ? q : 0);
      tNow += dt;
    }
    const wire = theta[0], surf = theta[n - 1] * surfRatio;
    let sens;
    if (s.sensor === "wire") sens = wire;
    else if (s.sensor === "outer") sens = surf;
    else {
      const th = [theta[0], ...Array.from(theta).slice(1), surf];
      sens = interp(Math.log(sensorR), lnR, th);
    }
    out.t_wire.push(wire + s.t_ambient);
    out.t_surface.push(surf + s.t_ambient);
    out.t_sensor.push(sens + s.t_ambient);
    if (keepProfiles) out.profiles.push(Float64Array.from(theta, (v) => v + s.t_ambient));
  }
  return out;
}

function interp(x, xs, ys) {
  if (x <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) {
      const f = (x - xs[i - 1]) / (xs[i] - xs[i - 1]);
      return ys[i - 1] + f * (ys[i] - ys[i - 1]);
    }
  }
  return ys[ys.length - 1];
}

export function steadyState(s) {
  const q = qLin(s), R = outerRadius(s);
  const rP = Math.log(s.powder_radius / s.wire_radius) / (2 * Math.PI * s.k_powder);
  const rT = Math.log(R / s.powder_radius) / (2 * Math.PI * s.k_tube);
  const rC = 1 / (2 * Math.PI * R * s.h_ext);
  return { surface: q * rC, inner_wall: q * (rC + rT), wire: q * (rC + rT + rP) };
}

// --- PT100 et chaînes de mesure ----------------------------------------------
const A = 3.9083e-3, B = -5.775e-7;
export const pt100R = (T) => 100 * (1 + A * T + B * T * T);
export const pt100T = (R) => (-A + Math.sqrt(A * A - 4 * B * (1 - R / 100))) / (2 * B);

// Générateur pseudo-aléatoire reproductible (mulberry32) + loi normale
export function rng(seed = 1) {
  let a = seed >>> 0;
  const uni = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return { uni, normal: () => Math.sqrt(-2 * Math.log(uni() + 1e-12)) * Math.cos(2 * Math.PI * uni()) };
}

export const FRONT_ENDS = {
  ideal: { label: "Capteur idéal", measure: (T) => T, resolution: 0 },
  max31865: {
    label: "MAX31865",
    resolution: 430 / 32768 / 0.385,
    measure: (T, g) => {
      const code = Math.floor((pt100R(T) / 430) * 32768 + 0.7 * g.normal());
      return pt100T((code / 32768) * 430);
    },
  },
  legacy: {
    label: "Pont 10 kΩ v1",
    resolution: 25.7,
    measure: (T) => {
      const R = pt100R(T);
      const c = Math.min(1023, Math.floor(((5 * 10000) / (10000 + R) / 5) * 1024));
      const v = ((c + 0.5) * 5) / 1024;
      return pt100T(10000 * (5 / v - 1));
    },
  },
};

// --- Analyse -----------------------------------------------------------------
export function slopeMethod(t, T, q, tMin, tMax) {
  const xs = [], ys = [];
  for (let i = 0; i < t.length; i++) {
    if (t[i] > 0 && t[i] >= tMin && t[i] <= tMax && Number.isFinite(T[i])) { xs.push(Math.log(t[i])); ys.push(T[i]); }
  }
  const n = xs.length;
  if (n < 3) return null;
  const mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
  let sxx = 0, sxy = 0, syy = 0;
  for (let i = 0; i < n; i++) { sxx += (xs[i] - mx) ** 2; sxy += (xs[i] - mx) * (ys[i] - my); syy += (ys[i] - my) ** 2; }
  const slope = sxy / sxx, intercept = my - slope * mx;
  let ssr = 0;
  for (let i = 0; i < n; i++) ssr += (ys[i] - intercept - slope * xs[i]) ** 2;
  const slopeStd = Math.sqrt(ssr / Math.max(n - 2, 1) / sxx);
  const k = q / (4 * Math.PI * slope);
  const tw = t.filter((v) => v > 0 && v >= tMin && v <= tMax);
  return {
    k, kStd: Math.abs(k) * slopeStd / Math.abs(slope), slope, slopeStd, intercept,
    r2: syy > 0 ? 1 - ssr / syy : 1, n, tMin: Math.min(...tw), tMax: Math.max(...tw),
    kLegacy: k / Math.LN10,
  };
}

// Lecture d'un CSV au format du firmware / du simulateur / des essais v1
export function parseCSV(text) {
  const lines = text.split(/\r?\n/);
  const meta = {};
  const rows = [];
  let header = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("#")) {
      for (const tok of line.slice(1).split(/\s+/)) {
        const m = tok.match(/^([A-Za-z_]+)=([-+0-9.eE]+),?$/);
        if (m) meta[m[1]] = Number(m[2]);
      }
      continue;
    }
    const parts = line.split(/[,;\t]/).map((p) => p.trim());
    if (!header) { header = parts.map((p) => p.toLowerCase()); continue; }
    const vals = parts.map(Number);
    if (vals.every(Number.isFinite)) rows.push(vals);
  }
  if (!header) throw new Error("Aucune ligne d'en-tête trouvée.");
  const col = (name) => header.indexOf(name);
  let t;
  if (col("time_s") >= 0) t = rows.map((r) => r[col("time_s")]);
  else if (col("time_ms") >= 0) t = rows.map((r) => r[col("time_ms")] / 1000);
  else throw new Error("Colonne de temps manquante : time_s ou time_ms.");
  let T;
  if (col("temperature_c") >= 0) T = rows.map((r) => r[col("temperature_c")]);
  else if (col("resistance_ohm") >= 0) T = rows.map((r) => pt100T(r[col("resistance_ohm")]));
  else throw new Error("Colonne temperature_c ou resistance_ohm manquante.");
  let heatingEnd = null, baseline = null;
  const hc = col("heater");
  if (hc >= 0) {
    const on = rows.findIndex((r) => r[hc] > 0.5);
    if (on >= 0) {
      const t0 = t[on];
      const before = T.filter((_, i) => i < on);
      if (before.length >= 3) baseline = before.reduce((a, b) => a + b, 0) / before.length;
      t = t.map((v) => v - t0);
      const off = rows.findIndex((r, i) => i > on && r[hc] < 0.5);
      if (off >= 0) heatingEnd = t[off];
    }
  }
  const keep = t.map((v) => v >= 0 && (heatingEnd === null || v <= heatingEnd));
  return {
    t: t.filter((_, i) => keep[i]), T: T.filter((_, i) => keep[i]),
    meta, baseline, n: rows.length,
  };
}
