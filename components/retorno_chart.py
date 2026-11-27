"""Gráfico de Retorno acumulado - componente único, usado por TODOS os ativos do app.

Mesma regra do `components/lpa_chart.py` (27/11/2026): gráfico NATIVO do Streamlit (Altair), sem
nenhuma conta de pixel/escala no código do projeto, sem barra desenhada com div/CSS, sem empilhar
barras. Única diferença de propósito pro de LPA: retorno pode ser negativo (ex. ação caindo no
período) - o rótulo do valor fica acima da barra quando positivo e abaixo quando negativo, e a cor
muda (vermelho/azul, mesmas cores do resto do app) - nenhuma conta de altura nova por causa disso,
só estilo.
"""
import altair as alt
import pandas as pd
import streamlit as st

from utils.formato import pct as _pct

ALTURA_PX = 220
AZUL = "#5b8def"
VERMELHO = "#f06a6a"


def render_retorno_chart(linhas):
    """
    Regra única para todos os ativos.
    linhas: list[dict] com {"nome": str, "valor": float opcional, "rotulo": str opcional}
    `rotulo` é o texto já formatado pra mostrar em cima da barra - quando ausente, usa
    `utils.formato.pct` (2 casas) como padrão; quem chama passa o seu próprio rótulo quando quiser
    manter a MESMA formatação usada em outro texto do mesmo card (ex. resumo logo abaixo do
    gráfico), pra nunca mostrar 2 arredondamentos diferentes do mesmo número na mesma tela.
    PROIBIDO: calcular altura em pixel, usar div/CSS, empilhar barras, usar hachura para representar valor.
    """
    pontos = [l for l in linhas if l.get("valor") is not None]
    if not pontos:
        st.caption("Sem dado suficiente para o gráfico.")
        return
    df = pd.DataFrame([{"nome": l["nome"], "valor": l["valor"], "rotulo": l.get("rotulo") or _pct(l["valor"])}
                       for l in pontos])
    base = alt.Chart(df).encode(
        x=alt.X("nome:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("valor:Q", title=None),
        color=alt.condition(alt.datum.valor < 0, alt.value(VERMELHO), alt.value(AZUL)),
    )
    barras = base.mark_bar()
    texto_pos = base.transform_filter(alt.datum.valor >= 0).mark_text(dy=-8, color="white").encode(text="rotulo:N")
    texto_neg = base.transform_filter(alt.datum.valor < 0).mark_text(dy=12, color="white").encode(text="rotulo:N")
    st.altair_chart((barras + texto_pos + texto_neg).properties(height=ALTURA_PX), use_container_width=True)
