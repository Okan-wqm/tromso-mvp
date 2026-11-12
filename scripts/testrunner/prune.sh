#!/usr/bin/env bash
# Removes the test runner's old image tags (README, Tests).
#
#   scripts/testrunner/prune.sh             removes them, and says what it removed and what it kept and why
#   scripts/testrunner/prune.sh --dry-run   removes nothing: says what it would remove
#
# scripts/testrunner/image.sh names the test runner's image by a hash of everything it is built from, so every change
# to the requirements, to docker/ or to chemcore/ builds a new tag (balik-testrunner-chemcore:req-<hash>, some 400 MB)
# and nothing removed the old ones: they filled the disk Docker lives on. This removes every req-* tag of that
# repository except:
#   (a) the tag of every live git worktree of this repository (`git worktree list`; that tree's own
#       scripts/testrunner/image.sh says its tag, so a tree on another branch keeps the image its own files ask for);
#   (b) a tag whose image a container uses, running or stopped;
#   (c) a tag made within the last 24 hours (KEEP_HOURS): a build that is running, a tree that was just removed.
# It removes tags only (`docker rmi <tag>`, never --force): the layers go when no other tag and no container holds
# them. It touches nothing but the req-* tags of that one repository: no other image, no container, no volume, no
# network, and it never prunes. Needs bash, git, docker and GNU date (Git Bash, Linux).
#
# PRUNE_REPOSITORY names another repository to prune (the script's own check uses a throwaway one); the worktrees' tags
# are of the real one, so rule (a) keeps nothing there.
set -euo pipefail
cd "$(dirname "$0")/../.."
export MSYS_NO_PATHCONV=1

dry=0
case "${1:-}" in
  '') ;;
  --dry-run) dry=1 ;;
  *) echo "usage: scripts/testrunner/prune.sh [--dry-run]" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "usage: scripts/testrunner/prune.sh [--dry-run]" >&2; exit 2; }
KEEP_HOURS=${KEEP_HOURS:-24}
case "$KEEP_HOURS" in ''|*[!0-9]*) echo "KEEP_HOURS must be a whole number of hours" >&2; exit 2 ;; esac

own=$(sh scripts/testrunner/image.sh | sed -n 's/^tag=//p')
REPOSITORY=${PRUNE_REPOSITORY:-${own%%:*}}

# (a) the tag each live worktree asks for
declare -A of_tree=()
while IFS= read -r tree; do
  if [ -f "$tree/scripts/testrunner/image.sh" ]; then
    tag=$(sh "$tree/scripts/testrunner/image.sh" 2>/dev/null | sed -n 's/^tag=//p') || tag=
    if [ -n "$tag" ]; then
      of_tree[$tag]="${of_tree[$tag]:+${of_tree[$tag]}, }$tree"
    else
      echo "note: $tree: its scripts/testrunner/image.sh named no tag"
    fi
  else
    echo "note: $tree: no scripts/testrunner/image.sh (a tree from before it, or one that is gone): no tag kept for it"
  fi
done < <(git worktree list --porcelain | sed -n 's/^worktree //p')

# (b) the images containers use, by id (a container can be made from another name of the same image)
declare -A used=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  used[${line%% *}]="${used[${line%% *}]:+${used[${line%% *}]}, }${line#* }"
done < <(docker ps -aq | xargs -r docker inspect --format '{{.Image}} {{.Name}}' | sed 's# /# #')

now=$(date +%s)
removed=0 kept=0 failed=0
while IFS= read -r tag; do
  [ -n "$tag" ] || continue
  id=$(docker image inspect --format '{{.Id}}' "$tag")
  # when the tag was made (LastTagTime; an image store that does not keep it says year 1) or the image built: the later
  made=0
  for stamp in $(docker image inspect --format '{{.Created}} {{if .Metadata}}{{json .Metadata.LastTagTime}}{{end}}' "$tag" \
                 | tr -d '"'); do
    seconds=$(date -d "$stamp" +%s 2>/dev/null) || continue
    [ "$seconds" -gt "$made" ] && made=$seconds
  done
  hours=$(( (now - made) / 3600 ))
  why=
  if [ -n "${of_tree[$tag]:-}" ]; then
    why="the tag of the worktree ${of_tree[$tag]}"
  elif [ -n "${used[$id]:-}" ]; then
    why="a container uses its image (${used[$id]})"
  elif [ "$made" -eq 0 ]; then
    why="its age could not be read"
  elif [ "$hours" -lt "$KEEP_HOURS" ]; then
    why="made $hours h ago, less than $KEEP_HOURS h"
  fi
  if [ -n "$why" ]; then
    echo "kept     $tag: $why"
    kept=$((kept + 1))
  elif [ "$dry" = 1 ]; then
    echo "would remove $tag: made $hours h ago, no worktree's tag, no container uses it"
    removed=$((removed + 1))
  elif docker rmi "$tag" >/dev/null 2>&1; then
    echo "removed  $tag: made $hours h ago, no worktree's tag, no container uses it"
    removed=$((removed + 1))
  else
    echo "kept     $tag: docker refused to remove it (in use after all?)"
    failed=$((failed + 1))
  fi
done < <(docker images --format '{{.Repository}}:{{.Tag}}' "$REPOSITORY" | grep -E "^${REPOSITORY}:req-" | LC_ALL=C sort || true)

if [ "$dry" = 1 ]; then
  echo "scripts/testrunner/prune.sh --dry-run: $REPOSITORY: would remove $removed, keep $kept; nothing was removed"
else
  echo "scripts/testrunner/prune.sh: $REPOSITORY: removed $removed, kept $((kept + failed))"
fi
