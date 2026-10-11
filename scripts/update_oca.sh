#!/bin/bash
# Actualiza las copias de módulos OCA en third_party/oca a los commits indicados.
# Uso: edite los SHA, ejecute el script, pruebe la instalación y actualice
# third_party/oca/README.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/third_party/oca"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# repo  sha  módulos...
SOURCES=(
  "account-financial-reporting 0078bc03f234d1caa8b9f40324678ce9dbed2a72 account_financial_report account_tax_balance"
  "mis-builder 7d519f31e1a553d7a5499571a9146f7e3ea49ea4 mis_builder"
  "account-financial-tools ddcabb93373382148826f97bf9935424d03ddea5 account_asset_management account_fiscal_year"
  "reporting-engine b9e8c6cdd2d106614eddaf81bd78f487ae35db45 report_xlsx report_xlsx_helper"
  "server-ux f2485eef1437b7fd57e3d44a61537420bbf1b281 date_range"
)

for line in "${SOURCES[@]}"; do
  read -r repo sha modules <<<"$line"
  git -C "$WORK" init -q "$repo"
  git -C "$WORK/$repo" fetch -q --depth 1 "https://github.com/OCA/$repo" "$sha"
  git -C "$WORK/$repo" checkout -q FETCH_HEAD
  for module in $modules; do
    rm -rf "${DEST:?}/$module"
    cp -a "$WORK/$repo/$module" "$DEST/"
  done
done
find "$DEST" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "Listo. Revise 'git diff --stat third_party/oca' y pruebe la instalación."
