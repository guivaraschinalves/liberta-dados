#!/bin/bash
# Renderiza os 3 gráficos (1080x1350) em cards/card-N.png.
# Precisa da página servida em http://127.0.0.1:8790 (python3 -m http.server 8790) e de um Chrome.
set -e
CH=${CHROME:-$HOME/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome}
cd "$(dirname "$0")/.."
for n in 1 2 3; do
  "$CH" --headless=new --no-sandbox --hide-scrollbars --force-device-scale-factor=1 --virtual-time-budget=6000 \
    --window-size=1080,1350 --screenshot="cards/card-$n.png" "http://127.0.0.1:8790/cards.html?card=$n" 2>/dev/null
done
ls -la cards
