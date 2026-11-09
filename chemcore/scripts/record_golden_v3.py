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
farm/tests/test_golden_v3.py holds the core to them exactly. Standard library and farm.water.native only."""
import gzip
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FORMAT = 1
TEMPERATURES = (2.0, 8.0, 12.0, 18.0, 25.0, 30.0)
SALINITIES = (0.0, 0.5, 1.0, 2.0, 3.0, 4.99, 5.0, 10.0, 35.0)
PHS = (6.5, 7.0, 7.5, 8.0, 8.5)
ALKALINITIES = (20.0, 80.0, 200.0)                    # mg/L as CaCO3
IONS = ({}, {'conductivity_25_us_cm': 50.0}, {'conductivity_25_us_cm': 300.0}, {'conductivity_25_us_cm': 1000.0},
        {'conductivity_25_us_cm': 3000.0}, {'hardness_mg_l': 50.0}, {'hardness_mg_l': 300.0})
LIMITS = {'nh3_n_mg_l': 0.0103, 'co2_mg_l': 15.0, 'h2s_ug_l': 2.0, 'alkalinity_low_mg_l': 50.0,
          'alkalinity_high_mg_l': 150.0}
ANALYSIS_KEYS = ('co2_mg_l', 'co2', 'nh3_n_mg_l', 'nh3', 'safe_tan_mg_l', 'h2s_ug_l', 'h2s', 'dic', 'target_dic',
                 'oxygen_solubility_mg_l', 'oxygen_saturation_pct', 'nh3_share_pct', 'h2s_share_pct',
                 'co2_corrected_mg_l', 'co2_basis', 'nh3_corrected_n_mg_l', 'nh3_basis')


def native():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from farm.water import native as found
    return found


def outputs(eq, alkalinity_mg_l, native_):
    """The constants (the pH offset among them) and, at each pH, the CO2 (mg/L) and the NH3 share."""
    meq = alkalinity_mg_l / native_.MG_CACO3_PER_MEQ
    return {'constants': dict(zip(native_.Equilibria.fields, eq.values())),
            'provenance': {'formula': eq.formula, 'ionic_strength': eq.ionic_strength, 'source': eq.strength_source,
                           'sea_weight': eq.sea_weight, 'warnings': eq.warnings},
            'at_ph': [{'ph': ph, 'co2_mg_l': eq.co2(eq.dic(meq, ph), ph) * native_.MG_CO2_PER_MMOL,
                       'co2_judged_mg_l': eq.co2_judged(meq, ph)[0] * native_.MG_CO2_PER_MMOL,
                       'nh3_share': eq.nh3_share(ph), 'nh3_share_corrected': eq.nh3_share_corrected(ph)}
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
