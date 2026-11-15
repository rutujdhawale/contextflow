#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HYDRADB_ROOT="${HYDRADB_ROOT:-$(cd "$ROOT/../hydradb" && pwd)}"
STORE="${HYDRADB_STORE:-$HYDRADB_ROOT/.hydradb/store}"
CACHE="${HYDRADB_CACHE:-$HYDRADB_ROOT/.hydradb/cache}"
LAGRAPH_PREFIX="${HYDRADB_LAGRAPH_PREFIX:-$HYDRADB_ROOT/.hydradb/lagraph}"

mkdir -p "$STORE" "$CACHE"
printf '%s\n' "${GRAPH_AUTH_TOKEN:-local-development-token-32-bytes}" \
  > "${GRAPH_AUTH_TOKEN_FILE:-$HYDRADB_ROOT/.hydradb/auth-token}"

if [[ ! -f "$LAGRAPH_PREFIX/lib/liblagraph.a" ]]; then
  printf 'LAGraph is not installed; building the pinned local dependency...\n' >&2
  bash "$HYDRADB_ROOT/scripts/install_lagraph.sh" "$LAGRAPH_PREFIX"
fi

export LAGRAPH_LIB_DIR="${LAGRAPH_LIB_DIR:-$LAGRAPH_PREFIX/lib}"

export CLOUD_PROVIDER="${CLOUD_PROVIDER:-local}"
export LOCAL_PATH="$STORE"
export GRAPH_NAMESPACE="${GRAPH_NAMESPACE:-default}"
export GRAPH_ID="${GRAPH_ID:-default}"
export GRAPH_CELL_ID="${GRAPH_CELL_ID:-cell-0}"
export GRAPH_CELLS="${GRAPH_CELLS:-cell-0}"
export GRAPH_NODE_ID="${GRAPH_NODE_ID:-node-0}"
export GRAPH_BOLT_NODE_ADDRESSES="${GRAPH_BOLT_NODE_ADDRESSES:-node-0=127.0.0.1:7687}"
export GRAPH_ADVERTISED_BOLT_ADDR="${GRAPH_ADVERTISED_BOLT_ADDR:-127.0.0.1:7687}"
export GRAPH_DATA_CACHE_DIR="$CACHE"
export GRAPH_AUTH_TOKEN_FILE="${GRAPH_AUTH_TOKEN_FILE:-$HYDRADB_ROOT/.hydradb/auth-token}"
export GRAPH_ALLOW_PLAINTEXT="${GRAPH_ALLOW_PLAINTEXT:-true}"
export GRAPH_CYPHER_ENGINE=datafusion
export RUST_MIN_STACK="${RUST_MIN_STACK:-33554432}"

cd "$HYDRADB_ROOT"
just build-datafusion-node
exec target/debug/graph-node
