#!/usr/bin/env bash
#
# Rebuild everything that derives from the meeting notes.
#
# Replacing the Markdown export changes three things, not one: the Neo4j graph,
# the search data the MCP server and CLI read, and the sanitized snapshot the
# dashboard serves. This runs all three in the right order so you do not have to
# remember which is which.
#
#   ./scripts/refresh.sh              refresh everything
#   ./scripts/refresh.sh --check      report what is stale, change nothing
#   ./scripts/refresh.sh --no-search  skip the search indexes
#   ./scripts/refresh.sh --force      re-embed every node, not only changed ones
#   ./scripts/refresh.sh --watch      re-run on every change to the notes
#
# Everything here is incremental. CocoIndex re-extracts only the meeting
# sections whose text changed, and the index builder re-embeds only the nodes
# whose indexed text changed, so a refresh after one edited meeting is quick.

set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

CHECK=0
FORCE=0
WATCH=0
SEARCH=1
for arg in "$@"; do
  case "$arg" in
    --check)      CHECK=1 ;;
    --force)      FORCE=1 ;;
    --watch)      WATCH=1 ;;
    --no-search)  SEARCH=0 ;;
    -h|--help)    sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "refresh: unknown option $arg" >&2; exit 2 ;;
  esac
done

if [ -x "$REPO/.venv/bin/python" ]; then
  PY="$REPO/.venv/bin/python"
  COCOINDEX="$REPO/.venv/bin/cocoindex"
else
  PY="$(command -v python3)"
  COCOINDEX="$(command -v cocoindex || true)"
fi
[ -n "$COCOINDEX" ] || { echo "refresh: cocoindex is not installed. Run: pip install -e '.[dev]'" >&2; exit 1; }

# Point at the source tree explicitly instead of trusting the editable install.
# `pip install -e .` writes a .pth file that some environments stop honouring,
# and this script should not be the thing that breaks when that happens.
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"

# .env is the one place NEO4J_* and SEARCH_EMBEDDING_MODEL live. Read line by
# line rather than sourcing it: values like `Form Responses 1` are unquoted in
# .env.example, and `source` would try to run them.
if [ -f "$REPO/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|'#'*) continue ;;
      *=*) key=${line%%=*}; value=${line#*=}
           case "$key" in *[!A-Za-z0-9_]*) continue ;; esac
           export "$key=$value" ;;
    esac
  done < "$REPO/.env"
fi

NOTES_DIR="${MEETING_NOTES_DIR:-./data/meeting_notes}"
SNAPSHOT="web/public/data/graph.json"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }

# --------------------------------------------------------------------------- #

check_neo4j() {
  if ! "$PY" - <<'PYEOF' 2>/dev/null
import os, sys
from neo4j import GraphDatabase
uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "scipyindia"))
try:
    driver = GraphDatabase.driver(uri, auth=auth, connection_timeout=4)
    with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
        s.run("RETURN 1").consume()
    driver.close()
except Exception:
    sys.exit(1)
PYEOF
  then
    echo "refresh: cannot reach Neo4j at ${NEO4J_URI:-bolt://localhost:7687}." >&2
    echo "         Start it with:  docker compose up -d --wait" >&2
    exit 1
  fi
}

graph_counts() {
  "$PY" - <<'PYEOF'
import json, os
from neo4j import GraphDatabase
driver = GraphDatabase.driver(
    os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
    auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "scipyindia")),
)
with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
    counts = {r["l"]: r["c"] for r in s.run(
        "MATCH (n) WHERE NOT n:GraphBuild RETURN labels(n)[0] AS l, count(*) AS c")}
    counts["OpenTasks"] = s.run(
        "MATCH (t:Task) WHERE t.status IN ['open','in_progress','blocked','unknown'] "
        "RETURN count(t) AS c").single()["c"]
driver.close()
print(json.dumps(counts, sort_keys=True))
PYEOF
}

describe_change() {
  "$PY" - "$1" "$2" <<'PYEOF'
import json, sys
before, after = json.loads(sys.argv[1]), json.loads(sys.argv[2])
moved = {k: (before.get(k, 0), v) for k, v in after.items() if before.get(k, 0) != v}
for gone in set(before) - set(after):
    moved[gone] = (before[gone], 0)
if not moved:
    print("  the graph is unchanged")
else:
    for key in sorted(moved):
        was, now = moved[key]
        print(f"  {key}: {was} -> {now}")
PYEOF
}

# --------------------------------------------------------------------------- #

run_once() {
  check_neo4j

  say "Notes"
  find "$NOTES_DIR" -type f \( -name '*.md' -o -name '*.markdown' -o -name '*.txt' \) \
    -exec sh -c 'printf "  %s  (modified %s)\n" "$1" "$(date -r "$1" "+%Y-%m-%d %H:%M")"' _ {} \;

  if [ "$CHECK" = 1 ]; then
    say "Checking (nothing will be written)"
    "$COCOINDEX" -d src update scipy_india_kg.main >/dev/null 2>&1 || true
    "$PY" scripts/build_search_indexes.py --status 2>/dev/null | sed 's/^/  /'
    if "$PY" scripts/export_public_snapshot.py --check >/dev/null 2>&1; then
      note "$SNAPSHOT is up to date"
    else
      note "$SNAPSHOT is STALE. Run ./scripts/refresh.sh"
      return 1
    fi
    return 0
  fi

  local before after
  before="$(graph_counts)"

  say "1/3  Graph"
  "$COCOINDEX" -d src update scipy_india_kg.main 2>&1 \
    | grep -E '^(✅|❌|⚠️)' | sed 's/^/  /' || true

  after="$(graph_counts)"
  describe_change "$before" "$after"

  if [ "$SEARCH" = 1 ]; then
    say "2/3  Search indexes"
    local flags="--embeddings"
    [ "$FORCE" = 1 ] && flags="$flags --force"
    if [ -z "${SEARCH_EMBEDDING_MODEL:-}" ]; then
      note "SEARCH_EMBEDDING_MODEL is not set, so full text only."
      note "Set it in .env to turn on hybrid retrieval."
      flags=""
    fi
    # shellcheck disable=SC2086
    "$PY" scripts/build_search_indexes.py $flags 2>/dev/null \
      | grep -E 'full-text|vector|current|Embedded|Every' | sed 's/^/  /' || true
  else
    say "2/3  Search indexes (skipped)"
  fi

  say "3/3  Dashboard snapshot"
  "$PY" scripts/export_public_snapshot.py 2>/dev/null | sed 's/^/  /'

  # The exporter works from an allowlist, so a leak needs a mistake in that
  # allowlist. These tests read the file that was just written and check.
  if "$PY" -m pytest tests/test_public_snapshot.py -q >/dev/null 2>&1; then
    note "privacy checks passed"
  else
    echo "  PRIVACY CHECKS FAILED on the snapshot just written." >&2
    echo "  Run: pytest tests/test_public_snapshot.py -q" >&2
    return 1
  fi

  say "Done"
  note "Dashboard data: $SNAPSHOT"
  note "Serve it with:  python -m http.server 8000 --directory web/public"
}

# --------------------------------------------------------------------------- #

if [ "$WATCH" = 0 ]; then
  run_once
  exit $?
fi

# --watch: the dev loop that keeps *everything* current, not only the graph.
# `cocoindex update -L` keeps Neo4j fresh but never touches the snapshot or the
# embeddings, so the dashboard would go stale while you watched it.
command -v fswatch >/dev/null 2>&1 || {
  echo "refresh: --watch needs fswatch (brew install fswatch)." >&2
  echo "         Without it, re-run ./scripts/refresh.sh after each edit." >&2
  exit 1
}
echo "Watching $NOTES_DIR. Every change refreshes the graph, search and snapshot."
echo "Ctrl-C to stop."
run_once || true
fswatch -o "$NOTES_DIR" | while read -r _; do
  echo
  echo "--- change detected $(date '+%H:%M:%S') ---"
  run_once || true
done
