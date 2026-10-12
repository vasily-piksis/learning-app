#!/bin/sh
set -eu
task_python_bin=${PYTHON_BIN_DIR:-.venv/bin}
"$task_python_bin/ruff" check backend
"$task_python_bin/ruff" format --check backend
"$task_python_bin/bandit" -r backend/app -q
sh scripts/semgrep.sh
"$task_python_bin/pytest" -q
npm run lint --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend
