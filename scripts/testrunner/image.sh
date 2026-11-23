#!/bin/sh
# The test runner's image, defined once for scripts/test.sh (which builds it when missing) and CI (which builds it with
# its layers cached, then runs scripts/test.sh, which finds it): the Dockerfile, the stage, the build context (the
# checkout, narrowed by .dockerignore) and the tag, a hash of everything the image is built from (the requirements, the
# docker/ files, chemcore/ but its build output).
#   sh scripts/testrunner/image.sh          prints file=, target=, context= and tag=, one per line (GITHUB_OUTPUT's form)
#   sh scripts/testrunner/image.sh build    builds it unless an image of that tag exists, then prints the tag
#
# The files of docker/ and chemcore/ that the tag is hashed from are the ones git tracks (`built_from`): what a build or
# a run leaves in a tree (chemcore/target/, the __pycache__ a script of chemcore/scripts leaves beside it) is not in the
# image's name. A worktree that has run its tests and a clean checkout (CI) so ask for the same tag: before, the
# worktree asked for a tag of its own and built an image for it. A new file counts once git tracks it (`git add`). In
# a copy that is no git checkout (or lies inside another repository, where git tracks none of this) everything there
# is hashed but those leftovers, which gives a clean copy the same tag as its checkout.
set -eu
cd "$(dirname "$0")/../.."
file=docker/testrunner.Dockerfile
target=tests
built_from() {
  if [ -z "$(git rev-parse --show-prefix 2>/dev/null || echo outside)" ] \
     && git ls-files --error-unmatch scripts/testrunner/image.sh >/dev/null 2>&1; then
    git ls-files -- "$1"
  else
    find "$1" -type f ! -path 'chemcore/target/*' ! -path '*/__pycache__/*'
  fi | LC_ALL=C sort
}
hash=$( { cat requirements.txt .dockerignore; built_from docker | xargs cat; cat scripts/testrunner/requirements.txt;
          built_from chemcore | xargs cat; } | sha256sum | cut -c1-12)
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
