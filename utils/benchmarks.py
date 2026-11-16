"""Comparadores brasileiros (CDI, Selic, IPCA, Poupança) pelo SGS do Banco Central.

As funções de acumulação são puras e testadas; a busca na API fica isolada e, se falhar,
devolve None: a tela mostra "Dados indisponíveis" e nunca um número inventado.
"""
from __future__ import annotations

import pandas as pd

# Códigos das séries no SGS/BCB
SGS = {
    "cdi": (12, "diaria"),        # CDI, % ao dia
    "selic": (11, "diaria"),      # Selic, % ao dia
    "ipca": (433, "mensal"),      # IPCA, % ao mês
    "poupanca": (195, "aniversario"),  # poupança (depósitos desde 05/2012), % ao mês por data de aniversário
}
URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"


def acumular(taxas_pct: pd.Series, inicio: pd.Timestamp, fim: pd.Timestamp) -> float | None:
    """Retorno acumulado em % das taxas (em %) com data em (inicio, fim].
    None se a série não cobre o começo do período."""
    if taxas_pct is None or taxas_pct.empty:
        return None
    s = taxas_pct.sort_index()
    if s.index[0] > inicio + pd.Timedelta(days=45):
        return None
    janela = s[(s.index > inicio) & (s.index <= fim)]
    if janela.empty:
        return None
    return float(((1 + janela / 100).prod() - 1) * 100)


def mensal_de_aniversario(taxas_pct: pd.Series) -> pd.Series:
    """Série diária de taxas mensais por aniversário -> uma taxa por mês (aniversário no dia 1º)."""
    s = taxas_pct.sort_index()
    return s[s.index.day == 1]


def buscar_sgs(codigo: int, inicio: pd.Timestamp, fim: pd.Timestamp) -> pd.Series:
    """Baixa uma série do SGS. Levanta exceção se a API falhar."""
    import requests

    r = requests.get(
        URL.format(codigo=codigo),
        params={"formato": "json", "dataInicial": f"{inicio:%d/%m/%Y}", "dataFinal": f"{fim:%d/%m/%Y}"},
        headers={"Accept": "application/json"}, timeout=12,
    )
    r.raise_for_status()
    dados = r.json()
    datas = pd.to_datetime([x["data"] for x in dados], format="%d/%m/%Y")
    return pd.Series([float(str(x["valor"]).replace(",", ".")) for x in dados], index=datas)


def retornos_brasil(fim: pd.Timestamp, anos=(1, 3, 5)) -> dict[str, list[float | None]]:
    """Retorno acumulado de cada comparador para cada período. Falha vira None."""
    saida = {}
    inicio_busca = fim - pd.DateOffset(years=max(anos)) - pd.Timedelta(days=40)
    for nome, (codigo, tipo) in SGS.items():
        try:
            serie = buscar_sgs(codigo, inicio_busca, fim)
            if tipo == "aniversario":
                serie = mensal_de_aniversario(serie)
            if tipo == "diaria":
                # taxa do dia D rende de D para D+1: de um fechamento ao outro entram as taxas de
                # [início, fim), mesma janela do retorno da ação
                um = pd.Timedelta(days=1)
                saida[nome] = [acumular(serie, fim - pd.DateOffset(years=a) - um, fim - um) for a in anos]
                continue
            if tipo == "mensal":
                # IPCA sai com 1 mês de atraso e cada taxa tem a data do dia 1º do mês: contar os N meses
                # até o último divulgado, senão o período de 12 meses fica com 11
                ref = serie.index[serie.index <= fim].max()
            else:
                # poupança: taxa datada no início do período de aniversário; só períodos já completos
                ref = serie.index[serie.index + pd.DateOffset(months=1) <= fim].max()
            saida[nome] = [acumular(serie, ref - pd.DateOffset(years=a), ref) for a in anos]
        except Exception:
            saida[nome] = [None for _ in anos]
    return saida
