declare const process: any;
declare function require(name: string): any;
/**
 * B1 (owner amendment, 2026-11-05): the source platform's water-chemistry engine run on the inputs of chemcore's
 * golden reference, every output and every intermediate at full precision (no rounding), so that the source, our
 * Python and the Rust core are compared three ways (chemcore/scripts/b1_compare.py, farm/tests/test_b1.py).
 *
 * The engine is NOT in this repository (a second copy of the chemistry, licence unverified). To run:
 * 1. Copy, UNCHANGED, from aquaculture_platform commit 352aa2a8a94a178dd6543de6b741c520f5a1d6f3 (read only; nothing is
 *    built or run there) into <harness>/src/ keeping their paths:
 *    libs/aquaculture-engines/src/water-chemistry/{water-quality,ammonia-calc,co2-calc,domains,types,deffeyes-data,
 *    reagents,index}.ts and web/shared-ui/src/water-chemistry/{compute,types}.ts; the sha256 of each is in
 *    chemcore/golden/b1/PROVENANCE.txt and is checked by this driver's caller.
 * 2. Copy this folder (driver.ts, register.js, tsconfig.json) and ../src/shared-contracts.ts (colours only) as
 *    <harness>/stubs/shared-contracts.ts.
 * 3. tsc -p <harness>/tsconfig.json (TypeScript 5.6.3), then
 *    node -r <harness>/out/register.js <harness>/out/driver.js inputs.json > source.json   (Node 22)
 * The two package imports of the engine (@aquaculture/shared-contracts, @platform/aquaculture-engines) are resolved
 * by register.js, so no copied file is edited.
 *
 * Input mapping as in ../driver.ts: the source takes "H₂S measured at the realtime pH"; it is fed the H₂S our total
 * sulfide gives at that pH by the source's own fraction. Non-finite outputs are written as the strings 'NaN',
 * 'Infinity', '-Infinity'.
 */
const fs = require('fs');
const E = require('./src/libs/aquaculture-engines/src/water-chemistry/index.js');
const { computeWaterChemistryOutputs } = require('./src/web/shared-ui/src/water-chemistry/compute.js');

const H2S_PER_S = 34.08088 / 32.065;

function v(x: number): number | string {
  return Number.isFinite(x) ? x : String(x);
}

function constants(row: any) {
  const t = row.temp_c, s = row.salinity;
  return {
    k1_sws: v(E.getK1(t, s)), k2_sws: v(E.getK2(t, s)), kw_total: v(E.calcKw(t, s)), kb_total: v(E.calcKB(t, s)),
    k_nh4_sws: v(E.getKNH4(t, s)), k_h2s_total: v(E.getKH2S(t, s)), ks: v(E.calcKS(t, s)), kf: v(E.calcKF(t, s)),
    ionic_strength: v(E.calcIonicStrength(s)), total_boron: v(E.totalBoron(s)), total_sulfate: v(E.totalSulfate(s)),
    total_fluoride: v(E.totalFluoride(s)), activity_h: v(E.calcActivityCoefficientH(t, s)),
    free_to_sws: v(E.ahFreeToSwsFactor(t, s)), free_to_total: v(E.ahFreeToTotFactor(t, s)),
    sws_to_nbs: v(E.ahSwsToNbsFactor(t, s)), ksp_calcite: v(E.calcKspCalcite(t, s)),
    ksp_aragonite: v(E.calcKspAragonite(t, s)), ph_free_7: v(E.phNbsToFree(7, t, s)),
    k1_free: v(E.swsToFree(E.getK1(t, s), t, s)), k2_free: v(E.swsToFree(E.getK2(t, s), t, s)),
    kw_free: v(E.totToFree(E.calcKw(t, s), t, s)), kb_free: v(E.totToFree(E.calcKB(t, s), t, s)),
    k_nh4_free: v(E.swsToFree(E.getKNH4(t, s), t, s)), k_h2s_free: v(E.totToFree(E.getKH2S(t, s), t, s)),
    nh3_fraction_7_5: v(E.fractionNH3(7.5, t, s)),
  };
}

function carbonate(row: any) {
  const t = row.temp_c, s = row.salinity, ph = row.ph, alk = row.alkalinity_meq;
  const free = E.phNbsToFree(ph, t, s);
  const dic = E.calcDicOfAlk(alk, ph, t, s);
  const out: any = {
    hydrogen: v(Math.pow(10, -free)),
    fractions: [v(E.alphaZero(free, t, s)), v(E.alphaOne(free, t, s)), v(E.alphaTwo(free, t, s))],
    isoline: [v(E.phLineSlope(free, t, s)), v(E.phLineIntercept(free, t, s))],
    dic: v(dic), alkalinity_back: v(E.calcAlkOfDicPh(dic, ph, t, s)), co2: v(E.calcCo2OfDic(dic, ph, t, s)),
    carbonate: v(E.calcCO3(dic, ph, t, s)), nh3_share: v(E.fractionNH3(ph, t, s)), h2s_share: v(E.fractionH2S(ph, t, s)),
    alkalinity_floor: v(E.phLineIntercept(free, t, s) * 50.04345),
    ph_at: v(E.calcPhForAlkDic(alk, dic, t, s)),
    ph_where_co2_at_dic: v(E.calcPhForCritCO2(dic, 0.3 * 44.0096, t, s)),
    ph_where_nh3: v(E.criticalPHforNH3(0.5, 0.0103, t, s)),
    ph_where_nh3_chart: v(E.criticalPHforNH3PHChartDomain(0.5, 0.0103, t, s)),
    ph_where_h2s: v(E.criticalPHforH2S(3.0 * H2S_PER_S * E.fractionH2S(ph, t, s), ph, 2.0, t, s)),
    ph_where_h2s_chart: v(E.criticalPHforH2SPHChartDomain(3.0 * H2S_PER_S * E.fractionH2S(ph, t, s), ph, 2.0, t, s)),
  };
  for (const co2 of [5, 15, 40]) out[`ph_where_co2_${co2}`] = v(E.criticalPHforCO2(alk, co2, t, s));
  // link: the source's downstream functions fed OUR upstream value (the Python DIC recorded in the golden)
  out.link_alkalinity_back_of_python_dic = v(E.calcAlkOfDicPh(row.python_dic, ph, t, s));
  out.link_co2_of_python_dic = v(E.calcCo2OfDic(row.python_dic, ph, t, s));
  out.link_carbonate_of_python_dic = v(E.calcCO3(row.python_dic, ph, t, s));
  return out;
}

const STATUS: Record<string, string> = { safe: 'ok', alert: 'warning', danger: 'critical' };

function analysis(row: any) {
  const w = row.water, l = row.limits, target = row.target;
  const fH2S = E.fractionH2S(w.ph, w.temperature_c, w.salinity_ppt);
  const o = computeWaterChemistryOutputs({
    tempC: w.temperature_c, pH: w.ph, salinity: w.salinity_ppt, alkalinityMg: w.alkalinity_mg_l,
    targetpH: target ? target.ph : w.ph, targetAlkalinityMg: target ? target.alkalinity_mg_l : w.alkalinity_mg_l,
    alkMinMg: l.alkalinity_low_mg_l, alkMaxMg: l.alkalinity_high_mg_l, tan: w.tan_mg_l,
    unIonizedNH3: l.nh3_n_mg_l, co2Toxic: l.co2_mg_l, h2sUgL: w.total_sulfide_ug_l * H2S_PER_S * fH2S,
    h2sLimitUgL: l.h2s_ug_l, caMgL: w.calcium_mg_l ?? 0, volume: 1, fishType: 'Arctic Charr', fishSize: '0-5 gram',
    showTarget: true,
  } as any, []);
  return {
    dic: v(o.currentDIC), co2_mg_l: v(o.currentCO2), co2_border: v(o.toxicCO2pH), target_dic: v(o.targetDIC),
    target_co2_mg_l: v(o.targetCO2), nh3_border: v(o.toxicNH3pH), nh3_n_mg_l: v(o.currentUIA),
    safe_tan_mg_l: v(o.safeTAN), nh3_share_at_border_pct: v(o.uiaNPercent), nh3_status: STATUS[o.uiaStatusLevel],
    nh3_delta_ph: v(o.deltaPH), h2s_border: v(o.toxicH2SpH), h2s_ug_l: v(o.currentH2S),
    total_sulfide_h2s_basis: v(o.totalSulfide), safe_total_sulfide_h2s_basis: v(o.safeTotalSulfide),
    h2s_status: STATUS[o.h2sStatusLevel], h2s_delta_ph: v(o.h2sDeltaPH),
    nh3_border_chart: v(E.criticalPHforNH3PHChartDomain(w.tan_mg_l, l.nh3_n_mg_l, w.temperature_c, w.salinity_ppt)),
  };
}

function geometry(row: any) {
  const w = row.water, l = row.limits, t = w.temperature_c, s = w.salinity_ppt;
  const h2s = w.total_sulfide_ug_l * H2S_PER_S * E.fractionH2S(w.ph, t, s);
  const d = E.generateDeffeyesChartData(
    { tempC: t, pH: w.ph, salinity: s, alkalinity: E.alkMgToMeq(w.alkalinity_mg_l) },
    row.target ? { targetpH: row.target.ph, targetAlkalinity: E.alkMgToMeq(row.target.alkalinity_mg_l) } : null,
    { tan: w.tan_mg_l, unIonizedNH3: l.nh3_n_mg_l, co2Toxic: l.co2_mg_l, h2sMeasuredUgL: h2s, h2sLimitUgL: l.h2s_ug_l,
      h2sMeasuredAtPH: w.ph },
    E.alkMgToMeq(l.alkalinity_low_mg_l), E.alkMgToMeq(l.alkalinity_high_mg_l), w.calcium_mg_l ?? 0);
  const pts = (zone: any) => (zone ? zone.points.map((p: any) => [p.CT, p.AT]) : null);
  return {
    current: [v(d.currentPoint.DIC), v(d.currentPoint.ALK)],
    target: d.targetPoint ? [v(d.targetPoint.DIC), v(d.targetPoint.ALK)] : null,
    safe_zone: d.safeZone ? [d.safeZone.topLeft, d.safeZone.topRight, d.safeZone.bottomRight, d.safeZone.bottomLeft]
      .map((c: any) => [v(c.DIC), v(c.ALK)]) : null,
    nh3_zone: pts(d.nh3ToxicZone), co2_zone: pts(d.co2ToxicZone), h2s_zone: pts(d.h2sToxicZone),
    calcite: pts(d.omegaCalcite), aragonite: pts(d.omegaAragonite),
    isolines: d.isolines.map((iso: any) => [iso.pH, iso.points[0].AT, iso.points[iso.points.length - 1].CT,
      iso.points[iso.points.length - 1].AT]),
  };
}

const NAMES: Record<string, string> = {
  nahco3: 'Sodium Bicarbonate', na2co3: 'Sodium Carbonate', naoh: 'Sodium Hydroxide', caco3: 'Calcium Carbonate',
  caoh2: 'Calcium Hydroxide', cao: 'Calcium Oxide', co2: 'Add CO₂', degas: 'De-gas CO₂', hcl: 'Muriatic Acid',
};

function dosing(row: any) {
  const t = row.temp_c, s = row.salinity;
  const alk = E.alkMgToMeq(row.alkalinity_mg_l);
  const dic = E.calcDicOfAlk(alk, row.ph, t, s);
  if (row.kind === 'recipes') {
    const targetAlk = E.alkMgToMeq(row.target[1]);
    const targetDic = E.calcDicOfAlk(targetAlk, row.target[0], t, s);
    const recipes = E.calculateDosingRecipes(dic, alk, targetDic, targetAlk, row.volume ?? 1,
      row.chosen.map((key: string) => NAMES[key]));
    return { dic: v(dic), target_dic: v(targetDic), recipes: recipes.map((r: any) => r.steps.map((step: any) =>
      [step.reagentName, v(step.amountGrams), v(step.deltaAlk), v(step.deltaDIC)])) };
  }
  const inputs = E.REAGENTS.filter((r: any) => Object.entries(NAMES).some(([key, name]) => name === r.name
    && (row.amounts[key] || 0) > 0)).map((r: any) => ({
      reagentKey: r.name, amountGrams: row.amounts[Object.keys(NAMES).find((key) => NAMES[key] === r.name)!],
    }));
  const steps = E.calcForwardDosing({ dic, alk, tempC: t, salinity: s }, row.volume, inputs);
  return { steps: steps.map((step: any) => [v(step.dic), v(step.alk), v(step.ph), v(step.co2)]) };
}

const inputs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out: any = { engine: 'aquaculture_platform 352aa2a8a94a178dd6543de6b741c520f5a1d6f3', node: process.version };
out.constants = inputs.constants.map(constants);
out.carbonate = inputs.carbonate.map(carbonate);
out.analysis = inputs.analysis.map(analysis);
out.geometry = inputs.geometry.map(geometry);
out.dosing = inputs.dosing.map(dosing);
process.stdout.write(JSON.stringify(out));
