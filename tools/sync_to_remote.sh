#!/usr/bin/env bash
# Sync the migrator source to a remote host without repositories or secrets.

set -euo pipefail

ssh_port=${REMOTE_SSH_PORT:-22}

while getopts ":p:" option; do
  case "$option" in
    p) ssh_port=$OPTARG ;;
    *)
      echo "Usage: $0 [-p ssh-port] user@remote-host [destination-path]" >&2
      exit 2
      ;;
  esac
done

shift $((OPTIND - 1))

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 [-p ssh-port] user@remote-host [destination-path]" >&2
  echo "Example: $0 -p 2222 deploy@example.com /apps/gitlab-migrator" >&2
  exit 2
fi

remote_host=$1
remote_path=${2:-/apps/gitlab-migrator}
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

ssh_command=(ssh)

ssh_command+=(-p "$ssh_port")

if [[ -n ${REMOTE_SSH_KEY:-} ]]; then
  ssh_command+=(-i "$REMOTE_SSH_KEY")
fi

rsync \
  --archive \
  --compress \
  --human-readable \
  --progress \
  --exclude '/workspace/' \
  --exclude '/keys/' \
  --exclude '/.venv/' \
  --exclude '/.env' \
  --exclude '/__pycache__/' \
  --exclude '/output/' \
  --exclude '*.pyc' \
  -e "${ssh_command[*]}" \
  "$project_root/" \
  "$remote_host:$remote_path/"
