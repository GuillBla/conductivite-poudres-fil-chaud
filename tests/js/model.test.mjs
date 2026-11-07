// Vérifie que le portage JavaScript (site/js/model.js) reproduit le modèle Python.
// Lancer :  node --test tests/js/
// Les valeurs de référence sont produites par scripts/build_site_data.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { simulate, lineSourceRise, slopeMethod, parseCSV, pt100R, pt100T } from "../../site/js/model.js";

const root = new URL("../../", import.meta.url);
const data = JSON.parse(readFileSync(fileURLToPath(new URL("site/data/results.json", root)), "utf8"));
const ref = data.reference;

const close = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${msg}: ${a} vs ${b}`);

for (const c of ref.simulate) {
  test(`simulate() = Python (${c.name})`, () => {
    const out = simulate(c.setup, c.times, { heaterOffAt: c.heater_off_at });
    c.times.forEach((_, i) => {
      close(out.t_sensor[i], c.t_sensor[i], 1e-6, "capteur");
      close(out.t_wire[i], c.t_wire[i], 1e-6, "fil");
      close(out.t_surface[i], c.t_surface[i], 1e-6, "surface");
    });
  });
}

test("E1 et source linéique = scipy", () => {
  const L = ref.line_source;
  L.t.forEach((t, i) => close(lineSourceRise(L.r, t, L.q, L.k, L.alpha), L.dT[i], 1e-8 * Math.max(1, L.dT[i]), `t=${t}`));
});

test("méthode de la pente = Python", () => {
  const L = ref.line_source;
  const t = Array.from({ length: 600 }, (_, i) => 1 + (599 * i) / 599);
  const T = t.map((v) => 20 + lineSourceRise(L.r, v, L.q, L.k, L.alpha));
  close(slopeMethod(t, T, L.q, 10, 600).k, L.slope_k_10_600, 1e-6, "k");
});

test("PT100 aller-retour", () => {
  for (const T of [0, 25, 100, 250]) close(pt100T(pt100R(T)), T, 1e-9, `T=${T}`);
});

test("lecture CSV avec colonne heater et ligne de base", () => {
  const csv = "# power=0.8 length=0.2\ntime_ms,heater,raw,resistance_ohm,temperature_c\n" +
    "0,0,0,107.79,20\n1000,0,0,107.79,20\n2000,0,0,107.79,20\n3000,1,0,108,21\n4000,1,0,108.5,22\n5000,0,0,108,21\n";
  const m = parseCSV(csv);
  assert.equal(m.meta.power, 0.8);
  assert.equal(m.baseline, 20);
  assert.deepEqual(m.t, [0, 1, 2]);
});
