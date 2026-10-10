#!/bin/sh
set -eu
task_backup_dir=${1:?Usage: ./scripts/backup.sh /absolute/backup/directory}
case "$task_backup_dir" in /*) ;; *) echo "Provide an absolute directory" >&2; exit 1;; esac
mkdir -p "$task_backup_dir"
chmod 700 "$task_backup_dir"
task_backup_name="learning-$(date -u +%Y%m%d-%H%M%S).tar.gz"
docker compose stop app
trap 'docker compose start app >/dev/null' EXIT HUP INT TERM
docker compose run --rm --no-deps --user 0 --entrypoint tar \
  -v "$task_backup_dir:/backup" app -czf "/backup/$task_backup_name" -C /data .
chmod 600 "$task_backup_dir/$task_backup_name"
echo "$task_backup_dir/$task_backup_name"
