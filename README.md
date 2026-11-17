# liberta-dados

Quanto valem em 17/11/2026 R$ 100 mil aplicados em 17/11/2013 em CDI, Ibovespa, Petrobras (PETR4), S&P 500, Nvidia, Take-Two, bitcoin, dólar, Brent e gasolina, contra o IPCA.

- Página: https://guivaraschinalves.github.io/liberta-dados/ (três gráficos para o Instagram)
- Gráficos em `cards/`: 3 gráficos × 4 tamanhos (4:5, 1:1, stories 9:16, 16:9) × PNG, JPG e PDF, gerados por `scripts/cards.sh` a partir de `cards.html`
- Planilha: [`dados/liberta-dados.xlsx`](dados/liberta-dados.xlsx) (as colunas calculadas são fórmulas; mude o capital em `B3`)
- Tabela em texto: [`dados/comparacao.csv`](dados/comparacao.csv)
- Séries temporais: [`dados/serie-mensal.csv`](dados/serie-mensal.csv) (R$ 100 mil mês a mês), [`dados/serie-mensal-descontada-ipca.csv`](dados/serie-mensal-descontada-ipca.csv) (em reais de 2013) e [`dados/serie-diaria.csv`](dados/serie-diaria.csv) (preços originais)

`python3 scripts/gerar.py` baixa tudo de fonte pública (Banco Central, IBGE, ANP, Yahoo Finance, CoinMetrics) e refaz os três arquivos de `dados/`. Precisa de `openpyxl`. As regras de data, câmbio, desdobramento e proventos estão na aba "Notas e fontes" da planilha e no fim da página.
