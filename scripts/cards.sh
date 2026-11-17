#!/bin/bash
# Renderiza os 3 gráficos em 4 tamanhos (feed 4:5, quadrado 1:1, stories 9:16, 16:9),
# cada um em PNG, JPG e PDF: cards/card-N-<tamanho>.<ext>.
# Precisa da página servida em http://127.0.0.1:8790 (python3 -m http.server 8790), de um Chrome
# e de um Python com Pillow (PY) para o JPG.
set -e
CH=${CHROME:-$HOME/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome}
PY=${PY:-python3}
cd "$(dirname "$0")/.."
mkdir -p cards
for t in 4x5:1080:1350 1x1:1080:1080 9x16:1080:1920 16x9:1920:1080; do
  IFS=: read nome w h <<< "$t"
  for n in 1 2 3; do
    url="http://127.0.0.1:8790/cards.html?card=$n&w=$w&h=$h"
    base="cards/card-$n-$nome"
    "$CH" --headless=new --no-sandbox --hide-scrollbars --force-device-scale-factor=1 --virtual-time-budget=6000 \
      --window-size=$w,$h --screenshot="$base.png" "$url" 2>/dev/null
    "$CH" --headless=new --no-sandbox --virtual-time-budget=6000 --no-pdf-header-footer \
      --print-to-pdf="$base.pdf" "$url" 2>/dev/null
  done
done
"$PY" -c "
import glob
from PIL import Image
for f in glob.glob('cards/card-*.png'):
    Image.open(f).convert('RGB').save(f[:-4] + '.jpg', quality=92)
"
ls cards | wc -l
