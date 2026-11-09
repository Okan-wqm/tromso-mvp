#!/bin/sh
# The test runner's image, defined once for scripts/test.sh (which builds it when missing) and CI (which builds it with
# its layers cached, then runs scripts/test.sh, which finds it): the Dockerfile, the stage, the build context (the
# checkout, narrowed by .dockerignore) and the tag, a hash of everything the image is built from (the requirements, the
# docker/ files, chemcore/ but its build output).
#   sh scripts/testrunner/image.sh          prints file=, target=, context= and tag=, one per line (GITHUB_OUTPUT's form)
#   sh scripts/testrunner/image.sh build    builds it unless an image of that tag exists, then prints the tag
set -eu
cd "$(dirname "$0")/../.."
file=docker/testrunner.Dockerfile
target=tests
hash=$( { cat requirements.txt .dockerignore docker/* scripts/testrunner/requirements.txt;
          find chemcore -type f ! -path 'chemcore/target/*' | LC_ALL=C sort | xargs cat; } | sha256sum | cut -c1-12)
tag=balik-testrunner-chemcore:req-$hash

case "${1:-}" in
  '')
    printf 'file=%s\ntarget=%s\ncontext=.\ntag=%s\n' "$file" "$target" "$tag" ;;
  build)
    if ! docker image inspect "$tag" >/dev/null 2>&1; then
      docker build -q -f "$file" --target "$target" -t "$tag" . >/dev/null
    fi
    echo "$tag" ;;
  *)
    echo "usage: sh scripts/testrunner/image.sh [build]" >&2
    exit 2 ;;
esac
