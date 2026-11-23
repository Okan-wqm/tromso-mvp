"""Golden v4: formula 4, the application's since 2026-11-19 (the water-chemistry audit's consensus and the owner's
decision, Rule S; chemcore/core/src/formula4.rs), recorded from the core beside golden v3 (formula 3, kept by name).

    docker run --rm -v "$PWD:/app" -w /app <runner image> python chemcore/scripts/record_golden_v4.py chemcore/golden/v4

The corpus is golden v3's (chemcore/scripts/record_golden_v3.py: its temperatures, salinities, alkalinities, ions, pHs,
limits, phosphates and scale salinities, and the functions that write one water's outputs), so the two files compare
water by water: formula 4 changes the NBS step of the sea path (Millero 1986), K_NH4 (Clegg & Whitfield 1995) and the
judged NH3 and CO2 from 5 permil (the best estimate at the pH plus or minus 0.03), nothing else. Four blocks, as v3's:
`waters` (each water's formula 4 constants, provenance and, at five pHs, the CO2, the judged and best NH3 shares, the
safe-side share and log10 Omega), `analyses` (the whole analysis at pH 7.0 with a TAN, a sulfide and the limits),
`scales` (the NBS pH of five pHs given on each scale) and `phosphate`. Every record names formula 4 explicitly, never
the application's default, so a later formula leaves this file's bytes as they are. Gzip with mtime 0, keys sorted,
floats as Python repr: two runs give the same bytes; farm/tests/test_golden_v4.py holds the core to them exactly.
Standard library and farm.water.native only."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FORMAT = 1
FORMULA = 4


def v3():
    """The golden v3 recorder, whose corpus and record functions this one shares."""
    spec = importlib.util.spec_from_file_location('record_golden_v3', Path(__file__).resolve().parent / 'record_golden_v3.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_all():
    """{block: [records]} of the corpus, by formula 4."""
    base = v3()
    n = base.native()
    waters, analyses = [], []
    for temp_c in base.TEMPERATURES:
        for salinity in base.SALINITIES:
            for alkalinity in base.ALKALINITIES:
                for ions in base.IONS:
                    eq = n.water_equilibria(temp_c, salinity, alkalinity, **ions, formula=FORMULA)
                    waters.append({'temp_c': temp_c, 'salinity': salinity, 'alkalinity_mg_l': alkalinity, 'ions': ions,
                                   'v4': base.outputs(eq, alkalinity, n)})
                    found = n.analyse(temp_c, salinity, 7.0, alkalinity, tan_mg_l=0.5, total_sulfide_ug_l=2.0,
                                      oxygen_mg_l=10.0, formula=FORMULA, **ions, **base.LIMITS, target_ph=7.5,
                                      target_alkalinity_mg_l=100.0)
                    analyses.append({'temp_c': temp_c, 'salinity': salinity, 'alkalinity_mg_l': alkalinity, 'ions': ions,
                                     'v4': {key: found[key] for key in base.ANALYSIS_KEYS}})
    scales = []
    for temp_c in base.TEMPERATURES:
        for salinity in base.SCALE_SALINITIES:
            eq = n.water_equilibria(temp_c, salinity, formula=FORMULA)
            scales.append({'temp_c': temp_c, 'salinity': salinity, 'ph_offset': eq.ph_offset,
                           'nbs_of': {scale: [eq.ph_nbs(ph, scale) for ph in base.PHS] for scale in n.PH_SCALES}})
    phosphate = []
    for temp_c in base.TEMPERATURES:
        for salinity in base.PHOSPHATE_SALINITIES:
            for alkalinity in base.ALKALINITIES:
                for given in base.PHOSPHATES:
                    eq = n.water_equilibria(temp_c, salinity, alkalinity, phosphate_p_mg_l=given, formula=FORMULA)
                    meq = alkalinity / n.MG_CACO3_PER_MEQ
                    at_ph = []
                    for ph in base.PHS:
                        if not eq.possible(meq, ph):
                            at_ph.append({'ph': ph, 'impossible': True})
                            continue
                        dic = eq.dic(meq, ph)
                        at_ph.append({'ph': ph, 'isoline': list(eq.isoline(ph)), 'dic': dic,
                                      'co2_mg_l': eq.co2(dic, ph) * n.MG_CO2_PER_MMOL,
                                      'co2_judged_mg_l': eq.co2_judged(meq, ph)[0] * n.MG_CO2_PER_MMOL,
                                      'ph_after_base': eq.ph_at(dic, meq + 0.5)})
                    phosphate.append({'temp_c': temp_c, 'salinity': salinity, 'alkalinity_mg_l': alkalinity,
                                      'phosphate_p_mg_l': given,
                                      'constants': {'phosphate': eq.phosphate, 'k1p': eq.k1p, 'k2p': eq.k2p,
                                                    'k3p': eq.k3p},
                                      'at_ph': at_ph})
    return {'waters': waters, 'analyses': analyses, 'scales': scales, 'phosphate': phosphate}


def encode(records):
    return v3().encode(records)


def manifest(encoded):
    n = v3().native()
    return {
        'format': FORMAT, 'golden_version': 'v4', 'beside': 'v3',
        'what': 'Formula 4 (the application’s since 2026-11-19): formula 3 with the NBS step of Millero (1986, table 7: '
                '0.1306 + 0.00073 S at 25 °C, 0.75 of the bisulfate term’s temperature change), the K_NH4 of Clegg & '
                'Whitfield (1995, eq. 18) fresh to sea, and Rule S: from 5 permil the judged NH3 and CO2 are the best '
                'estimate at the pH plus and minus 0.03 (US EPA 1989), up to 1 permil formula 3’s ideal water, blended '
                'between. Golden v3’s corpus.',
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
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'chemcore' / 'golden' / 'v4')
