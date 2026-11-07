// Petit moteur de graphiques SVG (axes linéaires ou logarithmiques, courbes,
// points, bande de fenêtre, réticule + infobulle, tableau de données).
// Toutes les couleurs viennent des variables CSS du thème.

const NS = "http://www.w3.org/2000/svg";
const el = (name, attrs = {}, parent) => {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
};

function niceStep(span, target) {
  const raw = span / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
}

function linearTicks(min, max, target = 5) {
  const step = niceStep(max - min || 1, target);
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}

function logTicks(min, max, width = 600) {
  // 1-2-5 par décade si la place le permet, sinon seulement les puissances de 10
  const decades = Math.log10(max / min) || 1;
  const mantissas = width / decades > 120 ? [1, 2, 5] : [1];
  const out = [];
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++) {
    for (const m of mantissas) {
      const v = m * 10 ** e;
      if (v >= min * 0.999 && v <= max * 1.001) out.push(v);
    }
  }
  return out;
}

export const fmt = (v, digits = 3) => {
  if (!Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e6 || a < 1e-5)) return v.toExponential(1).replace(".", ",").replace("e", "·10^").replace("+", "");
  return Number(v.toPrecision(digits)).toLocaleString("fr-FR");
};

/**
 * chart(container, spec)
 * spec = { x: {type:'linear'|'log', label, min, max}, y: {label, min, max},
 *          series: [{label, color, type:'line'|'points', x, y, dash, width}],
 *          bands: [{x0, x1, label}], hlines: [{y, label}], height, unitX, unitY, table }
 */
export function chart(container, spec) {
  container.classList.add("chart");
  container.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "chart-plot";
  container.appendChild(wrap);
  const tip = document.createElement("div");
  tip.className = "chart-tip";
  tip.hidden = true;
  wrap.appendChild(tip);

  const legendSeries = spec.series.filter((s) => s.label && !s.noLegend);
  if (legendSeries.length >= 2) {
    const lg = document.createElement("div");
    lg.className = "chart-legend";
    for (const s of legendSeries) {
      const item = document.createElement("span");
      const key = document.createElement("i");
      key.className = s.type === "points" ? "key-dot" : s.dash ? "key-line dashed" : "key-line";
      key.style.setProperty("--c", s.color);
      item.append(key, document.createTextNode(s.label));
      lg.appendChild(item);
    }
    container.insertBefore(lg, wrap);
  }

  if (spec.table) {
    const det = document.createElement("details");
    det.className = "chart-table";
    const sum = document.createElement("summary");
    sum.textContent = "Voir les valeurs";
    det.appendChild(sum);
    const box = document.createElement("div");
    box.className = "table-scroll";
    const tbl = document.createElement("table");
    const main = spec.series.find((s) => s.type === "points") || spec.series[0];
    const head = tbl.createTHead().insertRow();
    for (const h of [spec.x.label, ...spec.series.map((s) => s.label)]) {
      const th = document.createElement("th");
      th.textContent = h;
      head.appendChild(th);
    }
    const body = tbl.createTBody();
    const stride = Math.max(1, Math.ceil(main.x.length / 40));
    for (let i = 0; i < main.x.length; i += stride) {
      const row = body.insertRow();
      row.insertCell().textContent = fmt(main.x[i], 4);
      for (const s of spec.series) row.insertCell().textContent = fmt(valueAt(s, main.x[i]), 4);
    }
    tbl.className = "data";
    box.appendChild(tbl);
    det.appendChild(box);
    container.appendChild(det);
  }

  const draw = () => render(wrap, tip, spec);
  draw();
  const ro = new ResizeObserver(() => draw());
  ro.observe(wrap);
  return { update: (patch) => { Object.assign(spec, patch); draw(); } };
}

function valueAt(s, x) {
  // valeur de la série la plus proche en x (interpolée pour les courbes)
  const xs = s.x, ys = s.y;
  if (!xs.length) return NaN;
  if (s.type === "line") {
    if (x < xs[0] || x > xs[xs.length - 1]) return NaN;
    for (let i = 1; i < xs.length; i++) {
      if (x <= xs[i]) {
        const f = (x - xs[i - 1]) / (xs[i] - xs[i - 1] || 1);
        return ys[i - 1] + f * (ys[i] - ys[i - 1]);
      }
    }
    return ys[ys.length - 1];
  }
  let best = 0, bd = Infinity;
  for (let i = 0; i < xs.length; i++) {
    const d = Math.abs(xs[i] - x);
    if (d < bd) { bd = d; best = i; }
  }
  return ys[best];
}

function render(wrap, tip, spec) {
  const old = wrap.querySelector("svg");
  if (old) old.remove();
  const W = Math.max(wrap.clientWidth, 260);
  const H = spec.height || Math.round(Math.min(340, Math.max(220, W * 0.55)));
  const m = { l: 52, r: 16, t: 12, b: 44 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const isLog = spec.x.type === "log";

  // Domaines
  let xs = [], ys = [];
  for (const s of spec.series) {
    s.x.forEach((v, i) => {
      if (Number.isFinite(v) && Number.isFinite(s.y[i]) && (!isLog || v > 0)) { xs.push(v); ys.push(s.y[i]); }
    });
  }
  let x0 = spec.x.min ?? Math.min(...xs), x1 = spec.x.max ?? Math.max(...xs);
  let y0 = spec.y.min ?? Math.min(...ys), y1 = spec.y.max ?? Math.max(...ys);
  if (spec.hlines) for (const h of spec.hlines) { y0 = Math.min(y0, h.y); y1 = Math.max(y1, h.y); }
  if (y1 - y0 < 1e-9) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.06;
  if (spec.y.min === undefined) y0 -= pad;
  if (spec.y.max === undefined) y1 += pad;
  const yt = linearTicks(y0, y1, Math.max(3, Math.round(ph / 55)));
  if (spec.y.min === undefined) y0 = Math.min(y0, yt[0]);
  if (spec.y.max === undefined) y1 = Math.max(y1, yt[yt.length - 1]);

  const sx = isLog
    ? (v) => m.l + ((Math.log(v) - Math.log(x0)) / (Math.log(x1) - Math.log(x0))) * pw
    : (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * pw;
  const invx = isLog
    ? (p) => Math.exp(Math.log(x0) + ((p - m.l) / pw) * (Math.log(x1) - Math.log(x0)))
    : (p) => x0 + ((p - m.l) / pw) * (x1 - x0);
  const sy = (v) => m.t + ph - ((v - y0) / (y1 - y0)) * ph;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
  if (spec.title) el("title", {}, svg).textContent = spec.title;
  wrap.insertBefore(svg, tip);

  // Bandes (fenêtre d'ajustement)
  for (const b of spec.bands || []) {
    const a = sx(Math.max(b.x0, x0)), c = sx(Math.min(b.x1, x1));
    if (c > a) {
      el("rect", { x: a, y: m.t, width: c - a, height: ph, class: "band" }, svg);
      if (b.label) {
        const t = el("text", { x: a + 6, y: m.t + 14, class: "band-label" }, svg);
        t.textContent = b.label;
      }
    }
  }

  // Grille et axes
  const g = el("g", { class: "axis" }, svg);
  for (const v of yt) {
    if (v < y0 - 1e-9 || v > y1 + 1e-9) continue;
    el("line", { x1: m.l, x2: m.l + pw, y1: sy(v), y2: sy(v), class: "grid" }, g);
    const t = el("text", { x: m.l - 8, y: sy(v) + 4, "text-anchor": "end" }, g);
    t.textContent = fmt(v);
  }
  const xt = isLog ? logTicks(x0, x1, pw) : linearTicks(x0, x1, Math.max(3, Math.round(pw / 90)));
  for (const v of xt) {
    if (v < x0 - 1e-9 || v > x1 + 1e-9) continue;
    el("line", { x1: sx(v), x2: sx(v), y1: m.t, y2: m.t + ph, class: "grid" }, g);
    const t = el("text", { x: sx(v), y: m.t + ph + 18, "text-anchor": "middle" }, g);
    t.textContent = fmt(v);
  }
  el("line", { x1: m.l, x2: m.l + pw, y1: m.t + ph, y2: m.t + ph, class: "baseline" }, g);
  const xl = el("text", { x: m.l + pw / 2, y: H - 6, "text-anchor": "middle", class: "axis-label" }, g);
  xl.textContent = spec.x.label;
  const yl = el("text", { x: 14, y: m.t + ph / 2, "text-anchor": "middle", class: "axis-label",
    transform: `rotate(-90 14 ${m.t + ph / 2})` }, g);
  yl.textContent = spec.y.label;

  for (const h of spec.hlines || []) {
    el("line", { x1: m.l, x2: m.l + pw, y1: sy(h.y), y2: sy(h.y), class: "zero" }, svg);
  }

  // Séries
  const clipId = "c" + Math.random().toString(36).slice(2);
  const cp = el("clipPath", { id: clipId }, el("defs", {}, svg));
  el("rect", { x: m.l, y: m.t - 4, width: pw, height: ph + 8 }, cp);
  const layer = el("g", { "clip-path": `url(#${clipId})` }, svg);
  const ordered = [...spec.series].sort((a, b) => (a.type === "points" ? 0 : 1) - (b.type === "points" ? 0 : 1));
  for (const s of ordered) {
    if (s.type === "points") {
      const gp = el("g", { class: "pts" }, layer);
      gp.style.setProperty("--c", s.color);
      s.x.forEach((v, i) => {
        if (!Number.isFinite(s.y[i]) || (isLog && v <= 0)) return;
        el("circle", { cx: sx(v), cy: sy(s.y[i]), r: s.r || 3 }, gp);
      });
    } else {
      let d = "";
      let pen = false;
      s.x.forEach((v, i) => {
        const y = s.y[i];
        if (!Number.isFinite(y) || (isLog && v <= 0)) { pen = false; return; }
        d += `${pen ? "L" : "M"}${sx(v).toFixed(1)},${sy(y).toFixed(1)}`;
        pen = true;
      });
      const p = el("path", { d, class: "line" + (s.dash ? " dashed" : "") }, layer);
      p.style.setProperty("--c", s.color);
      if (s.width) p.style.strokeWidth = s.width;
    }
  }

  // Étiquettes directes en bout de courbe (séries « line » marquées endLabel)
  for (const s of spec.series) {
    if (!s.endLabel || s.type !== "line") continue;
    let i = s.x.length - 1;
    while (i > 0 && !Number.isFinite(s.y[i])) i--;
    const t = el("text", { x: Math.min(sx(s.x[i]) - 4, m.l + pw - 4), y: sy(s.y[i]) - 7, "text-anchor": "end", class: "end-label" }, svg);
    t.textContent = s.endLabel;
  }

  // Réticule + infobulle
  const cross = el("line", { y1: m.t, y2: m.t + ph, class: "crosshair", visibility: "hidden" }, svg);
  const hit = el("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent", tabindex: 0,
    "aria-label": "Survoler pour lire les valeurs" }, svg);
  const show = (px) => {
    const xv = invx(Math.min(Math.max(px, m.l), m.l + pw));
    // aimantation sur le point de mesure le plus proche s'il existe
    const ref = spec.series.find((s) => s.type === "points") || spec.series[0];
    let xs2 = xv;
    if (ref.type === "points" && ref.x.length) {
      let bd = Infinity;
      for (const v of ref.x) {
        const d = Math.abs(sx(v) - sx(xv));
        if (d < bd) { bd = d; xs2 = v; }
      }
    }
    const X = sx(xs2);
    cross.setAttribute("x1", X); cross.setAttribute("x2", X);
    cross.setAttribute("visibility", "visible");
    tip.replaceChildren();
    const h = document.createElement("div");
    h.className = "tip-head";
    h.textContent = `${spec.x.label.split(" (")[0]} : ${fmt(xs2, 4)}${spec.unitX ? " " + spec.unitX : ""}`;
    tip.appendChild(h);
    for (const s of spec.series) {
      const v = valueAt(s, xs2);
      if (!Number.isFinite(v)) continue;
      const row = document.createElement("div");
      row.className = "tip-row";
      const key = document.createElement("i");
      key.className = s.type === "points" ? "key-dot" : "key-line";
      key.style.setProperty("--c", s.color);
      const b = document.createElement("b");
      b.textContent = `${fmt(v, 4)}${spec.unitY ? " " + spec.unitY : ""}`;
      const lab = document.createElement("span");
      lab.textContent = s.label || "";
      row.append(key, b, lab);
      tip.appendChild(row);
    }
    tip.hidden = false;
    const tw = tip.offsetWidth;
    tip.style.left = `${X + 12 + tw > W ? X - tw - 12 : X + 12}px`;
    tip.style.top = `${m.t + 6}px`;
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  hit.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    show(((e.clientX - r.left) / r.width) * W);
  });
  hit.addEventListener("pointerleave", hide);
  hit.addEventListener("focus", () => show(m.l + pw / 2));
  hit.addEventListener("blur", hide);
}
