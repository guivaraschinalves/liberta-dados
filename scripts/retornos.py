"""Retorno total por ano, 2017 a 2026 (no ano), de ativos brasileiros e americanos.

Grava dados/retornos.json (a tabela que a página retornos.html lê) e
dados/retornos-anuais.csv. Só retornos anuais: nenhuma série de preço vai para
o site.

Fontes:
  - Comdinheiro (preço ajustado por todos os proventos): Ibovespa, small caps
    (SMLL), IFIX, IMA-B, IRF-M, IDA-DI e as ações brasileiras. Precisa do
    cliente da Comdinheiro em ~/projetos/pl-ibovespa (credenciais locais);
    por isso este script roda à mão, não na Action.
  - Yahoo Finance (fechamento ajustado por dividendos): SPY, QQQ, EWZ, GLD e as
    sete ações da Mag 7.
  - CoinMetrics: bitcoin. Banco Central: CDI (SGS 12) e dólar PTAX (SGS 1).
    IBGE: IPCA (SIDRA 1737), como referência.

Contas:
  - Ano Y = nível do último dia útil até 31/12/Y sobre o do último até 31/12/Y-1.
  - CDI: taxa diária capitalizada no ano (a de cada dia rende até o dia útil seguinte).
  - Mag 7: média simples dos retornos anuais das sete ações (pesos iguais,
    rebalanceado todo 1º de janeiro).
  - Em reais × em dólares: (1 + r) × (PTAX fim / PTAX início) − 1 para ativo em
    dólar, e o inverso para ativo em reais. A PTAX é a do último dia útil até
    cada data.

    python3 scripts/retornos.py [--cache]
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
BRUTO = RAIZ / "bruto" / "retornos"
DADOS = RAIZ / "dados"
CACHE = "--cache" in sys.argv
ANOS = list(range(2017, 2027))           # 2026 = no ano
ANO_ATUAL = ANOS[-1]
UA = {"User-Agent": "Mozilla/5.0"}

sys.path.insert(0, os.path.expanduser(os.environ.get("COMDINHEIRO_CLIENTE", "~/projetos/pl-ibovespa")))

# (id, nome, grupo, fonte, código, moeda)
ATIVOS = [
    ("cdi", "CDI", "Brasil", "sgs", 12, "BRL"),
    ("idadi", "IDA-DI (debêntures DI)", "Brasil", "cd", "ANBIMA_IDADI", "BRL"),
    ("imab", "IMA-B (títulos IPCA+)", "Brasil", "cd", "ANBIMA_IMAB", "BRL"),
    ("irfm", "IRF-M (títulos prefixados)", "Brasil", "cd", "ANBIMA_IRFM", "BRL"),
    ("ibov", "Ibovespa", "Brasil", "cd", "IBOV", "BRL"),
    ("smll", "Small caps (SMLL)", "Brasil", "cd", "SMLL", "BRL"),
    ("ifix", "Fundos imobiliários (IFIX)", "Brasil", "cd", "IFIX", "BRL"),
    ("ewz", "Ibovespa em dólar (EWZ)", "Brasil", "yahoo", "EWZ", "USD"),
    ("dolar", "Dólar (PTAX)", "Brasil", "ptax", None, "USD"),
    ("petr4", "Petrobras (PETR4)", "Ações", "cd", "PETR4", "BRL"),
    ("vale3", "Vale (VALE3)", "Ações", "cd", "VALE3", "BRL"),
    ("itub4", "Itaú (ITUB4)", "Ações", "cd", "ITUB4", "BRL"),
    ("bbas3", "Banco do Brasil (BBAS3)", "Ações", "cd", "BBAS3", "BRL"),
    ("wege3", "WEG (WEGE3)", "Ações", "cd", "WEGE3", "BRL"),
    ("abev3", "Ambev (ABEV3)", "Ações", "cd", "ABEV3", "BRL"),
    ("spy", "S&P 500 (SPY)", "EUA", "yahoo", "SPY", "USD"),
    ("qqq", "Nasdaq 100 (QQQ)", "EUA", "yahoo", "QQQ", "USD"),
    ("mag7", "Magnificent 7", "EUA", "mag7", None, "USD"),
    ("gld", "Ouro (GLD)", "EUA", "yahoo", "GLD", "USD"),
    ("btc", "Bitcoin", "EUA", "btc", None, "USD"),
]
MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]


def baixar(nome, url, cab=None):
    destino = BRUTO / nome
    if CACHE and destino.exists():
        return destino.read_bytes()
    for t in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=cab or {}), timeout=90) as r:
                corpo = r.read()
            destino.write_bytes(corpo)
            return corpo
        except Exception as e:  # noqa: BLE001
            print(f"  {nome}: {e}; nova tentativa", file=sys.stderr)
            time.sleep(3 * (t + 1))
    raise SystemExit(f"falhou: {url}")


def sgs(codigo):
    serie = {}
    for k, (a, b) in enumerate([("01/12/2016", "31/12/2021"), ("01/01/2022", dt.date.today().strftime("%d/%m/%Y"))]):
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json"
               f"&dataInicial={a}&dataFinal={b}")
        for x in json.loads(baixar(f"sgs{codigo}-{k}.json", url)):
            serie[dt.datetime.strptime(x["data"], "%d/%m/%Y").date()] = float(x["valor"])
    return serie


def yahoo(simbolo):
    p1, p2 = int(dt.datetime(2016, 12, 1).timestamp()), int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(simbolo)}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,split")
    r = json.loads(baixar(f"yahoo-{simbolo}.json", url, UA))["chart"]["result"][0]
    tz = ZoneInfo(r["meta"]["exchangeTimezoneName"])
    fecha = r["meta"].get("currentTradingPeriod", {}).get("regular", {}).get("end", 0)
    hoje = dt.datetime.now(tz).date()
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for t, v in zip(r["timestamp"], adj):
        d = dt.datetime.fromtimestamp(t, tz).date()
        if v is None or (d == hoje and time.time() < fecha + 20 * 60):
            continue
        out[d] = v
    return out


def bitcoin():
    url = ("https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
           "?assets=btc&metrics=PriceUSD&start_time=2016-12-01&frequency=1d&page_size=10000")
    return {dt.date.fromisoformat(x["time"][:10]): float(x["PriceUSD"])
            for x in json.loads(baixar("coinmetrics-btc.json", url))["data"]}


def ipca():
    url = "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/201612-209912"
    return {dt.date(int(x["D3C"][:4]), int(x["D3C"][4:]), 1): float(x["V"])
            for x in json.loads(baixar("sidra-1737.json", url))[1:] if x["V"] not in ("...", "-", "")}


def comdinheiro(codigos):
    """Preço ajustado por todos os proventos, em janelas de até ~3,5 anos
    (a tela devolve no máximo 1.000 linhas)."""
    import comdinheiro as c
    janelas = [("26122016", "30062020"), ("01072020", "31122023"), ("01012024", dt.date.today().strftime("%d%m%Y"))]
    out = {k: {} for k in codigos}
    for a, b in janelas:
        url = (f"HistoricoCotacao002.php?&x={'+'.join(codigos)}&data_ini={a}&data_fim={b}&pagina=1"
               "&d=MOEDA_ORIGINAL&g=1&m=0&info_desejada=preco&retorno=discreto&tipo_data=du_br"
               "&tipo_ajuste=todosajustes&num_casas=8&enviar_email=0&ordem_legenda=1&cabecalho_excel=modo1"
               "&ordem_data=0&rent_acum=rent_acum&preco_nd_ant=0&base_num_indice=100&flag_num_indice=0")
        linhas = c.tabela(c.consultar(url, atualizar=not CACHE), 1)
        if len(linhas) >= 999:
            raise SystemExit(f"Comdinheiro: janela {a}-{b} cortada em 1.000 linhas")
        for ln in linhas:
            d = dt.datetime.strptime(ln["Data"], "%d/%m/%Y").date()
            for k in codigos:
                v = c.numero(ln.get(k))
                if v:
                    out[k][d] = v
    for k, s in out.items():
        if len(s) < 2000:
            raise SystemExit(f"Comdinheiro: {k} veio com só {len(s)} dias")
    return out


def ultimo_ate(serie, d):
    ds = [x for x in serie if x <= d]
    if not ds:
        raise SystemExit(f"sem dado até {d}")
    return max(ds)


def retornos_por_ano(serie, fim_atual):
    """{ano: retorno} pelo último nível até 31/12 de cada ano; o ano corrente
    vai até fim_atual. Devolve também as datas usadas."""
    out, datas = {}, {}
    for y in ANOS:
        d0 = ultimo_ate(serie, dt.date(y - 1, 12, 31))
        d1 = ultimo_ate(serie, fim_atual if y == ANO_ATUAL else dt.date(y, 12, 31))
        out[y] = serie[d1] / serie[d0] - 1
        datas[y] = (d0, d1)
    return out, datas


def fins_de_mes(fim):
    """[("2017-01", data), ...] até o mês de `fim`; o último mês acaba em `fim`."""
    out, y, m = [], ANOS[0], 1
    while (y, m) <= (fim.year, fim.month):
        prox = dt.date(y + (m == 12), m % 12 + 1, 1)
        out.append((f"{y}-{m:02d}", min(prox - dt.timedelta(days=1), fim)))
        y, m = prox.year, prox.month
    return out


def niveis_mensais(serie, meses):
    """Nível no fim de dez do ano anterior ao primeiro e no fim de cada mês, com as datas usadas."""
    d0 = ultimo_ate(serie, dt.date(ANOS[0] - 1, 12, 31))
    ds = [d0] + [ultimo_ate(serie, d) for _, d in meses]
    return [serie[d] for d in ds], ds


def niveis_mag7(yh, meses):
    """Índice da Mag 7 com pesos iguais rebalanceados todo 1º de janeiro (a mesma
    regra da tabela anual): dentro do ano, a média de quanto cada ação andou desde
    o fim do ano anterior."""
    base_ano, nivel, saida, ds = {}, 1.0, [1.0], [ultimo_ate(yh["AAPL"], dt.date(ANOS[0] - 1, 12, 31))]
    for mes, d in meses:
        y = int(mes[:4])
        if y not in base_ano:
            base_ano[y] = (nivel, {s: yh[s][ultimo_ate(yh[s], dt.date(y - 1, 12, 31))] for s in MAG7})
        n0, p0 = base_ano[y]
        nivel = n0 * sum(yh[s][ultimo_ate(yh[s], d)] / p0[s] for s in MAG7) / len(MAG7)
        saida.append(nivel)
        ds.append(ultimo_ate(yh["AAPL"], d))
    return saida, ds


def main():
    BRUTO.mkdir(parents=True, exist_ok=True)
    hoje = dt.date.today()
    ptax = sgs(1)
    cdi = sgs(12)
    cd = comdinheiro([a[4] for a in ATIVOS if a[3] == "cd"])
    yh = {s: yahoo(s) for s in [a[4] for a in ATIVOS if a[3] == "yahoo"] + MAG7}
    btc = bitcoin()
    ip = ipca()

    # índice do CDI: taxa de cada dia rende até o dia útil seguinte
    dias = sorted(cdi)
    idx, nivel = {}, 1.0
    for i, d in enumerate(dias):
        idx[d] = nivel
        nivel *= 1 + cdi[d] / 100
    # o nível no dia seguinte ao último dado (o rendimento do último dia já aconteceu)
    idx[dias[-1] + dt.timedelta(days=1)] = nivel

    # Data final comum: o último dia que todas as fontes já têm (a Comdinheiro
    # às vezes demora um pregão). Todos os ativos param nela, para o "no ano"
    # comparar o mesmo período: uma semana forte só de um lado distorce.
    fim_br = ultimo_ate(cd["IBOV"], hoje - dt.timedelta(days=1))
    fim = min(fim_br, ultimo_ate(yh["SPY"], hoje), ultimo_ate(ptax, hoje))
    fim_br = fim_eua = fim_ptax = fim
    print(f"data final comum: {fim}")

    def fx(d):
        return ptax[ultimo_ate(ptax, d)]

    linhas = []
    for id_, nome, grupo, fonte, cod, moeda in ATIVOS:
        if fonte == "cd":
            serie, fim = cd[cod], fim_br
        elif fonte == "sgs":
            serie, fim = idx, fim_br + dt.timedelta(days=1)
        elif fonte == "yahoo":
            serie, fim = yh[cod], fim_eua
        elif fonte == "btc":
            serie, fim = btc, ultimo_ate(btc, fim_eua)
        elif fonte == "ptax":
            serie, fim = ptax, fim_ptax
        if fonte == "mag7":
            por = {s: retornos_por_ano(yh[s], fim_eua) for s in MAG7}
            r = {y: sum(por[s][0][y] for s in MAG7) / len(MAG7) for y in ANOS}
            datas = por["AAPL"][1]
            fim = fim_eua
            niv, nds = niveis_mag7(yh, fins_de_mes(fim))
        else:
            r, datas = retornos_por_ano(serie, fim)
            niv, nds = niveis_mensais(serie, fins_de_mes(fim))
        # retornos mensais, em reais e em dólares (o produto dos meses de um ano dá o anual)
        mbrl, musd = [], []
        for i in range(1, len(niv)):
            rm, camb = niv[i] / niv[i - 1] - 1, fx(nds[i]) / fx(nds[i - 1])
            if id_ == "dolar":
                mbrl.append(rm); musd.append(None)
            elif moeda == "USD":
                musd.append(rm); mbrl.append((1 + rm) * camb - 1)
            else:
                mbrl.append(rm); musd.append((1 + rm) / camb - 1)
        # em reais e em dólares
        brl, usd = {}, {}
        for y in ANOS:
            d0, d1 = datas[y]
            camb = fx(d1) / fx(d0)
            if id_ == "dolar":
                brl[y], usd[y] = r[y], None          # o dólar em dólar não varia
            elif moeda == "USD":
                usd[y], brl[y] = r[y], (1 + r[y]) * camb - 1
            else:
                brl[y], usd[y] = r[y], (1 + r[y]) / camb - 1
        linhas.append(dict(id=id_, nome=nome, grupo=grupo, moeda=moeda,
                           fim=fim.isoformat(),
                           brl={str(y): round(v, 6) for y, v in brl.items()},
                           usd={str(y): (round(v, 6) if v is not None else None) for y, v in usd.items()},
                           mbrl=[round(v, 6) for v in mbrl],
                           musd=[(round(v, 6) if v is not None else None) for v in musd]))
        # conferência: os meses de cada ano compõem o retorno anual
        for y in ANOS:
            for nome_m, anual, mens in (("brl", brl, mbrl), ("usd", usd, musd)):
                if anual[y] is None:
                    continue
                f = 1.0
                for (mes, _), v in zip(fins_de_mes(fim), mens):
                    if mes.startswith(str(y)):
                        f *= 1 + v
                if abs(f - 1 - anual[y]) > 1e-6:
                    raise SystemExit(f"{nome} {y} {nome_m}: meses dão {f - 1:.6f}, ano dá {anual[y]:.6f}")

    # IPCA como referência (não entra no ranking): dez/dez, e no ano até o último mês
    ult = max(ip)
    ipca_r = {str(y): round(ip[min(dt.date(y, 12, 1), ult)] / ip[dt.date(y - 1, 12, 1)] - 1, 6) for y in ANOS}
    dias_ano = (fim_br - dt.date(ANO_ATUAL - 1, 12, 31)).days
    doc = dict(gerado=dt.datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M"),
               anos=ANOS, fim_b3=fim_br.isoformat(), fim_eua=fim_eua.isoformat(), fim_ptax=fim_ptax.isoformat(),
               ipca=ipca_r, ipca_ate=ult.isoformat(), anos_periodo=round(len(ANOS) - 1 + dias_ano / 365.25, 4),
               meses=[m for m, _ in fins_de_mes(fim_br)],
               ipca_m=[(round(ip[dt.date(int(m[:4]), int(m[5:]), 1)] / ip[dt.date(int(m[:4]) - (m[5:] == "01"),
                                                                       (int(m[5:]) - 2) % 12 + 1, 1)] - 1, 6)
                        if dt.date(int(m[:4]), int(m[5:]), 1) in ip else None) for m, _ in fins_de_mes(fim_br)],
               linhas=linhas)
    (DADOS / "retornos.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))

    with open(DADOS / "retornos-anuais.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Ativo", "Moeda do retorno"] + [str(y) if y < ANO_ATUAL else f"{y} (no ano)" for y in ANOS])
        for moeda in ("brl", "usd"):
            for ln in linhas:
                w.writerow([ln["nome"], "R$" if moeda == "brl" else "US$"] +
                           [("" if ln[moeda][str(y)] is None else round(ln[moeda][str(y)] * 100, 2)) for y in ANOS])
        w.writerow(["IPCA (referência)", "R$"] + [round(ipca_r[str(y)] * 100, 2) for y in ANOS])

    for ln in linhas:
        print(f"{ln['nome']:30s} " + " ".join(f"{ln['brl'][str(y)] * 100:7.1f}" for y in ANOS))
    print("em dólares:")
    for ln in linhas:
        if ln["moeda"] == "USD" and ln["id"] != "dolar":
            print(f"{ln['nome']:30s} " + " ".join(f"{ln['usd'][str(y)] * 100:7.1f}" for y in ANOS))


if __name__ == "__main__":
    main()
