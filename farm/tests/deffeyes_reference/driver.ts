declare const process: any;
/**
 * The reference table of farm/tests/test_deffeyes.py and farm/tests/test_calculator.py: the source's
 * water-chemistry calculator (aquaculture_platform, commit 352aa2a8) run by its own pure functions: the
 * constants, the values, the chart's geometry, the dosing recipes and the dosing simulator (reagents.ts) and
 * the data of the four small charts beside the chart (ammonia-calc.ts, co2-calc.ts). Writes reference.json to
 * stdout.
 *
 * To make it again (nothing here runs in the source's checkout):
 * 1. Copy into ./src, unchanged, from that commit: libs/aquaculture-engines/src/water-chemistry/
 *    {water-quality,ammonia-calc,co2-calc,domains,types,deffeyes-data,reagents}.ts and
 *    web/shared-ui/src/water-chemistry/compute.ts; web/shared-ui/src/water-chemistry/types.ts as
 *    ui-types.ts. ./src/index.ts and ./src/shared-contracts.ts (a stub of the colours) are here.
 * 2. Point the imports at the copies: '@aquaculture/shared-contracts' → './shared-contracts.js' in
 *    reagents.ts and deffeyes-data.ts; '@platform/aquaculture-engines' → './index.js' in compute.ts and
 *    ui-types.ts; './types' → './ui-types.js' in compute.ts.
 * 3. node_modules/.bin/tsc -p farm/tests/deffeyes_reference/tsconfig.json, then
 *    node farm/tests/deffeyes_reference/out/driver.js > farm/tests/deffeyes_reference/reference.json
 *    (TypeScript 5.6.3, Node 22).
 *
 * Input mapping: the source's calculator takes "H₂S measured at the realtime pH" (µg/L, no basis); ours
 * takes the total sulfide as S. The source is fed h2sUgL = St × 34.08088/32.065 × fractionH2S(pH), the H₂S
 * that total sulfide gives at the pH by the source's own fraction, so that its total sulfide is ours on
 * the H₂S basis.
 */
import { computeWaterChemistryOutputs } from './src/compute.js';
import {
  alkMgToMeq,
  fractionH2S,
  generateDeffeyesChartData,
  getK1,
  getK2,
  calcKw,
  calcKB,
  getKNH4,
  getKH2S,
  phNbsToFree,
  swsToFree,
  totToFree,
  phLineSlope,
  phLineIntercept,
  REAGENTS,
  calcDicOfAlk,
  calculateDosingRecipes,
  calcForwardDosing,
  generateUIAvsPHData,
  generateH2SvsPHData,
  generateCarbonateVsPHData,
  generateSaturationVsPHData,
} from './src/index.js';

const H2S_PER_S = 34.08088 / 32.065;

function num(x: number): number | null {
  if (!isFinite(x)) return null;
  return Number(x.toPrecision(9));
}

const TEMPS = [0, 12, 25, 40];
const SALINITIES = [0, 1, 5, 15, 35, 50];
const PHS = [6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0];
const ALKS = [20, 100, 300, 800];
const TANS = [0.1, 0.5, 2, 6, 25];
const NH3_LIMITS = [0.0103, 0.02, 0.05];
const CO2_LIMITS = [10, 15, 40];
const SULFIDES = [1, 15, 200, 3000];
const H2S_LIMITS = [2, 25];
const TARGETS: Array<[number, number]> = [[7.5, 100], [6.8, 50], [8.2, 300]];
const BANDS: Array<[number, number]> = [[50, 100], [80, 200]];

function inputsAt(i: number, tempC: number, S: number, pH: number, alkMg: number) {
  const totalS = SULFIDES[i % SULFIDES.length];
  const h2sLimit = H2S_LIMITS[i % H2S_LIMITS.length];
  const fH2S = fractionH2S(pH, tempC, S);
  const [targetpH, targetAlk] = TARGETS[i % TARGETS.length];
  const [alkMin, alkMax] = BANDS[i % BANDS.length];
  return {
    ours: {
      temperature_c: tempC, salinity_ppt: S, ph: pH, alkalinity_mg_l: alkMg,
      tan_mg_l: TANS[i % TANS.length], nh3_n_limit: NH3_LIMITS[i % NH3_LIMITS.length],
      co2_limit: CO2_LIMITS[i % CO2_LIMITS.length], total_sulfide_ug_l: totalS, h2s_limit: h2sLimit,
      target_ph: targetpH, target_alkalinity_mg_l: targetAlk, alkalinity_low: alkMin, alkalinity_high: alkMax,
    },
    source: {
      tempC, pH, salinity: S, alkalinityMg: alkMg, targetpH, targetAlkalinityMg: targetAlk,
      alkMinMg: alkMin, alkMaxMg: alkMax, tan: TANS[i % TANS.length],
      unIonizedNH3: NH3_LIMITS[i % NH3_LIMITS.length], co2Toxic: CO2_LIMITS[i % CO2_LIMITS.length],
      h2sUgL: totalS * H2S_PER_S * fH2S, h2sLimitUgL: h2sLimit, caMgL: 400, volume: 1,
      fishType: 'Arctic Charr', fishSize: '0-5 gram', showTarget: true,
    } as any,
  };
}

const STATUS: Record<string, number> = { safe: 0, alert: 1, danger: 2 };

function outputsRow(i: number, tempC: number, S: number, pH: number, alkMg: number) {
  const { ours, source } = inputsAt(i, tempC, S, pH, alkMg);
  const o = computeWaterChemistryOutputs(source, []);
  const pHfree = phNbsToFree(pH, tempC, S);
  return {
    ...ours,
    isoline_slope: num(phLineSlope(pHfree, tempC, S)), isoline_intercept: num(phLineIntercept(pHfree, tempC, S)),
    dic: num(o.currentDIC), co2: num(o.currentCO2), co2_border: num(o.toxicCO2pH),
    target_dic: num(o.targetDIC), target_co2: num(o.targetCO2),
    nh3_border: num(o.toxicNH3pH), nh3_n: num(o.currentUIA), safe_tan: num(o.safeTAN),
    nh3_share_at_border_pct: num(o.uiaNPercent), nh3_status: STATUS[o.uiaStatusLevel],
    h2s_border: num(o.toxicH2SpH), h2s: num(o.currentH2S), total_sulfide_h2s_basis: num(o.totalSulfide),
    safe_total_sulfide_h2s_basis: num(o.safeTotalSulfide), h2s_status: STATUS[o.h2sStatusLevel],
  };
}

const rows: any[] = [];
let i = 0;
for (const tempC of TEMPS) for (const S of SALINITIES) for (const pH of PHS) for (const alk of ALKS) {
  rows.push(outputsRow(i, tempC, S, pH, alk));
  i += 1;
}
// Edges: TAN at and below the limit (never toxic) and just above it (its border above pH 12), no sulfide,
// a limit at or above the total, a border off the chart's pH range both ways (the source's 3 and 13.5), the
// calculator's pH ends (4 and 12 are ours; 6.25 and 11.25 the source's input bounds), alkalinity near 0.
const EDGES: Array<[number, number, number, number, Partial<Record<string, number>>]> = [
  [12, 1, 7.0, 80, { tan: 0.0103, unIonizedNH3: 0.0103 }],
  [12, 1, 7.0, 80, { tan: 0.005, unIonizedNH3: 0.0103 }],
  [12, 1, 7.0, 80, { tan: 0.01031, unIonizedNH3: 0.0103 }],
  [12, 1, 7.0, 80, { h2sUgL: 0 }],
  [12, 1, 7.0, 80, { h2sLimitUgL: 1e6 }],
  [12, 1, 7.0, 80, { totalS: 20000, h2sLimitUgL: 0.01 }],
  [12, 1, 7.0, 80, { totalS: 10, h2sLimitUgL: 10 * H2S_PER_S * 0.99999 }],
  [12, 1, 6.25, 80, {}], [12, 1, 11.25, 80, {}], [12, 35, 6.25, 120, {}], [12, 35, 11.25, 120, {}],
  [12, 0, 4.5, 20, {}], [12, 0, 10.5, 800, {}], [0, 50, 8.0, 115, {}], [40, 0, 6.0, 20, {}],
  [12, 1, 7.0, 0.5, {}], [25, 35, 8.1, 115, {}],
];
const edges: any[] = [];
for (const [tempC, S, pH, alk, override] of EDGES) {
  const { ours, source } = inputsAt(i, tempC, S, pH, alk);
  const { totalS, ...sourceOverride } = override;
  Object.assign(source, sourceOverride);
  if ('tan' in override) { ours.tan_mg_l = override.tan!; ours.nh3_n_limit = override.unIonizedNH3!; }
  if ('h2sUgL' in override) ours.total_sulfide_ug_l = 0;
  if ('h2sLimitUgL' in override) ours.h2s_limit = override.h2sLimitUgL!;
  if (totalS !== undefined) {
    ours.total_sulfide_ug_l = totalS;
    source.h2sUgL = totalS * H2S_PER_S * fractionH2S(pH, tempC, S);
  }
  const o = computeWaterChemistryOutputs(source, []);
  edges.push({
    ...ours, dic: num(o.currentDIC), co2: num(o.currentCO2), co2_border: num(o.toxicCO2pH),
    target_dic: num(o.targetDIC), target_co2: num(o.targetCO2),
    nh3_border: num(o.toxicNH3pH), nh3_n: num(o.currentUIA), safe_tan: num(o.safeTAN),
    nh3_status: STATUS[o.uiaStatusLevel], h2s_border: num(o.toxicH2SpH), h2s: num(o.currentH2S),
    safe_total_sulfide_h2s_basis: num(o.safeTotalSulfide), h2s_status: STATUS[o.h2sStatusLevel],
  });
  i += 1;
}

// The chart's geometry for a smaller set: what generateDeffeyesChartData draws (the farm calculator
// shows it on 0–6 mmol/L × 0–6 meq/L; the data runs to DIC 8, the zones' scan to 24).
const GEOMETRY: Array<[number, number, number, number, number, number, number, number, number, number]> = [];
// [tempC, S, pH, alkMg, tan, nh3Limit, co2Limit, totalS, h2sLimit, caMgL]
for (const [tempC, S] of [[12, 1], [12, 0], [4, 35], [25, 35], [20, 15], [8, 5], [30, 0], [0, 50]]) {
  for (const [pH, alk, tan, nh3, co2, st, h2sl] of [
    [7.0, 80, 0.5, 0.0103, 15, 1, 2], [7.5, 150, 2, 0.02, 10, 2.5, 2], [6.6, 40, 6, 0.05, 40, 3000, 2],
  ]) {
    GEOMETRY.push([tempC, S, pH, alk, tan, nh3, co2, st, h2sl, S >= 5 ? 412 * S / 35 : 400]);
  }
}
const geometry: any[] = [];
for (const [tempC, S, pH, alkMg, tan, nh3, co2, totalS, h2sLimit, caMgL] of GEOMETRY) {
  const h2sMeasured = totalS * H2S_PER_S * fractionH2S(pH, tempC, S);
  const d = generateDeffeyesChartData(
    { tempC, pH, salinity: S, alkalinity: alkMgToMeq(alkMg) },
    { targetpH: 7.5, targetAlkalinity: alkMgToMeq(120) },
    { tan, unIonizedNH3: nh3, co2Toxic: co2, h2sMeasuredUgL: h2sMeasured, h2sLimitUgL: h2sLimit, h2sMeasuredAtPH: pH },
    alkMgToMeq(50), alkMgToMeq(150), caMgL,
  );
  const pick = (points: Array<{ CT: number; AT: number }> | undefined, every: number) =>
    (points ?? []).filter((_p, k) => k % every === 0).map((p) => [p.CT, p.AT]);
  geometry.push({
    temperature_c: tempC, salinity_ppt: S, ph: pH, alkalinity_mg_l: alkMg, tan_mg_l: tan, nh3_n_limit: nh3,
    co2_limit: co2, total_sulfide_ug_l: totalS, h2s_limit: h2sLimit, calcium_mg_l: caMgL,
    target_ph: 7.5, target_alkalinity_mg_l: 120, alkalinity_low: 50, alkalinity_high: 150,
    isolines: d.isolines.map((iso) => [iso.pH, iso.points[0].AT, iso.points[iso.points.length - 1].CT,
      iso.points[iso.points.length - 1].AT]),
    co2_zone: d.co2ToxicZone ? pick(d.co2ToxicZone.points, 5) : null,
    nh3_zone: d.nh3ToxicZone ? pick(d.nh3ToxicZone.points, 20) : null,
    h2s_zone: d.h2sToxicZone ? pick(d.h2sToxicZone.points, 20) : null,
    safe_zone: d.safeZone ? [d.safeZone.topLeft, d.safeZone.topRight, d.safeZone.bottomRight, d.safeZone.bottomLeft]
      .map((c) => [num(c.DIC), num(c.ALK)]) : null,
    current: [num(d.currentPoint.DIC), num(d.currentPoint.ALK)],
    target: d.targetPoint ? [num(d.targetPoint.DIC), num(d.targetPoint.ALK)] : null,
    calcite: d.omegaCalcite ? pick(d.omegaCalcite.points, 10) : null,
    aragonite: d.omegaAragonite ? pick(d.omegaAragonite.points, 10) : null,
  });
}

function table(list: any[]) {
  const header = Object.keys(list[0]);
  return { header, rows: list.map((row) => header.map((key) => row[key])) };
}
const constants: any[] = [];
for (const tempC of TEMPS) for (const S of SALINITIES) {
  constants.push({
    temperature_c: tempC, salinity_ppt: S,
    pk1_free: num(-Math.log10(swsToFree(getK1(tempC, S), tempC, S))),
    pk2_free: num(-Math.log10(swsToFree(getK2(tempC, S), tempC, S))),
    pkw_free: num(-Math.log10(totToFree(calcKw(tempC, S), tempC, S))),
    pkb_free: num(-Math.log10(totToFree(calcKB(tempC, S), tempC, S))),
    pk_nh4_free: num(-Math.log10(swsToFree(getKNH4(tempC, S), tempC, S))),
    pk_h2s_free: num(-Math.log10(totToFree(getKH2S(tempC, S), tempC, S))),
    ph_offset: num(phNbsToFree(7, tempC, S) - 7),
  });
}

// ---- dosing (reagents.ts: calculateDosingRecipes as compute.ts calls it, calcForwardDosing as the
// calculator's page calls it) and the four small charts' data (ammonia-calc.ts, co2-calc.ts, as
// SecondaryCharts.tsx calls them) ----
const DEFAULT_REAGENTS = ['Sodium Bicarbonate', 'Sodium Hydroxide', 'Add CO₂', 'De-gas CO₂'];
const ALL_REAGENTS = REAGENTS.map((r) => r.name);
const SELECTIONS: string[][] = [DEFAULT_REAGENTS, ALL_REAGENTS];
for (let a = 0; a < ALL_REAGENTS.length; a++) {
  for (let b = a + 1; b < ALL_REAGENTS.length; b++) SELECTIONS.push([ALL_REAGENTS[a], ALL_REAGENTS[b]]);
}
// [tempC, S, pH, alkMg]
const DOSING_WATERS: Array<[number, number, number, number]> = [[12, 1, 7.0, 80], [25, 35, 8.1, 115], [8, 0, 6.6, 30]];
// [targetpH, targetAlkMg]: up and right, up and left, down, the water itself (12 °C), along NaHCO₃ and more
const DOSING_TARGETS: Array<[number, number]> = [[7.5, 100], [7.2, 60], [6.8, 150], [8.3, 80], [6.5, 40], [7.0, 80],
  [8.0, 200]];
const dosing: any[] = [];
let d = 0;
for (const [tempC, S, pH, alkMg] of DOSING_WATERS) for (const [targetpH, targetAlkMg] of DOSING_TARGETS) {
  for (const selected of SELECTIONS) {
    const volume = [1, 37.5][d % 2];
    const alk = alkMgToMeq(alkMg);
    const targetAlk = alkMgToMeq(targetAlkMg);
    const dic = calcDicOfAlk(alk, pH, tempC, S);
    const targetDic = calcDicOfAlk(targetAlk, targetpH, tempC, S);
    const recipes = calculateDosingRecipes(dic, alk, targetDic, targetAlk, volume, selected);
    dosing.push({
      temperature_c: tempC, salinity_ppt: S, ph: pH, alkalinity_mg_l: alkMg, target_ph: targetpH,
      target_alkalinity_mg_l: targetAlkMg, volume_m3: volume, reagents: selected,
      dic: num(dic), target_dic: num(targetDic),
      recipes: recipes.map((recipe) => recipe.steps.map((step) => [step.reagentName, num(step.amountGrams),
        num(step.deltaAlk), num(step.deltaDIC)])),
    });
    d += 1;
  }
}
const AMOUNTS: Array<Record<string, number>> = [
  { 'Sodium Bicarbonate': 50 },
  { 'Sodium Hydroxide': 20, 'De-gas CO₂': 30 },
  { 'Muriatic Acid': 40 },
  { 'Sodium Carbonate': 10, 'Calcium Carbonate': 5, 'Calcium Hydroxide': 5, 'Calcium Oxide': 5, 'Add CO₂': 10 },
  { 'De-gas CO₂': 500 },
  { 'Muriatic Acid': 4000 },
];
const forward: any[] = [];
for (const [tempC, S, pH, alkMg] of DOSING_WATERS) for (const amounts of AMOUNTS) for (const volume of [1, 2.5]) {
  const alk = alkMgToMeq(alkMg);
  const dic = calcDicOfAlk(alk, pH, tempC, S);
  // As the page does (WaterChemistryPage.tsx): the reagents with an amount, in the REAGENTS order.
  const inputs = REAGENTS.filter((r) => (amounts[r.name] || 0) > 0)
    .map((r) => ({ reagentKey: r.name, amountGrams: amounts[r.name] }));
  const steps = calcForwardDosing({ dic, alk, tempC, salinity: S }, volume, inputs);
  forward.push({
    temperature_c: tempC, salinity_ppt: S, ph: pH, alkalinity_mg_l: alkMg, volume_m3: volume, amounts,
    steps: steps.map((step) => [step.label, num(step.dic), num(step.alk), num(step.ph), num(step.co2)]),
  });
}
// [tempC, S, pH, alkMg, tan, nh3Limit, totalS (as S), h2sLimit, caMgL]
const CHART_WATERS: Array<[number, number, number, number, number, number, number, number, number]> = [
  [12, 1, 7.0, 80, 0.5, 0.0103, 2, 2, 400], [25, 35, 8.1, 115, 1, 0.02, 10, 2, 412], [4, 10, 7.5, 60, 3, 0.05, 50, 25, 150],
];
const phCharts: any[] = [];
for (const [tempC, S, pH, alkMg, tan, nh3Limit, totalS, h2sLimit, caMgL] of CHART_WATERS) {
  const h2sMeasured = totalS * H2S_PER_S * fractionH2S(pH, tempC, S);
  const dic = calcDicOfAlk(alkMgToMeq(alkMg), pH, tempC, S);
  const every = <T,>(list: T[], step: number) => list.filter((_p, k) => k % step === 0);
  phCharts.push({
    temperature_c: tempC, salinity_ppt: S, ph: pH, alkalinity_mg_l: alkMg, tan_mg_l: tan, nh3_n_limit: nh3Limit,
    total_sulfide_ug_l: totalS, h2s_limit: h2sLimit, calcium_mg_l: caMgL,
    uia: every(generateUIAvsPHData(tempC, S, tan, nh3Limit), 5).map((p) => [p.pH, num(p.UIA)]),
    h2s: every(generateH2SvsPHData(tempC, S, h2sMeasured, pH, h2sLimit, 4.0, 12.5), 10)
      .map((p) => [p.pH, num(p.H2S_pct), num(p.HS_pct), num(p.H2S_ugL)]),
    carbonate: every(generateCarbonateVsPHData(tempC, S, 2.0, 4.0, 12.0), 5)
      .map((p) => [p.pH, num(p.CO2), num(p.HCO3), num(p.CO3)]),
    saturation: every(generateSaturationVsPHData(tempC, S, dic, caMgL), 5)
      .map((p) => [p.pH, num(p.Calcite), num(p.Aragonite)]),
  });
}
process.stdout.write(JSON.stringify({
  source: 'aquaculture_platform 352aa2a8 (libs/aquaculture-engines/src/water-chemistry, web/shared-ui/src/water-chemistry/compute.ts)',
  generated_by: 'driver.ts with the main checkout tsc; node ' + process.version,
  h2s_per_s: H2S_PER_S,
  constants: table(constants), outputs: table(rows), edges: table(edges), geometry,
  dosing, forward, ph_charts: phCharts,
}));
