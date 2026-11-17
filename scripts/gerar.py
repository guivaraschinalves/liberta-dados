"""R$ 100 mil em 17/11/2013 e quanto valem em 17/11/2026, ativo por ativo.

Baixa tudo de fonte pública e grava:
  dados/resumo.json        a tabela e as trajetórias que a página lê
  dados/comparacao.csv     a tabela em texto
  dados/liberta-dados.xlsx a planilha, com fórmulas nas colunas calculadas

Uso: python3 scripts/gerar.py [--cache]   (--cache reaproveita bruto/)
Precisa de openpyxl só para a planilha.
"""
import csv
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
BRUTO = RAIZ / "bruto"
DADOS = RAIZ / "dados"
CACHE = "--cache" in sys.argv

INICIO = dt.date(2013, 11, 17)
FIM = dt.date(2026, 11, 17)
CAPITAL = 100_000.0
ANOS = 13

UA = {"User-Agent": "Mozilla/5.0"}


def baixar(nome, url, cabecalho=None):
    """Grava url em bruto/nome; com --cache, usa o que já existe."""
    destino = BRUTO / nome
    if CACHE and destino.exists():
        return destino.read_bytes()
    for tentativa in range(4):
        try:
            req = urllib.request.Request(url, headers=cabecalho or {})
            with urllib.request.urlopen(req, timeout=90) as r:
                corpo = r.read()
            destino.write_bytes(corpo)
            return corpo
        except Exception as e:  # noqa: BLE001
            print(f"  {nome}: {e}; nova tentativa", file=sys.stderr)
            time.sleep(3 * (tentativa + 1))
    raise SystemExit(f"falhou: {url}")


def br(d):
    return d.strftime("%d/%m/%Y")


# --------------------------------------------------------------------------- fontes

def yahoo(simbolo):
    """Fechamentos diários (data local da bolsa). Devolve (fechamento, ajustado).

    O fechamento do Yahoo já vem corrigido por desdobramento (a Nvidia teve 4:1
    em 2021 e 10:1 em 2024); o ajustado também reinveste os proventos.
    O pregão de hoje só entra depois do fechamento, para não usar preço do meio
    do dia como se fosse o final.
    """
    p1 = int(dt.datetime(2013, 11, 1).timestamp())
    p2 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(simbolo)}"
           f"?period1={p1}&period2={p2}&interval=1d&events=split,div")
    r = json.loads(baixar(f"yahoo-{simbolo.strip('^').replace('=', '')}.json", url, UA))
    r = r["chart"]["result"][0]
    tz = ZoneInfo(r["meta"]["exchangeTimezoneName"])
    fecha_hoje = r["meta"].get("currentTradingPeriod", {}).get("regular", {}).get("end", 0)
    hoje = dt.datetime.now(tz).date()
    q = r["indicators"]["quote"][0]["close"]
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose") or q
    fech, ajus = {}, {}
    for i, t in enumerate(r["timestamp"]):
        d = dt.datetime.fromtimestamp(t, tz).date()
        if q[i] is None:
            continue
        if d == hoje and time.time() < fecha_hoje + 20 * 60:
            continue
        fech[d] = round(q[i], 4)
        ajus[d] = adj[i]
    splits = [(dt.datetime.fromtimestamp(int(k), tz).date().isoformat(), v["splitRatio"])
              for k, v in r.get("events", {}).get("splits", {}).items()]
    return fech, ajus, splits


def sgs(codigo):
    """Série diária do SGS em janelas de até 10 anos (limite do BC)."""
    serie = {}
    janelas = [("01/11/2013", "31/12/2019"), ("01/01/2020", br(dt.date.today()))]
    for k, (a, b) in enumerate(janelas):
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
               f"?formato=json&dataInicial={a}&dataFinal={b}")
        for x in json.loads(baixar(f"sgs{codigo}-{k}.json", url)):
            serie[dt.datetime.strptime(x["data"], "%d/%m/%Y").date()] = float(x["valor"])
    return serie


def ipca_indice():
    """Número-índice do IPCA (dez/1993 = 100), tabela 1737 do SIDRA."""
    url = "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/201310-209912"
    linhas = json.loads(baixar("sidra-1737.json", url))[1:]
    return {dt.date(int(x["D3C"][:4]), int(x["D3C"][4:]), 1): float(x["V"])
            for x in linhas if x["V"] not in ("...", "-", "")}


def bitcoin():
    """Preço de referência da CoinMetrics. O registro do dia D é o fim do dia D
    (0h UTC de D+1); o Yahoo só tem bitcoin a partir de set/2014."""
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           "?assets=btc&metrics=PriceUSD&start_time=2013-11-01&frequency=1d&page_size=10000")
    dados = json.loads(baixar("coinmetrics-btc.json", url))["data"]
    return {dt.date.fromisoformat(x["time"][:10]): float(x["PriceUSD"]) for x in dados}


def gasolina():
    """Preço médio de revenda da gasolina comum no Brasil, semanal (ANP).
    Chave: último dia da semana de pesquisa (sábado)."""
    import openpyxl
    url = ("https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/"
           "precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/semanal-brasil-desde-2013.xlsx")
    baixar("anp-semanal-brasil.xlsx", url, UA)
    wb = openpyxl.load_workbook(BRUTO / "anp-semanal-brasil.xlsx", read_only=True)
    serie, semanas = {}, {}
    for r in wb.worksheets[0].iter_rows(values_only=True):
        if len(r) > 5 and isinstance(r[2], str) and r[2].strip().upper() == "GASOLINA COMUM":
            fim = r[1].date()
            serie[fim] = float(r[5])
            semanas[fim] = r[0].date()
    return serie, semanas


# --------------------------------------------------------------------------- contas

def ultimo_ate(serie, d):
    datas = [x for x in serie if x <= d]
    if not datas:
        raise SystemExit(f"sem dado até {d}")
    return max(datas)


def main():
    BRUTO.mkdir(exist_ok=True)
    DADOS.mkdir(exist_ok=True)

    ptax = sgs(1)
    cdi = sgs(12)
    ipca = ipca_indice()
    btc = bitcoin()
    gas, gas_semana = gasolina()
    yh = {s: yahoo(s) for s in ["^BVSP", "PETR4.SA", "^GSPC", "^SP500TR", "NVDA", "TTWO", "BZ=F"]}

    # Datas finais efetivas
    def par(serie, ini=INICIO - dt.timedelta(days=1), fim=FIM):
        return ultimo_ate(serie, ini), ultimo_ate(serie, fim)

    def fx(d):
        return ptax[ultimo_ate(ptax, d)]

    ativos = []

    def add(**k):
        ativos.append(k)

    # CDI: aplicado no fechamento do último dia útil antes de 17/11/2013 (14/11,
    # porque 15/11 é feriado) e capitalizado dia a dia até a véspera de
    # 17/11/2026 — a taxa de cada dia rende até o dia útil seguinte.
    c0 = ultimo_ate(cdi, INICIO - dt.timedelta(days=1))
    dias = sorted(d for d in cdi if c0 <= d < FIM)
    fator, idx = 1.0, {c0: 100.0}
    for d in dias:
        fator *= 1 + cdi[d] / 100
        prox = min([x for x in cdi if x > d], default=FIM)
        idx[min(prox, FIM)] = 100 * fator
    add(id="cdi", nome="CDI (rentabilidade acumulada)", tipo="Investimento", moeda="BRL",
        unidade="índice, 14/11/2013 = 100", d0=c0, v0=100.0, d1=FIM, v1=100 * fator,
        dias_uteis=len(dias), serie=idx,
        fonte="Banco Central, SGS 12 (CDI diário), capitalizado dia a dia")

    for simb, id_, nome in [("^BVSP", "ibov", "Ibovespa"), ("PETR4.SA", "petr4", "Petrobras (PETR4)")]:
        f, a, sp = yh[simb]
        d0, d1 = par(f)
        add(id=id_, nome=nome, tipo="Investimento", moeda="BRL",
            unidade="pontos" if id_ == "ibov" else "R$ por ação", d0=d0, v0=f[d0], d1=d1, v1=f[d1],
            tr=(a[d1] / a[d0]) if id_ == "petr4" else None, serie=f, serie_tr=a if id_ == "petr4" else None,
            fonte="B3, via Yahoo Finance" + (" (fechamento e fechamento ajustado por proventos)" if id_ == "petr4" else ""))

    f, _, _ = yh["^GSPC"]
    ftr, _, _ = yh["^SP500TR"]
    d0, d1 = par(f)
    add(id="sp500", nome="S&P 500", tipo="Investimento", moeda="USD", unidade="pontos",
        d0=d0, v0=f[d0], d1=d1, v1=f[d1], tr=ftr[ultimo_ate(ftr, d1)] / ftr[ultimo_ate(ftr, d0)],
        serie=f, serie_tr=ftr, fonte="S&P Dow Jones Indices, via Yahoo Finance (^GSPC e ^SP500TR, com dividendos)")

    for simb, id_, nome in [("NVDA", "nvda", "Nvidia (NVDA)"),
                            ("TTWO", "ttwo", "Take-Two Interactive (TTWO)")]:
        f, a, sp = yh[simb]
        d0, d1 = par(f)
        add(id=id_, nome=nome, tipo="Investimento", moeda="USD", unidade="US$ por ação",
            d0=d0, v0=f[d0], d1=d1, v1=f[d1], tr=a[d1] / a[d0], serie=f, serie_tr=a, splits=sp,
            fonte="Nasdaq, via Yahoo Finance (preço corrigido por desdobramento"
                  + ("s: 4 por 1 em 20/07/2021 e 10 por 1 em 10/06/2024)" if sp else ")"))

    # Bitcoin: o mercado não fecha, então os dois pontos são o mesmo instante —
    # 0h UTC de 17/11 (21h de 16/11 em Brasília).
    d0, d1 = INICIO - dt.timedelta(days=1), ultimo_ate(btc, FIM - dt.timedelta(days=1))
    add(id="btc", nome="Bitcoin (BTC)", tipo="Investimento", moeda="USD", unidade="US$ por bitcoin",
        d0=d0, v0=btc[d0], d1=d1, v1=btc[d1], serie=btc, hora="0h UTC do dia seguinte",
        fonte="CoinMetrics (preço de referência diário, PriceUSD)")

    i0 = dt.date(2013, 10, 1)
    i1 = max(m for m in ipca if m <= dt.date(FIM.year, FIM.month, 1))
    add(id="ipca", nome="IPCA (inflação acumulada)", tipo="Referência", moeda="BRL",
        unidade="número-índice, dez/1993 = 100", d0=i0, v0=ipca[i0], d1=i1, v1=ipca[i1],
        serie=ipca, mensal=True,
        fonte="IBGE, SIDRA tabela 1737 (número-índice); inflação de nov/2013 até o último mês divulgado")

    d0, d1 = par(ptax)
    add(id="dolar", nome="Dólar (USD/BRL)", tipo="Investimento", moeda="BRL", unidade="R$ por US$ (PTAX venda)",
        d0=d0, v0=ptax[d0], d1=d1, v1=ptax[d1], serie=ptax, fonte="Banco Central, SGS 1 (PTAX venda)")

    f, _, _ = yh["BZ=F"]
    d0, d1 = par(f)
    add(id="brent", nome="Petróleo Brent (barril)", tipo="Preço (hipotético)", moeda="USD",
        unidade="US$ por barril", d0=d0, v0=f[d0], d1=d1, v1=f[d1], serie=f,
        fonte="ICE, contrato futuro mais próximo, via Yahoo Finance (BZ=F)")

    d0 = ultimo_ate(gas, INICIO - dt.timedelta(days=1))
    d1 = ultimo_ate(gas, FIM)
    add(id="gasolina", nome="Gasolina comum (preço médio Brasil)", tipo="Preço (hipotético)", moeda="BRL",
        unidade="R$ por litro", d0=d0, v0=gas[d0], d1=d1, v1=gas[d1], serie=gas,
        semana0=gas_semana[d0], semana1=gas_semana[d1],
        fonte="ANP, Levantamento de Preços de Combustíveis, série semanal Brasil")

    # Contas: as mesmas fórmulas da planilha.
    f_ipca = next(a for a in ativos if a["id"] == "ipca")
    fator_ipca = f_ipca["v1"] / f_ipca["v0"]
    for a in ativos:
        a["var_orig"] = a["v1"] / a["v0"] - 1
        if a["moeda"] == "USD":
            a["fx0"], a["fx1"] = fx(a["d0"]), fx(a["d1"])
            camb = a["fx1"] / a["fx0"]
        else:
            camb = 1.0
        a["var_brl"] = (1 + a["var_orig"]) * camb - 1
        a["hoje"] = CAPITAL * (1 + a["var_brl"])
        a["ao_ano"] = (1 + a["var_brl"]) ** (1 / ANOS) - 1
        a["real"] = (1 + a["var_brl"]) / fator_ipca - 1
        if a.get("tr"):
            a["hoje_tr"] = CAPITAL * a["tr"] * camb
            a["var_brl_tr"] = a["tr"] * camb - 1

    # Trajetórias mensais em reais (último dado de cada mês, mais o ponto final)
    meses = []
    m = dt.date(2013, 11, 1)
    while m <= FIM:
        prox = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        meses.append(min(prox - dt.timedelta(days=1), FIM))
        m = prox

    def trajetoria(a, chave="serie"):
        s = a[chave]
        pts = [[a["d0"].isoformat(), CAPITAL]] if not a.get("mensal") else [["2013-11-14", CAPITAL]]
        base = s[ultimo_ate(s, a["d0"])]
        for d in meses:
            if a.get("mensal"):
                mm = dt.date(d.year, d.month, 1)
                if mm not in s or mm <= a["d0"]:
                    continue
                v = s[mm] / base
                x = d
            else:
                lim = min(d, a["d1"])
                if lim <= a["d0"]:
                    continue
                v = s[ultimo_ate(s, lim)] / base
                if a["moeda"] == "USD":
                    v *= fx(lim) / a["fx0"]
                x = lim
            pts.append([x.isoformat(), round(CAPITAL * v, 2)])
        return pts

    saida_ativos = []
    for a in ativos:
        o = {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in a.items()
             if k not in ("serie", "serie_tr")}
        o["trajetoria"] = trajetoria(a)
        if a.get("serie_tr"):
            o["trajetoria_tr"] = trajetoria(a, "serie_tr")
        saida_ativos.append(o)

    resumo = dict(
        gerado=dt.datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M"),
        capital=CAPITAL, anos=ANOS, fator_ipca=fator_ipca,
        ipca=dict(acumulada=fator_ipca - 1, poder_compra=CAPITAL / fator_ipca,
                  necessario=CAPITAL * fator_ipca, perda=1 - 1 / fator_ipca,
                  mes0="nov/2013", mes1=f_ipca["d1"].isoformat()),
        ativos=saida_ativos)
    (DADOS / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, separators=(",", ":")))

    escrever_csv(ativos)
    escrever_xlsx(ativos, resumo)

    for a in ativos:
        extra = f"  com proventos R$ {a['hoje_tr']:,.0f}" if a.get("hoje_tr") else ""
        print(f"{a['nome']:38s} {a['d0']} {a['v0']:>12.4f} → {a['d1']} {a['v1']:>12.4f}"
              f"  {a['var_brl']*100:8.1f}%  R$ {a['hoje']:>14,.0f}{extra}")


# --------------------------------------------------------------------------- saídas

def rotulo_data(a, qual):
    d = a[qual]
    if a["id"] == "ipca":
        return d.strftime("%m/%Y")
    if a["id"] == "gasolina":
        sem = a["semana0" if qual == "d0" else "semana1"]
        return f"semana {sem.strftime('%d/%m')} a {br(d)}"
    if a["id"] == "btc":
        return f"{br(d)} (fim do dia, 0h UTC)"
    return br(d)


def escrever_csv(ativos):
    with open(DADOS / "comparacao.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Ativo/indicador", "Data de referência inicial", "Valor em 17/11/2013",
                    "Data de referência final", "Valor em 17/11/2026", "Unidade",
                    "Variação na moeda original (%)", "Variação acumulada em reais (%)",
                    "R$ 100 mil de 2013 valeriam hoje (R$)", "Com proventos reinvestidos (R$)",
                    "Retorno ao ano (%)", "Acima do IPCA (%)", "Fonte"])
        for a in ativos:
            w.writerow([a["nome"], rotulo_data(a, "d0"), round(a["v0"], 6), rotulo_data(a, "d1"),
                        round(a["v1"], 6), a["unidade"], round(a["var_orig"] * 100, 2),
                        round(a["var_brl"] * 100, 2), round(a["hoje"], 2),
                        round(a["hoje_tr"], 2) if a.get("hoje_tr") else "",
                        round(a["ao_ano"] * 100, 2), round(a["real"] * 100, 2), a["fonte"]])


def escrever_xlsx(ativos, resumo):
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True
    ws = wb.active
    ws.title = "Comparação"
    fonte = Font(name="Arial", size=10)
    negr = Font(name="Arial", size=10, bold=True)
    azul = Font(name="Arial", size=10, color="0000FF")
    cab = PatternFill("solid", fgColor="1F497D")
    fina = Side(style="thin", color="BFBFBF")

    ws["A1"] = "R$ 100 mil investidos em 17/11/2013: quanto valem em 17/11/2026"
    ws["A1"].font = Font(name="Arial", size=14, bold=True)
    ws["A2"] = ("Último pregão antes de cada data. Ativos em dólar convertidos pela PTAX de venda "
                "do mesmo dia (ou do último dia útil antes dele). Sem impostos nem custos.")
    ws["A2"].font = Font(name="Arial", size=9, italic=True, color="595959")
    ws["A3"], ws["B3"] = "Capital inicial (R$)", CAPITAL
    ws["A4"], ws["B4"] = "Anos", ANOS
    for c in ("A3", "A4"):
        ws[c].font = negr
    for c in ("B3", "B4"):
        ws[c].font = azul
        ws[c].fill = PatternFill("solid", fgColor="FFFF00")
    ws["B3"].number_format = '"R$" #,##0'
    ws["C3"] = "← mude aqui o valor aplicado; as colunas K, L, N e P se refazem"
    ws["C3"].font = Font(name="Arial", size=9, italic=True, color="595959")

    cols = ["Ativo/indicador", "Tipo", "Unidade", "Data de referência (2013)", "Valor em 17/11/2013",
            "Data de referência (2026)", "Valor em 17/11/2026", "Variação na moeda original",
            "PTAX venda inicial", "PTAX venda final", "Variação percentual acumulada no período (em reais)",
            "Quanto valeriam hoje R$ 100 mil investidos em 2013", "Retorno ao ano",
            "Acima da inflação (IPCA)", "Fator com proventos reinvestidos (moeda original)",
            "R$ 100 mil com proventos reinvestidos", "Fonte"]
    L0 = 6
    for j, t in enumerate(cols, 1):
        c = ws.cell(L0, j, t)
        c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        c.fill = cab
        c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[L0].height = 54

    lin_ipca = L0 + 1 + [a["id"] for a in ativos].index("ipca")
    for i, a in enumerate(ativos):
        r = L0 + 1 + i
        vals = [a["nome"], a["tipo"], a["unidade"], rotulo_data(a, "d0"), a["v0"], rotulo_data(a, "d1"), a["v1"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(r, j, v)
            c.font = azul if j in (5, 7) else fonte
        ws.cell(r, 8, f"=G{r}/E{r}-1")
        if a["moeda"] == "USD":
            ws.cell(r, 9, a["fx0"]).font = azul
            ws.cell(r, 10, a["fx1"]).font = azul
        ws.cell(r, 11, f'=(G{r}/E{r})*IF(I{r}="",1,J{r}/I{r})-1')
        ws.cell(r, 12, f"=$B$3*(1+K{r})")
        ws.cell(r, 13, f"=(1+K{r})^(1/$B$4)-1")
        ws.cell(r, 14, f"=(1+K{r})/(G{lin_ipca}/E{lin_ipca})-1" if a["id"] != "ipca" else None)
        if a.get("tr"):
            ws.cell(r, 15, a["tr"]).font = azul
            ws.cell(r, 16, f'=$B$3*O{r}*IF(I{r}="",1,J{r}/I{r})')
        ws.cell(r, 17, a["fonte"]).font = Font(name="Arial", size=9, color="595959")
        for j in (8, 11, 13, 14):
            ws.cell(r, j).number_format = "0.0%"
        for j in (12, 16):
            ws.cell(r, j).number_format = '"R$" #,##0'
        for j in (5, 7):
            ws.cell(r, j).number_format = "#,##0.00" if a["v1"] >= 1 else "0.0000"
        for j in (9, 10):
            ws.cell(r, j).number_format = "0.0000"
        ws.cell(r, 15).number_format = "0.00x"
        for j in range(1, 18):
            ws.cell(r, j).border = Border(bottom=fina)
            if j in (1, 2, 3, 4, 6, 8, 11, 12, 13, 14, 16):
                ws.cell(r, j).font = negr if j in (1, 12) else fonte
        if a["id"] == "ipca":
            ws.cell(r, 12).comment = Comment("No IPCA, é quanto é preciso ter hoje para comprar o mesmo "
                                             "que R$ 100 mil compravam em nov/2013.", "liberta-dados")
        if a["tipo"].startswith("Preço"):
            ws.cell(r, 12).comment = Comment("Hipotético: comprar o produto em 2013 e vender hoje. "
                                             "Serve para comparar preços, não como investimento.", "liberta-dados")

    # Bloco do IPCA
    r = L0 + len(ativos) + 2
    ws.cell(r, 1, "IPCA: poder de compra").font = Font(name="Arial", size=12, bold=True)
    linhas = [
        ("Inflação acumulada (nov/2013 até o último mês divulgado)", f"=G{lin_ipca}/E{lin_ipca}-1", "0.0%"),
        ("R$ 100 mil de 2013 compram hoje o que compravam (em reais de 2013)", f"=$B$3/(G{lin_ipca}/E{lin_ipca})", '"R$" #,##0'),
        ("Perda de poder de compra do dinheiro parado", f"=1-1/(G{lin_ipca}/E{lin_ipca})", "0.0%"),
        ("Valor necessário hoje para manter o poder de compra", f"=$B$3*(G{lin_ipca}/E{lin_ipca})", '"R$" #,##0'),
    ]
    for k, (t, fml, fmt) in enumerate(linhas, 1):
        ws.cell(r + k, 1, t).font = fonte
        c = ws.cell(r + k, 4, fml)
        c.number_format = fmt
        c.font = negr

    larguras = [34, 18, 26, 26, 14, 26, 14, 13, 11, 11, 16, 18, 10, 12, 14, 18, 70]
    for j, w in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(L0 + 1, 2)

    # Trajetórias
    ws2 = wb.create_sheet("Trajetória mensal")
    ws2["A1"] = "Valor em reais de R$ 100 mil aplicados em nov/2013, no fim de cada mês (preço, sem proventos)"
    ws2["A1"].font = Font(name="Arial", size=12, bold=True)
    datas = [p[0] for p in max((a["trajetoria"] for a in resumo["ativos"]), key=len)]
    todas = sorted({p[0] for a in resumo["ativos"] for p in a["trajetoria"]})
    meses = sorted({d[:7] for d in todas})
    ws2.cell(3, 1, "Mês").font = negr
    for j, a in enumerate(resumo["ativos"], 2):
        ws2.cell(3, j, a["nome"]).font = negr
        ws2.cell(3, j).alignment = Alignment(wrap_text=True)
        ws2.column_dimensions[get_column_letter(j)].width = 16
        por_mes = {p[0][:7]: p[1] for p in a["trajetoria"]}
        for i, m in enumerate(meses, 4):
            if m in por_mes:
                c = ws2.cell(i, j, por_mes[m])
                c.number_format = '"R$" #,##0'
                c.font = fonte
    for i, m in enumerate(meses, 4):
        ws2.cell(i, 1, f"{m[5:]}/{m[:4]}").font = fonte
    ws2.row_dimensions[3].height = 42
    ws2.column_dimensions["A"].width = 10
    ws2.freeze_panes = "B4"
    del datas

    # Notas
    ws3 = wb.create_sheet("Notas e fontes")
    notas = [
        "Datas de referência",
        "17/11/2013 foi domingo e 15/11/2013 (sexta) foi feriado no Brasil. Ativos brasileiros e PTAX usam 14/11/2013; "
        "ativos americanos e Brent, 15/11/2013, último pregão lá.",
        "No fim, o valor é o fechamento de 17/11/2026 quando a planilha foi gerada depois do pregão; "
        "antes disso, o do pregão anterior. A coluna de data mostra qual foi usado.",
        "Bitcoin negocia todo dia: os dois pontos são o preço de referência às 0h UTC de 17/11 (21h de 16/11 em Brasília).",
        "Gasolina: semana de pesquisa da ANP que terminou antes de cada data (a de 2026 é a última divulgada).",
        "IPCA: número-índice de out/2013 contra o último mês divulgado, ou seja, a inflação de nov/2013 em diante.",
        "",
        "Contas",
        "Ativos em dólar: variação do preço em dólar vezes a variação da PTAX de venda entre as duas datas — "
        "é o resultado de quem trocou reais por dólares em 2013, comprou o ativo e trocou de volta hoje.",
        "Desdobramentos: preços já corrigidos. Nvidia teve 4 por 1 (20/07/2021) e 10 por 1 (10/06/2024): "
        "uma ação de 2013 virou 40.",
        "CDI: taxa diária (SGS 12) capitalizada de 14/11/2013 até 16/11/2026; a taxa de cada dia rende até o dia útil seguinte.",
        "Coluna principal é só preço. A coluna de proventos reinveste dividendos e JCP brutos (Yahoo: fechamento ajustado; "
        "S&P 500: índice de retorno total). O Ibovespa já é um índice de retorno total.",
        "Sem imposto de renda, IOF, custódia ou corretagem em nenhum caso.",
        "Brent e gasolina são comparações de preço: os R$ 100 mil seriam comprar o produto e vendê-lo hoje.",
        "",
        "Fontes",
    ] + [f"{a['nome']}: {a['fonte']}" for a in ativos] + [
        "", f"Gerado em {resumo['gerado']} por scripts/gerar.py (github.com/guivaraschinalves/liberta-dados).",
    ]
    for i, t in enumerate(notas, 1):
        c = ws3.cell(i, 1, t)
        c.font = negr if t in ("Datas de referência", "Contas", "Fontes") else fonte
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws3.column_dimensions["A"].width = 130

    wb.save(DADOS / "liberta-dados.xlsx")


if __name__ == "__main__":
    main()
