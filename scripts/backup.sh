#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
task_backup_dir=${1:?Usage: ./scripts/backup.sh /absolute/backup/directory}
case "$task_backup_dir" in /*) ;; *) echo "Provide an absolute directory" >&2; exit 1;; esac
mkdir -p "$task_backup_dir"
chmod 700 "$task_backup_dir"
task_backup_name="learning-$(date -u +%Y%m%d-%H%M%S)-$$.tar.gz"
task_backup_partial="$task_backup_dir/.$task_backup_name.partial"
docker compose stop app
trap 'docker compose start app >/dev/null; rm -f "$task_backup_partial"' EXIT HUP INT TERM
docker compose run -T --interactive=false --rm --no-deps --user 10001 \
  --label traefik.enable=false --entrypoint tar \
  app -czf - -C /data . > "$task_backup_partial"
mv "$task_backup_partial" "$task_backup_dir/$task_backup_name"
chmod 600 "$task_backup_dir/$task_backup_name"
echo "$task_backup_dir/$task_backup_name"
