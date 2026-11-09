"""Golden v3: I2, fresh water's ionic strength (chemcore/core/src/fresh.rs; chemcore/findings/B1.md, I2), recorded from
the core beside golden v1 and NOT used by the application until the owner decides (chemcore/findings/I2-comparison.md).

    docker run --rm -v "$PWD:/app" -w /app <runner image> python chemcore/scripts/record_golden_v3.py chemcore/golden/v3

Writes <out>/waters.jsonl.gz (one JSON object per line, keys sorted, floats as Python repr; gzip with mtime 0, so two
runs give the same bytes) and <out>/manifest.json. A water of the corpus: a temperature, a salinity, an
alkalinity and what is measured of its ions (nothing, a conductivity, a hardness), fresh, hard and brackish waters and
sea water (where v3 is v1). For each, v1's and v3's constants (Equilibria's fields), v3's ionic strength and its
source, and what the owner compares: at each of five pHs the CO2 (mg/L) at its alkalinity and the NH3 share of the TAN,
with the pH offset (free - NBS) among the constants. The values are the core's (bit for bit on every platform, `libm`), so
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
SALINITIES = (0.0, 0.5, 2.0, 4.99, 5.0, 10.0, 35.0)
PHS = (6.5, 7.0, 7.5, 8.0, 8.5)
ALKALINITIES = (20.0, 80.0, 200.0)                    # mg/L as CaCO3
IONS = ({}, {'conductivity_us_cm': 50.0}, {'conductivity_us_cm': 300.0}, {'conductivity_us_cm': 1000.0},
        {'conductivity_us_cm': 3000.0}, {'hardness_mg_l': 50.0}, {'hardness_mg_l': 300.0})


def native():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from farm.water import native as found
    return found


def outputs(eq, alkalinity_mg_l, native_):
    """The constants (the pH offset among them) and, at each pH, the CO2 (mg/L) and the NH3 share."""
    meq = alkalinity_mg_l / native_.MG_CACO3_PER_MEQ
    return {'constants': dict(zip(native_.Equilibria.fields, eq.values())),
            'at_ph': [{'ph': ph, 'co2_mg_l': eq.co2(eq.dic(meq, ph), ph) * native_.MG_CO2_PER_MMOL,
                       'nh3_share': eq.nh3_share(ph)} for ph in PHS]}


def record_all():
    """{block: [records]} of the corpus."""
    n = native()
    waters = []
    for temp_c in TEMPERATURES:
        for salinity in SALINITIES:
            for alkalinity in ALKALINITIES:
                for ions in IONS:
                    strength, source = n.fresh_ionic_strength(salinity, alkalinity, **ions)
                    v1 = n.equilibria(temp_c, salinity)
                    v3 = n.equilibria_v3(temp_c, salinity, alkalinity, **ions)
                    waters.append({'temp_c': temp_c, 'salinity': salinity, 'alkalinity_mg_l': alkalinity, 'ions': ions,
                                   'ionic_strength': strength, 'source': source, 'v1': outputs(v1, alkalinity, n),
                                   'v3': outputs(v3, alkalinity, n)})
    return {'waters': waters}


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
        'what': 'I2: fresh water ionic strength (conductivity, hardness and alkalinity, salinity, alkalinity) with '
                'Davies activities below a salinity of 5; v1 from 5 on. Not used by the application.',
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
