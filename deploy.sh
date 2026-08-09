#!/bin/bash
# Zet de nieuwste versie van de PWA live op GitHub Pages.
set -euo pipefail
cd "$(dirname "$0")"

git branch -D gh-pages 2>/dev/null || true
git subtree split --prefix pwa -b gh-pages
git push -f origin gh-pages
git branch -D gh-pages
echo "Live over ~1 minuut op https://remco-goat.github.io/pa-annabel/"
