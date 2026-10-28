#!/usr/bin/env bash
# Concurrency is coordinated by one runner and SQLite, configured with workers.
set -euo pipefail
if [ "$#" -lt 1 ]; then
  echo "Usage: $0 CONFIG.yaml [DATASET.yaml] [additional run options]" >&2
  exit 2
fi
config="$1"
shift
dataset="data/[TerminalBenchVer]uuid_bash_agent_questions.yaml"
if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then
  dataset="$1"
  shift
fi
exec bbdevbox run "$dataset" --config "$config" "$@"
