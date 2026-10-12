#!/bin/sh
set -eu
task_semgrep_bin=${SEMGREP_BIN:-.venv-semgrep/bin/semgrep}
task_semgrep_dir=$(mktemp -d "${TMPDIR:-/tmp}/learning-semgrep.XXXXXX")
trap 'rm -rf "$task_semgrep_dir"' EXIT HUP INT TERM
export SEMGREP_SETTINGS_FILE="$task_semgrep_dir/settings.yml"
export SEMGREP_LOG_FILE="$task_semgrep_dir/semgrep.log"
if [ "$#" -eq 0 ]; then
  set -- backend/app frontend/src
fi
"$task_semgrep_bin" scan \
  --config p/python --config p/react --config p/typescript \
  --config p/security-audit \
  --metrics off --disable-version-check --error --strict \
  "$@"
