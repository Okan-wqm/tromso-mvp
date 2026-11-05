"""The one door to the water-chemistry core, chemcore (Rust, built into the runner's image: README, chemcore).
Only this module imports it (farm/tests/test_native.py checks the whole checkout); the chemistry modules call
through here. There is no fallback: without the module this import fails, and so does the server's start.

`expected()` reads chemcore/EXPECTED, which chemcore/scripts/gen_expected.sh writes from the built module and
which is committed with the source; the start check core.E001 (core/checks.py) refuses a build that differs."""
from pathlib import Path

import chemcore

if not hasattr(chemcore, 'core_hash'):
    # The checkout's chemcore/ directory imports as an empty namespace package when the wheel is missing.
    raise ImportError('The water-chemistry core (chemcore) is not installed: only its source directory was found '
                      f'({list(getattr(chemcore, "__path__", []))}). Build the image (docker/testrunner.Dockerfile).')

EXPECTED = Path(__file__).resolve().parent.parent.parent / 'chemcore' / 'EXPECTED'
FIELDS = ('version', 'formula_version', 'core_hash')


def version():
    return chemcore.version()


def formula_version():
    return chemcore.formula_version()


def core_hash():
    return chemcore.core_hash()


def expected():
    """{field: value} of chemcore/EXPECTED; ValueError when a line is not "name value" or a field is missing."""
    found = {}
    for number, line in enumerate(EXPECTED.read_text(encoding='utf-8').splitlines(), start=1):
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2 or parts[0] not in FIELDS:
            raise ValueError(f'line {number}: not "name value" with a name of {", ".join(FIELDS)}')
        found[parts[0]] = parts[1]
    missing = [field for field in FIELDS if field not in found]
    if missing:
        raise ValueError(f'missing {", ".join(missing)}')
    return found


def handshake_problems():
    """What differs between the installed core and chemcore/EXPECTED, as sentences; [] when they agree."""
    try:
        wanted = expected()
    except (OSError, ValueError) as error:
        return [f'chemcore/EXPECTED cannot be read: {error}']
    installed = {'version': version(), 'formula_version': str(formula_version()), 'core_hash': core_hash()}
    return [f'{field}: installed {installed[field]}, expected {wanted[field]}'
            for field in FIELDS if installed[field] != wanted[field]]
