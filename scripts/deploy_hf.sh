#!/bin/bash
# Pushes the last commit (backend only) to a Hugging Face Docker Space.
# Usage: bash scripts/deploy_hf.sh <hf-username>/<space-name>
# git asks for a username (your HF username) and a password (paste your HF write token).
set -e
SPACE="$1"
if [ -z "$SPACE" ]; then echo "Usage: bash scripts/deploy_hf.sh <hf-username>/<space-name>"; exit 1; fi
TMP=$(mktemp -d)
git archive HEAD | tar -x -C "$TMP"
rm -rf "$TMP/web" "$TMP/scripts"
cat > "$TMP/README.md" <<'MD'
---
title: Civic Agent API
emoji: 🏛️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---
Backend of Civic Agent (agent API + test portal + headless Chromium). The UI is deployed separately on Vercel.
MD
cd "$TMP"
git init -q -b main
git add .
git commit -qm "Deploy $(date '+%Y-%m-%d %H:%M')"
git push --force "https://huggingface.co/spaces/$SPACE" main
echo "Pushed. Build logs: https://huggingface.co/spaces/$SPACE (Logs tab)"
