#!/bin/bash
# Zet de nieuwste versie van de PWA live op GitHub Pages.
# Stempelt alle assets met de commit-hash zodat browsers nooit een oude
# app.js bij een nieuwe index.html kunnen mengen (cache-skew).
set -euo pipefail
cd "$(dirname "$0")"

STAMP=$(git rev-parse --short HEAD)
sed -E -i '' "s/(styles\.css|config\.js|app\.js|vendor\/supabase\.js)\?v=[A-Za-z0-9]*/\1?v=${STAMP}/g" pwa/index.html
if ! git diff --quiet pwa/index.html; then
  git add pwa/index.html
  git -c user.name="Remco Kuilman" -c user.email="r.kuilman@aviclaim.nl" commit -q -m "cache-stempel ${STAMP}"
fi

git branch -D gh-pages 2>/dev/null || true
git subtree split --prefix pwa -b gh-pages
git push -f origin gh-pages
git push -q origin main
git branch -D gh-pages
echo "Live over ~1 minuut op https://remco-goat.github.io/pa-annabel/"
