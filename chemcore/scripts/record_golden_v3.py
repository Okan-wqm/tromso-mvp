"""Golden v3: formula 3, the application's since the switch (owner, 2026-11-09): I1, the Debye-Hückel A of the water's
temperature, and I2, fresh water's ionic strength with the band from 1 to 5 permil (chemcore/core/src/fresh.rs;
chemcore/findings/B1.md, I1 and I2; chemcore/findings/I2-comparison.md), recorded from the core beside golden v1.

    docker run --rm -v "$PWD:/app" -w /app <runner image> python chemcore/scripts/record_golden_v3.py chemcore/golden/v3

Writes <out>/waters.jsonl.gz (one JSON object per line, keys sorted, floats as Python repr; gzip with mtime 0, so two
runs give the same bytes) and <out>/manifest.json. A water of the corpus: a temperature, a salinity, an
alkalinity and what is measured of its ions (nothing, a conductivity at 25 °C, a hardness), fresh, hard, brackish and sea
water. For each, formula 1's and formula 3's constants (Equilibria's fields) and provenance (formula, ionic strength,
its source, the seawater share), and what the owner compares: at each of five pHs the CO2 (mg/L) at its alkalinity and
the NH3 share of the TAN (the judged one, the larger of the limits' basis and the activity-corrected, cross review F1,
and the corrected one), with the pH offset (free - NBS) among the constants. Block `analyses`: the whole analysis
(native.analyse: CO2 and its border, NH3-N and its border, each judged with its corrected value and basis, H2S, the oxygen) of every water at pH 7.0 with a TAN, a
sulfide, the default limits and a target, by formula 1 and by formula 3. The values are the core's (bit for bit on every platform, `libm`), so
farm/tests/test_golden_v3.py holds the core to them exactly. Standard library and farm.water.native only.

Recorded again, each time by this script and with its reason (formula 3 had not left its branch: the corrections went
into formula 3 itself, formula 1's values in these files never moved; chemcore/findings/I2-comparison.md, the part of
2026-11-10, has the numbers that moved):
- 2026-11-10, Kw: formula 3's ion product of water is Millero's (1995) on his seawater scale over [H+]SWS/[H+]free
  (pure water's at S 0), no longer the 2007 Guide's approximate total-scale value (owner-approved after the independent
  check of 2026-11-09 against PyCO2SYS and seacarb). The constant `kw` moves by -0.8 to +1.5 % in the corpus; the CO2
  worked out from it by at most +0.085 % (30 °C, S 35, 20 mg/L, pH 8.5), a median of 0.0002 %. The judged CO2 moves only
  where the water's own value judges (1 440 of 9 900): the basis the limits were set on keeps formula 1's Kw.
- 2026-11-10, Ω: each pH of a water from 5 permil also holds `log_omega`, log10 Ω of calcite and of aragonite with 400
  mg/L of calcium (no Ω was recorded before). Formula 3's takes the Ksp per litre, Mucci's per-kg2 Ksp times the square
  of the sea water's density (EOS-80; owner-approved after the same check, claim 12b: Ω was ρ2 too high); formula 1's
  keeps the per-kg Ksp, as golden v1 holds it. FORMAT 2: a key was added."""
import gzip
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FORMAT = 2
TEMPERATURES = (2.0, 8.0, 12.0, 18.0, 25.0, 30.0)
SALINITIES = (0.0, 0.5, 1.0, 2.0, 3.0, 4.99, 5.0, 10.0, 28.3, 28.5, 35.0)   # 28.3, 28.5: NaCl's Davies limit
PHS = (6.5, 7.0, 7.5, 8.0, 8.5)
ALKALINITIES = (20.0, 80.0, 200.0)                    # mg/L as CaCO3
IONS = ({}, {'conductivity_25_us_cm': 50.0}, {'conductivity_25_us_cm': 300.0}, {'conductivity_25_us_cm': 1000.0},
        {'conductivity_25_us_cm': 3000.0}, {'hardness_mg_l': 50.0}, {'hardness_mg_l': 300.0},
        # Salt-added fresh water (cross review F3; round 2): the fresh path to the Davies limit, then the sea path.
        {'water_origin': 'salt_added'}, {'conductivity_25_us_cm': 3000.0, 'water_origin': 'salt_added'},
        {'water_origin': 'seawater'})
LIMITS = {'nh3_n_mg_l': 0.0103, 'co2_mg_l': 15.0, 'h2s_ug_l': 2.0, 'alkalinity_low_mg_l': 50.0,
          'alkalinity_high_mg_l': 150.0}
CALCIUM_MG_L = 400.0                                  # the calcium Ω is recorded with (the calculator's example)
OMEGA_SALINITY = (5.0, 44.0)                          # Ω is drawn where Mucci (1983) measured (the core's geometry.rs)
ANALYSIS_KEYS = ('co2_mg_l', 'co2', 'nh3_n_mg_l', 'nh3', 'safe_tan_mg_l', 'h2s_ug_l', 'h2s', 'dic', 'target_dic',
                 'oxygen_solubility_mg_l', 'oxygen_saturation_pct', 'nh3_share_pct', 'h2s_share_pct',
                 'co2_corrected_mg_l', 'co2_basis', 'nh3_corrected_n_mg_l', 'nh3_basis')


def native():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from farm.water import native as found
    return found


def log_omega(eq, alkalinity_meq, ph, native_):
    """log10 Ω of calcite and of aragonite of a water with CALCIUM_MG_L of calcium (the small chart's saturation index);
    None outside the salinities Ω is drawn for."""
    if not OMEGA_SALINITY[0] <= eq.salinity <= OMEGA_SALINITY[1]:
        return None
    dic = eq.dic(alkalinity_meq, ph)
    return {name: native_.saturation_index(eq, dic, ph, CALCIUM_MG_L, ksp)
            for name, ksp in (('calcite', eq.ksp_calcite), ('aragonite', eq.ksp_aragonite))}


def outputs(eq, alkalinity_mg_l, native_):
    """The constants (the pH offset among them) and, at each pH, the CO2 (mg/L), the NH3 share and log10 Ω."""
    meq = alkalinity_mg_l / native_.MG_CACO3_PER_MEQ
    return {'constants': dict(zip(native_.Equilibria.fields, eq.values())),
            'provenance': {'formula': eq.formula, 'ionic_strength': eq.ionic_strength, 'source': eq.strength_source,
                           'sea_weight': eq.sea_weight, 'warnings': eq.warnings,
                           'water_origin': eq.water_origin},
            'at_ph': [{'ph': ph, 'co2_mg_l': eq.co2(eq.dic(meq, ph), ph) * native_.MG_CO2_PER_MMOL,
                       'co2_judged_mg_l': eq.co2_judged(meq, ph)[0] * native_.MG_CO2_PER_MMOL,
                       'nh3_share': eq.nh3_share(ph), 'nh3_share_corrected': eq.nh3_share_corrected(ph),
                       'nh3_share_limits': eq.nh3_share_limits(ph), 'log_omega': log_omega(eq, meq, ph, native_)}
                      for ph in PHS],
            'nh3_basis': eq.nh3_basis}


def record_all():
    """{block: [records]} of the corpus."""
    n = native()
    waters = []
    for temp_c in TEMPERATURES:
        for salinity in SALINITIES:
            for alkalinity in ALKALINITIES:
                for ions in IONS:
                    strength, source = n.fresh_ionic_strength(salinity, alkalinity, **ions)
                    v1 = n.water_equilibria(temp_c, salinity, alkalinity, **ions, formula=1)
                    v3 = n.water_equilibria(temp_c, salinity, alkalinity, **ions, formula=3)
                    waters.append({'temp_c': temp_c, 'salinity': salinity, 'alkalinity_mg_l': alkalinity, 'ions': ions,
                                   'ionic_strength': strength, 'source': source, 'v1': outputs(v1, alkalinity, n),
                                   'v3': outputs(v3, alkalinity, n)})
    analyses = []
    for temp_c in TEMPERATURES:
        for salinity in SALINITIES:
            for alkalinity in ALKALINITIES:
                for ions in IONS:
                    record = {'temp_c': temp_c, 'salinity': salinity, 'alkalinity_mg_l': alkalinity, 'ions': ions}
                    for formula in (1, 3):
                        found = n.analyse(temp_c, salinity, 7.0, alkalinity, tan_mg_l=0.5, total_sulfide_ug_l=2.0,
                                          oxygen_mg_l=10.0, formula=formula, **ions, **LIMITS, target_ph=7.5,
                                          target_alkalinity_mg_l=100.0)
                        record[f'v{formula}'] = {key: found[key] for key in ANALYSIS_KEYS}
                    analyses.append(record)
    return {'waters': waters, 'analyses': analyses}


def encode(records):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, compresslevel=9) as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False, ensure_ascii=False).encode('utf-8'))
            stream.write(b'\n')
    return buffer.getvalue()


def manifest(encoded):
    n = native()
    return {
        'format': FORMAT, 'golden_version': 'v3', 'beside': 'v1',
        'what': 'Formula 3 (the application’s): I1, the Debye-Hückel A of the temperature; I2, fresh water ionic '
                'strength (the conductivity at 25 °C or the salinity, not below the hardness and alkalinity or the '
                'alkalinity) with Davies activities up to 1 permil, the seawater constants from 5, blended between. '
                'Beside formula 1 (golden v1).',
        'core': {'version': n.version(), 'formula_version': n.formula_version(), 'core_hash': n.core_hash()},
        'recorder_sha256': hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        'blocks': {name: {'records': count, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                   for name, (count, data) in encoded.items()},
    }


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    encoded = {name: (len(records), encode(records)) for name, records in record_all().items()}
    for name, (_count, data) in encoded.items():
        (out / f'{name}.jsonl.gz').write_bytes(data)
    (out / 'manifest.json').write_text(json.dumps(manifest(encoded), indent=2, sort_keys=True) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'chemcore' / 'golden' / 'v3')
