#!/usr/bin/env bash
# One-shot installer + self-check for the crypto-perp-analysis skill.
# Usage:  bash install.sh            (installs into ~/.claude/skills/)
#         SKILLS_DIR=/path bash install.sh   (custom location)
set -euo pipefail

REPO="https://github.com/kim1232aa/crypto-perp-analysis.git"
DEST="${SKILLS_DIR:-$HOME/.claude/skills}/crypto-perp-analysis"

echo "→ installing to: $DEST"
mkdir -p "$(dirname "$DEST")"
if [ -d "$DEST/.git" ]; then
  echo "→ already present, pulling latest"; git -C "$DEST" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DEST"
fi

command -v python3 >/dev/null || { echo "✗ python3 not found"; exit 1; }

echo "→ self-check: analyze.py ETH 5m (needs network to OKX/Binance/Bybit)"
if python3 "$DEST/scripts/analyze.py" ETH 5m 2>/dev/null | grep -q "报告块"; then
  echo "✅ install OK — skill works, live data reachable."
  echo "   Try:  python3 $DEST/scripts/analyze.py BTC 15m"
  echo "   Claude Code users: restart the session to auto-discover the skill."
else
  echo "⚠️ installed, but self-check produced no 报告块."
  echo "   Likely exchanges are geo/network blocked. Retry with a proxy:"
  echo "   HTTPS_PROXY=http://<proxy>:<port> python3 $DEST/scripts/analyze.py ETH 5m"
fi
