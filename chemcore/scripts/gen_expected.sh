#!/bin/sh
# Writes chemcore/EXPECTED from the BUILT module, never by hand: run it in the runner image after a change to
# chemcore (README, chemcore), then commit the file with the change.
#   docker run --rm -v "$PWD:/app" -w /app <runner image> sh chemcore/scripts/gen_expected.sh
set -eu
cd "$(dirname "$0")/.."
python3 - > EXPECTED <<'PY'
import chemcore
print('# The chemcore build the server accepts (Django check core.E001). Written by chemcore/scripts/gen_expected.sh')
print('# from the built module; never edited by hand.')
print('version', chemcore.version())
print('formula_version', chemcore.formula_version())
print('core_hash', chemcore.core_hash())
PY
cat EXPECTED
