import { simulate, steadyState, alphaPowder, outerRadius, qLin, slopeMethod, parseCSV, FRONT_ENDS, rng, DEFAULT_SETUP } from "./model.js";
import { chart, fmt } from "./plot.js";

const $ = (id) => document.getElementById(id);
const C = { s1: "var(--s1)", s2: "var(--s2)", s3: "var(--s3)", pts: "var(--pts)" };

// ---------------------------------------------------------------- utilitaires
function cssColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function hexToRgb(h) {
  const m = h.replace("#", "");
  const v = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
  return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16));
}
function heatColor(f, c0, c1) {
  f = Math.min(1, Math.max(0, f));
  return `rgb(${c0.map((v, i) => Math.round(v + (c1[i] - v) * f)).join(",")})`;
}
function stat(label, value, sub = "") {
  const d = document.createElement("div");
  d.className = "stat";
  const l = document.createElement("span"); l.className = "label"; l.textContent = label;
  const v = document.createElement("span"); v.className = "value"; v.textContent = value;
  d.append(l, v);
  if (sub) { const s = document.createElement("span"); s.className = "sub"; s.textContent = sub; d.appendChild(s); }
  return d;
}
function chip(kind, text) {
  const c = document.createElement("span");
  c.className = `chip ${kind}`;
  c.textContent = text;
  return c;
}
const pct = (v) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;
const duration = (s) => (s < 120 ? `${fmt(s, 3)} s` : s < 7200 ? `${fmt(s / 60, 3)} min` : `${fmt(s / 3600, 3)} h`);

// ---------------------------------------------------------------- coupe du tube
function drawSection(canvas, setup, profile, grid, tMin, tMax, sensor, gamma = 0.5) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width, cx = W / 2, cy = W / 2, Rpx = W * 0.46;
  const R = outerRadius(setup);
  const c0 = hexToRgb(cssColor("--heat-0")), c1 = hexToRgb(cssColor("--heat-1"));
  ctx.clearRect(0, 0, W, W);
  const faces = grid.faces;
  for (let i = profile.length - 1; i >= 0; i--) {
    ctx.beginPath();
    ctx.arc(cx, cy, Math.max((faces[i + 1] / R) * Rpx, 1), 0, Math.PI * 2);
    ctx.fillStyle = heatColor(Math.max(0, (profile[i] - tMin) / (tMax - tMin || 1)) ** gamma, c0, c1);
    ctx.fill();
  }
  const ink = cssColor("--ink");
  // paroi du tube
  ctx.lineWidth = Math.max(2, ((R - setup.powder_radius) / R) * Rpx);
  ctx.strokeStyle = cssColor("--muted");
  ctx.globalAlpha = 0.55;
  ctx.beginPath();
  ctx.arc(cx, cy, Rpx - ctx.lineWidth / 2, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;
  // fil
  ctx.fillStyle = ink;
  ctx.beginPath();
  ctx.arc(cx, cy, Math.max(W * 0.008, (setup.wire_radius / R) * Rpx), 0, Math.PI * 2);
  ctx.fill();
  // capteur
  if (sensor) {
    const sx = sensor === "wire" ? cx + W * 0.025 : cx + Rpx + W * 0.012;
    ctx.fillStyle = cssColor("--accent");
    ctx.strokeStyle = cssColor("--surface");
    ctx.lineWidth = W * 0.006;
    ctx.beginPath();
    ctx.rect(sx - W * 0.014, cy - W * 0.014, W * 0.028, W * 0.028);
    ctx.fill();
    ctx.stroke();
  }
}

// ---------------------------------------------------------------- hero animé
function hero(recSetup) {
  const canvas = $("hero-canvas");
  const s = { ...recSetup, sensor: "wire" };
  const times = Array.from({ length: 121 }, (_, i) => (i === 0 ? 0.001 : 2.5 * i));
  const sim = simulate(s, times, { keepProfiles: true });
  const tMax = Math.max(...sim.t_wire);
  const caption = $("hero-caption");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let frame = reduce ? times.length - 1 : 0, last = 0;
  const paint = (i) => {
    drawSection(canvas, s, sim.profiles[i], sim.grid, s.t_ambient, tMax, null, 0.35);
    caption.textContent = `Coupe du tube du montage recommandé, t = ${Math.round(times[i])} s après la mise en chauffe : la chaleur part du fil (au centre) et s'étale dans la poudre.`;
  };
  paint(frame);
  if (reduce) return;
  const loop = (ts) => {
    if (ts - last > 50) {
      frame = (frame + 1) % (times.length + 30);
      if (frame < times.length) paint(frame);
      last = ts;
    }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => paint(Math.min(frame, times.length - 1)));
}

// ---------------------------------------------------------------- section méthode
function methodCharts(data) {
  const scan = data.window_scan;
  chart($("chart-window"), {
    x: { type: "log", label: "début de la fenêtre t (s)" },
    y: { label: "erreur sur k (%)" },
    unitX: "s", unitY: "%",
    hlines: [{ y: 0 }],
    bands: [],
    series: [
      { label: "Montage v1", color: C.s2, type: "line", x: scan.v1.map((d) => d.t_min), y: scan.v1.map((d) => d.error * 100) },
      { label: "Montage recommandé", color: C.s1, type: "line", x: scan.recommande.map((d) => d.t_min), y: scan.recommande.map((d) => d.error * 100) },
    ],
    table: true,
  });
  const sens = data.sensitivity.v1;
  const all = ["wire", "outer"].flatMap((w) => Object.values(sens[w]).flat());
  const yMin = Math.min(...all), yMax = Math.max(...all);
  for (const where of ["wire", "outer"]) {
    const S = sens[where];
    chart($(`chart-sens-${where}`), {
      x: { type: "log", label: "temps (s)" },
      y: { label: "variation de T (K)", min: Math.floor(yMin / 50) * 50, max: Math.ceil(yMax / 50) * 50 + 25 },
      unitX: "s", unitY: "K",
      hlines: [{ y: 0 }],
      series: [
        { label: "k poudre", color: C.s1, type: "line", x: sens.t, y: S.k_powder },
        { label: "ρc poudre", color: C.s2, type: "line", x: sens.t, y: S.rhocp_powder },
        { label: "h extérieur", color: C.s3, type: "line", x: sens.t, y: S.h_ext },
      ],
      table: true,
    });
  }
}

// ---------------------------------------------------------------- simulateur
const PRESETS = {};
const state = {};
let simCharts = null;

function setControls(p) {
  $("in-k").value = Math.log10(p.k_powder);
  $("in-rhocp").value = p.rhocp_powder / 1e6;
  $("in-wire").value = p.wire_radius * 2e3;
  $("in-tube").value = Math.round(p.powder_radius * 2e3);
  $("in-length").value = Math.round(p.length * 1e3);
  $("in-power").value = Math.log10(p.power);
  $("in-h").value = p.h_ext;
  $("in-duration").value = p.duration;
  $("in-tmin").value = p.tmin;
  $("in-tmax").value = p.tmax;
  $("in-fe").value = p.fe;
  state.sensor = p.sensor;
}

function readControls() {
  const base = state.base;
  const s = {
    ...base,
    k_powder: 10 ** +$("in-k").value,
    rhocp_powder: +$("in-rhocp").value * 1e6,
    wire_radius: +$("in-wire").value / 2e3,
    powder_radius: +$("in-tube").value / 2e3,
    length: +$("in-length").value / 1e3,
    power: 10 ** +$("in-power").value,
    h_ext: +$("in-h").value,
    sensor: state.sensor,
  };
  $("out-k").textContent = `${fmt(s.k_powder, 3)} W/m/K`;
  $("out-rhocp").textContent = `${fmt(s.rhocp_powder / 1e6, 2)}·10⁶ J/m³/K`;
  $("out-wire").textContent = `${fmt(s.wire_radius * 2e3, 2)} mm`;
  $("out-tube").textContent = `${Math.round(s.powder_radius * 2e3)} mm`;
  $("out-length").textContent = `${Math.round(s.length * 1e3)} mm`;
  $("out-power").textContent = `${fmt(s.power, 3)} W`;
  $("out-h").textContent = `${s.h_ext} W/m²/K`;
  const dur = +$("in-duration").value;
  $("out-duration").textContent = duration(dur);
  for (const b of document.querySelectorAll("[data-sensor]")) b.setAttribute("aria-pressed", String(b.dataset.sensor === state.sensor));
  return { s, dur, tmin: +$("in-tmin").value, tmax: +$("in-tmax").value, fe: $("in-fe").value };
}

let pending = false;
function scheduleSim() {
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => { pending = false; runSim(); });
}

function runSim() {
  const ctl = readControls();
  const { s, dur, fe } = ctl;
  let { tmin, tmax } = ctl;
  const dt = Math.max(1, dur / 600);
  const times = [];
  for (let t = dt; t <= dur + 1e-9; t += dt) times.push(+t.toFixed(6));
  const sim = simulate(s, times, { keepProfiles: true, maxDt: Math.min(5, dt) });
  const g = rng(7);
  const meas = sim.t_sensor.map((T) => FRONT_ENDS[fe].measure(T, g));
  if (!(tmax > tmin)) { tmin = Math.min(10, dur / 10); tmax = dur; }
  tmax = Math.min(tmax, dur);
  const res = slopeMethod(times, meas, qLin(s), tmin, tmax);

  // statistiques
  const a = alphaPowder(s);
  const tWall = s.powder_radius ** 2 / (4 * a);
  const rise = Math.max(...sim.t_wire) - s.t_ambient;
  const riseSensor = Math.max(...sim.t_sensor) - s.t_ambient;
  const stats = $("sim-stats");
  stats.replaceChildren(
    stat("k imposé", `${fmt(s.k_powder, 3)}`, "W/m/K"),
    stat("k retrouvé (pente)", res ? fmt(res.k, 3) : "–", res ? `${pct(res.k / s.k_powder - 1)} · R² ${fmt(res.r2, 5)}` : "fenêtre trop courte"),
    stat("Échauffement du fil", `+${fmt(rise, 3)} K`, `max ${fmt(s.t_ambient + rise, 3)} °C`),
    stat("Chaleur à la paroi", duration(tWall), "R² / 4α"),
  );

  // alertes
  const chips = $("sim-chips");
  chips.replaceChildren();
  if (res) {
    const e = Math.abs(res.k / s.k_powder - 1);
    chips.appendChild(e < 0.02 ? chip("ok", `Erreur sur k ${pct(res.k / s.k_powder - 1)}`) : e < 0.1 ? chip("warn", `Erreur sur k ${pct(res.k / s.k_powder - 1)}`) : chip("bad", `Erreur sur k ${pct(res.k / s.k_powder - 1)}`));
  }
  if (s.sensor === "outer") chips.appendChild(chip("bad", "Capteur en paroi : la mesure dépend surtout de h et de ρc"));
  if (s.t_ambient + rise > 150) chips.appendChild(chip("bad", "Fil au-delà de 150 °C : réduire la puissance"));
  else if (rise > 40) chips.appendChild(chip("warn", "Échauffement du fil élevé : risque de convection dans la poudre"));
  if (s.sensor === "wire" && tmax > tWall) chips.appendChild(chip("warn", `La chaleur atteint la paroi (${duration(tWall)}) avant la fin de la fenêtre`));
  const wireLag = 20 * (s.wire_radius ** 2) / a;
  if (s.sensor === "wire" && tmin < wireLag) chips.appendChild(chip("warn", `Début de fenêtre trop tôt pour ce fil : commencer après ≈ ${duration(wireLag)}`));
  const reso = FRONT_ENDS[fe].resolution;
  if (reso > riseSensor / 10) chips.appendChild(chip("bad", `Résolution du capteur (${fmt(reso, 2)} °C) trop grossière pour ${fmt(riseSensor, 2)} K d'échauffement`));
  if (res && res.r2 < 0.999 && s.sensor === "wire") chips.appendChild(chip("warn", "La mesure n'est pas une droite en ln t dans cette fenêtre"));
  if (!chips.children.length) chips.appendChild(chip("ok", "Montage cohérent"));

  // graphiques
  const fitT = res ? times.filter((t) => t >= res.tMin && t <= res.tMax) : [];
  const fitY = fitT.map((t) => res.intercept + res.slope * Math.log(t));
  const lin = {
    x: { type: "linear", label: "temps depuis la mise en chauffe (s)", min: 0 },
    y: { label: "température (°C)" },
    unitX: "s", unitY: "°C",
    series: [
      { label: "fil (vrai)", color: C.s2, type: "line", x: times, y: sim.t_wire },
      { label: "paroi (vraie)", color: C.s1, type: "line", x: times, y: sim.t_surface },
      { label: `mesure (${FRONT_ENDS[fe].label})`, color: C.pts, type: "points", r: 2, x: times, y: meas },
    ],
  };
  const log = {
    x: { type: "log", label: "temps (s, échelle log)" },
    y: { label: "température mesurée (°C)" },
    unitX: "s", unitY: "°C",
    bands: res ? [{ x0: res.tMin, x1: res.tMax, label: "fenêtre" }] : [],
    series: [
      { label: "mesure", color: C.pts, type: "points", r: 2, x: times, y: meas },
      { label: res ? `droite : k = ${fmt(res.k, 3)} W/m/K` : "droite", color: C.s1, type: "line", x: fitT, y: fitY, width: 2.5 },
    ],
  };
  // recréés à chaque calcul pour que la légende reflète la valeur de k
  simCharts = { lin: chart($("chart-sim-lin"), lin), log: chart($("chart-sim-log"), log) };
  state.sim = { s, sim, times };
  drawXsec();
}

function drawXsec() {
  if (!state.sim) return;
  const { s, sim, times } = state.sim;
  const idx = Math.round((+$("xsec-time").value / 100) * (times.length - 1));
  const tMax = Math.max(...sim.t_wire);
  drawSection($("xsec-canvas"), s, sim.profiles[idx], sim.grid, s.t_ambient, tMax, s.sensor);
  $("xsec-label").textContent = `t = ${duration(times[idx])} · fil ${fmt(sim.t_wire[idx], 4)} °C · paroi ${fmt(sim.t_surface[idx], 4)} °C`;
  $("cb-min").textContent = `${fmt(s.t_ambient, 3)} °C`;
  $("cb-max").textContent = `${fmt(tMax, 3)} °C`;
  const g = sim.grid;
  const r = Array.from(g.centers).map((c, i) => (i === 0 ? 0 : c * 1e3));
  const prof = Array.from(sim.profiles[idx]);
  const spec = {
    x: { type: "linear", label: "distance au fil (mm)", min: 0, max: outerRadius(s) * 1e3 },
    y: { label: "T (°C)", min: s.t_ambient, max: tMax + (tMax - s.t_ambient) * 0.05 },
    unitX: "mm", unitY: "°C", height: 170,
    series: [{ label: "profil radial", color: C.s2, type: "line", x: r, y: prof }],
  };
  if (!state.profileChart) state.profileChart = chart($("chart-profile"), spec);
  else state.profileChart.update(spec);
}

function initSimulator(data) {
  const v1 = data.setups.v1, rec = data.setups.recommande;
  state.base = { ...DEFAULT_SETUP, ...rec };
  PRESETS.rec = { ...rec, duration: 300, tmin: 10, tmax: 300, fe: "max31865", sensor: "wire" };
  PRESETS.v1 = { ...v1, duration: 3600, tmin: 720, tmax: 3600, fe: "max31865", sensor: "outer" };
  const apply = (name) => {
    state.base = { ...DEFAULT_SETUP, ...(name === "rec" ? rec : v1) };
    setControls(PRESETS[name]);
    $("preset-rec").classList.toggle("primary", name === "rec");
    $("preset-v1").classList.toggle("primary", name === "v1");
    runSim();
  };
  $("preset-rec").addEventListener("click", () => apply("rec"));
  $("preset-v1").addEventListener("click", () => apply("v1"));
  $("sim-form").addEventListener("input", scheduleSim);
  $("sim-form").addEventListener("submit", (e) => e.preventDefault());
  for (const b of document.querySelectorAll("[data-sensor]")) {
    b.addEventListener("click", () => { state.sensor = b.dataset.sensor; scheduleSim(); });
  }
  $("in-duration").addEventListener("change", () => {
    const d = +$("in-duration").value;
    if (+$("in-tmax").value > d || +$("in-tmax").value < d * 0.5) $("in-tmax").value = d;
    if (+$("in-tmin").value >= d) $("in-tmin").value = Math.round(d / 10);
    scheduleSim();
  });
  $("xsec-time").addEventListener("input", drawXsec);
  let playing = null;
  $("xsec-play").addEventListener("click", () => {
    if (playing) { clearInterval(playing); playing = null; $("xsec-play").textContent = "▶"; return; }
    if (+$("xsec-time").value >= 100) $("xsec-time").value = 0;
    $("xsec-play").textContent = "❚❚";
    playing = setInterval(() => {
      const v = +$("xsec-time").value + 1;
      $("xsec-time").value = Math.min(v, 100);
      drawXsec();
      if (v >= 100) { clearInterval(playing); playing = null; $("xsec-play").textContent = "▶"; }
    }, 60);
  });
  apply("rec");
}

// ---------------------------------------------------------------- analyse de fichiers
const EXAMPLES = {
  "simulation_recommande.csv": "Exemple : simulation du montage recommandé (k imposé = 0,20 W/m/K, bruit d'un MAX31865).",
  "essai_2.csv": "Exemple : essai 2 de la v1. Capteur collé sur la paroi : la méthode de la pente ne s'applique pas à cette mesure.",
  "essai_1.csv": "Exemple : essai 1 de la v1. Capteur collé sur la paroi : la méthode de la pente ne s'applique pas à cette mesure.",
};
const an = { data: null, charts: null };

function loadText(text, source) {
  const err = $("an-err");
  err.hidden = true;
  try {
    const m = parseCSV(text);
    if (m.t.length < 5) throw new Error("Moins de 5 points exploitables en phase de chauffe.");
    an.data = m;
    $("an-source").textContent = source;
    if (m.meta.power) $("an-power").value = m.meta.power;
    if (m.meta.length) $("an-length").value = m.meta.length;
    const tEnd = Math.max(...m.t);
    $("an-tmax").value = Math.round(tEnd);
    $("an-tmin").value = tEnd <= 900 ? 10 : Math.round(tEnd / 5);
    runAnalysis();
  } catch (e) {
    err.textContent = `Lecture impossible : ${e.message}`;
    err.hidden = false;
  }
}

function runAnalysis() {
  const m = an.data;
  if (!m) return;
  const P = +$("an-power").value, L = +$("an-length").value;
  const tmin = +$("an-tmin").value, tmax = +$("an-tmax").value;
  const stats = $("an-stats"), chips = $("an-chips");
  chips.replaceChildren();
  if (!(P > 0 && L > 0)) {
    stats.replaceChildren();
    chips.appendChild(chip("warn", "Renseignez la puissance P et la longueur L pour calculer k"));
    return;
  }
  const q = P / L;
  const res = slopeMethod(m.t, m.T, q, tmin, tmax);
  if (!res) {
    stats.replaceChildren();
    chips.appendChild(chip("bad", "Moins de 3 points dans la fenêtre choisie"));
    return;
  }
  stats.replaceChildren(
    stat("Conductivité k", fmt(res.k, 4), `± ${fmt(res.kStd, 2)} W/m/K (statistique)`),
    stat("Pente dT/d ln t", `${fmt(res.slope, 4)} K`, `q = ${fmt(q, 4)} W/m`),
    stat("Qualité R²", res.r2.toLocaleString("fr-FR", { maximumFractionDigits: 5 }), `${res.n} points, ${fmt(res.tMin, 3)}–${fmt(res.tMax, 4)} s`),
    stat("Calcul « tableur v1 »", fmt(res.kLegacy, 3), "avec log10 : 2,303 fois trop petit"),
  );
  chips.appendChild(res.r2 > 0.999 ? chip("ok", "Droite bien établie (R² > 0,999)") : res.r2 > 0.99 ? chip("warn", "R² < 0,999 : vérifiez la fenêtre") : chip("bad", "Ce n'est pas une droite en ln t : résultat non interprétable"));
  // courbure des résidus : premier/dernier tiers vs milieu
  const inW = m.t.map((t, i) => [t, m.T[i]]).filter(([t]) => t > 0 && t >= res.tMin && t <= res.tMax);
  const r = inW.map(([t, T]) => T - res.intercept - res.slope * Math.log(t));
  const third = Math.floor(r.length / 3);
  if (third >= 3) {
    const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
    const ends = (mean(r.slice(0, third)) + mean(r.slice(-third))) / 2 - mean(r.slice(third, -third));
    const rms = Math.sqrt(mean(r.map((v) => v * v)));
    if (Math.abs(ends) > 2 * rms / Math.sqrt(third) && Math.abs(ends) > 0.5 * rms) {
      chips.appendChild(chip("warn", ends > 0 ? "Résidus en U : la pente augmente, la paroi est peut-être atteinte" : "Résidus en ∩ : la pente diminue, effet du fil ou de la ligne de base"));
    }
  }
  if (m.baseline !== null) chips.appendChild(chip("ok", `Ligne de base détectée : ${fmt(m.baseline, 4)} °C`));

  const pos = m.t.map((t, i) => [t, m.T[i]]).filter(([t]) => t > 0);
  const fitT = pos.map(([t]) => t).filter((t) => t >= res.tMin && t <= res.tMax);
  const spec = {
    x: { type: "log", label: "temps depuis la mise en chauffe (s, échelle log)" },
    y: { label: "température (°C)" },
    unitX: "s", unitY: "°C",
    bands: [{ x0: res.tMin, x1: res.tMax, label: "fenêtre" }],
    series: [
      { label: "mesure", color: C.pts, type: "points", r: 2.5, x: pos.map((p) => p[0]), y: pos.map((p) => p[1]) },
      { label: `droite : k = ${fmt(res.k, 3)} W/m/K`, color: C.s1, type: "line", width: 2.5, x: fitT, y: fitT.map((t) => res.intercept + res.slope * Math.log(t)) },
    ],
    table: true,
  };
  const resid = {
    x: { type: "log", label: "temps (s, échelle log)" },
    y: { label: "résidu (K)" },
    unitX: "s", unitY: "K", height: 190,
    hlines: [{ y: 0 }],
    bands: [{ x0: res.tMin, x1: res.tMax }],
    series: [{ label: "écart à la droite", color: C.pts, type: "points", r: 2.5, x: pos.map((p) => p[0]), y: pos.map(([t, T]) => T - res.intercept - res.slope * Math.log(t)) }],
  };
  if (!an.charts) an.charts = { main: chart($("chart-an"), spec), res: chart($("chart-an-res"), resid) };
  else { an.charts.main = chart($("chart-an"), spec); an.charts.res.update(resid); }
}

async function loadExample(name) {
  const r = await fetch(`data/${name}`);
  loadText(await r.text(), EXAMPLES[name]);
}

function initAnalyzer() {
  for (const id of ["an-power", "an-length", "an-tmin", "an-tmax"]) $(id).addEventListener("input", runAnalysis);
  $("ex-select").addEventListener("change", (e) => loadExample(e.target.value));
  const readFile = (f) => {
    const fr = new FileReader();
    fr.onload = () => loadText(String(fr.result), `Fichier : ${f.name}`);
    fr.readAsText(f);
  };
  $("file").addEventListener("change", (e) => e.target.files[0] && readFile(e.target.files[0]));
  const drop = $("drop");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (e.dataTransfer.files[0]) readFile(e.dataTransfer.files[0]);
  });
  loadExample("simulation_recommande.csv");
}

// ---------------------------------------------------------------- essais v1
function v1Section(data) {
  const E = data.essais;
  const pm = (v, s) => `${fmt(v, 3)} ± ${fmt(s, 2)}`;
  const rows = [
    ["Tableur d'origine (log10, fenêtre manuelle)", "—", "0,86"],
    ["Pente en ln t, fin de courbe", ...E.map((e) => pm(e.slope.k, e.slope.k_std))],
    ["Ajustement E1 (capteur à 16 mm)", ...E.map((e) => pm(e.line.params.k, e.line.std.k))],
    ["Modèle complet (k, ρc, h, T air)", ...E.map((e) => pm(e.model.params.k_powder, e.model.std.k_powder))],
    ["ρc ajusté par le modèle (10⁶ J/m³/K)", ...E.map((e) => fmt(e.model.params.rhocp_powder / 1e6, 3))],
  ];
  const tbl = $("v1-table");
  const head = tbl.createTHead().insertRow();
  for (const h of ["Méthode", ...E.map((e) => `${e.title} · ${fmt(e.power, 3)} W`)]) {
    const th = document.createElement("th"); th.textContent = h; head.appendChild(th);
  }
  const body = tbl.createTBody();
  for (const r of rows) {
    const tr = body.insertRow();
    r.forEach((c) => (tr.insertCell().textContent = c));
  }

  E.forEach((e, i) => {
    $(`v1-title-${i}`).textContent = `${e.title} : ${fmt(e.power, 3)} W sur ${fmt(e.length * 1000, 3)} mm, PT100 en paroi`;
    const sl = e.slope;
    const tw = e.t.filter((t) => t >= sl.t_min && t <= sl.t_max);
    chart($(`chart-v1-${i}`), {
      x: { type: "linear", label: "temps (s)", min: 0 },
      y: { label: "température (°C)" },
      unitX: "s", unitY: "°C",
      series: [
        { label: "mesure", color: C.pts, type: "points", r: 2.5, x: e.t, y: e.T },
        { label: `pente : k = ${fmt(sl.k, 3)}`, color: C.s1, type: "line", x: tw, y: tw.map((t) => sl.intercept + sl.slope * Math.log(t)) },
        { label: `E1 : k = ${fmt(e.line.params.k, 3)}`, color: C.s2, type: "line", dash: true, x: e.line.curve.t, y: e.line.curve.T },
        { label: `modèle complet : k = ${fmt(e.model.params.k_powder, 3)}`, color: C.s3, type: "line", x: e.model.curve.t, y: e.model.curve.T },
      ],
      table: true,
    });
  });

  const e1 = E[0];
  const items = [
    ["Des résultats incompatibles. ", `Selon la méthode, k va de ${fmt(Math.min(...E.flatMap((e) => [e.slope.k, e.line.params.k, e.model.params.k_powder])), 2)} à ${fmt(Math.max(...E.flatMap((e) => [e.slope.k, e.line.params.k, e.model.params.k_powder])), 2)} W/m/K, un écart bien plus grand que les incertitudes statistiques de chaque méthode.`],
    ["Une capacité thermique impossible. ", `Le modèle complet ne reproduit les courbes qu'avec ρc = ${E.map((e) => fmt(e.model.params.rhocp_powder / 1e6, 2)).join(" et ")}·10⁶ J/m³/K, contre environ 1·10⁶ pour une poudre. Les corrélations entre k, ρc et h dépassent 0,9.`],
    ["Un bilan d'énergie qui ne boucle pas. ", `L'essai 1 injecte ${fmt(e1.energy_J, 3)} J. Sans pertes, la poudre (≈ ${fmt(e1.capacity_J_per_K, 2)} J/K) aurait pris ${fmt(e1.rise_without_losses_K, 2)} K ; la paroi n'a pris que ${fmt(e1.rise_measured_K, 3)} K. L'essentiel de la chaleur est parti ailleurs : pertes axiales, ou puissance mesurée hors du fil.`],
    ["Un calcul biaisé. ", "Le tableur prenait la pente en log10 : son résultat est 2,303 fois trop petit, en plus de dépendre fortement de la fenêtre choisie à la main."],
  ];
  const ul = $("v1-findings");
  for (const [b, t] of items) {
    const li = document.createElement("li");
    const strong = document.createElement("b"); strong.textContent = b;
    li.append(strong, document.createTextNode(t));
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------- navigation
function initNav() {
  const links = [...document.querySelectorAll(".nav a")];
  const map = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.isIntersecting) {
        links.forEach((a) => a.classList.remove("active"));
        map.get(en.target.id)?.classList.add("active");
      }
    }
  }, { rootMargin: "-45% 0px -50% 0px" });
  for (const id of map.keys()) { const s = $(id); if (s) io.observe(s); }
}

// ---------------------------------------------------------------- démarrage
async function main() {
  initNav();
  const data = await (await fetch("data/results.json")).json();
  hero(data.setups.recommande);
  methodCharts(data);
  initSimulator(data);
  initAnalyzer();
  v1Section(data);
}
main().catch((e) => {
  console.error(e);
  const p = document.createElement("p");
  p.className = "err gutter";
  p.textContent = `Le chargement des données a échoué (${e.message}). Ouvrez la page via un serveur web (GitHub Pages ou « python -m http.server » dans le dossier site).`;
  document.querySelector("main").prepend(p);
});
