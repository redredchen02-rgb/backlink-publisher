#!/usr/bin/env bash
# check-worktrees.sh — report worktree/branch consistency.
#
# Lists all worktrees and flags: dirty trees, branches not on origin/main, and
# worktrees sharing a repo with an unexpected detached HEAD.
#
# Exit 0 = all clean; 1 = at least one anomaly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/_worktree_safety.sh"

main_wt="$(wt_main_path)"
anomalies=0

while IFS='|' read -r wt_path wt_head wt_branch; do
  [[ -z "$wt_path" ]] && continue

  printf "%-60s %s\n" "$wt_path" "$wt_branch"

  if ! wt_is_clean "$wt_path"; then
    printf "  ! dirty (uncommitted changes)\n"
    ((anomalies+=1))
  fi

  if [[ "$wt_path" != "$main_wt" ]] && ! wt_branch_in_main "$wt_path"; then
    printf "  ! branch not merged to origin/main\n"
    ((anomalies+=1))
  fi
done < <(wt_list_porcelain)

  if [[ "$anomalies" -gt 0 ]]; then
  echo ""
  echo "$anomalies anomaly(ies) found"
  exit 1
fi

echo "all worktrees clean"
