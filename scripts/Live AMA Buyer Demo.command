#!/bin/zsh
set -eu
buyer_cli="$(command -v codex || true)"
if [[ -z "$buyer_cli" ]]; then
  buyer_cli="/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
fi
curl --fail --silent http://127.0.0.1:8000/health >/dev/null
cd /private/tmp
exec "$buyer_cli" exec --ignore-user-config --ephemeral --skip-git-repo-check --sandbox read-only \
  -c 'mcp_servers.tollgate.url="http://127.0.0.1:8000/mcp"' \
  'Use only the Toll Gate MCP search_catalog tool. Search for inference caching. In English, give the title, price per read, and license for the rollout checklist, then one sentence about why a buyer might choose it based on its public abstract. Do not purchase or fetch the paid text. If the tool fails, report that.'
