"""Gráfico de LPA - componente único, usado por TODOS os ativos do app.

27/11/2026: depois de várias rodadas corrigindo (e não resolvendo, segundo o usuário em produção)
um gráfico de barras desenhado na mão com div/CSS, trocado por um gráfico NATIVO do Streamlit -
ele mesmo garante a proporção entre as alturas, sem nenhuma conta de pixel/escala no código do
projeto. Nenhuma outra tela pode desenhar seu próprio gráfico de LPA: toda tela passa por
`render_lpa_chart`.

Mesmo dia, follow-up: `st.bar_chart` sozinho não mostra o valor em cima de cada barra (o usuário
reportou "Não tem valor nas barras") - a API simples dele não tem opção de rótulo de dado. Trocado
por `st.altair_chart` com uma camada de barra + uma camada de texto (ainda um componente NATIVO do
Streamlit, sem nenhum div/CSS/HTML escrito à mão) - a altura/proporção continua 100% calculada pelo
Vega-Lite (dentro do Altair), nunca pelo projeto; só o texto do valor é adicionado por cima.
"""
import altair as alt
import pandas as pd
import streamlit as st

from utils.formato import num as _num

ALTURA_PX = 220


def render_lpa_chart(dados):
    """
    Regra única para todos os ativos.
    dados: list[dict] com {"ano": str, "valor": float, "detalhe": str opcional}
    PROIBIDO: calcular altura em pixel, usar div/CSS, empilhar barras, usar hachura para representar valor.
    """
    df = pd.DataFrame([{"ano": d["ano"], "valor": d["valor"], "rotulo": _num(d["valor"])} for d in dados])
    base = alt.Chart(df).encode(
        # labelOverlap=False força o Vega-Lite a mostrar TODOS os rótulos do eixo, mesmo quando ele
        # "acharia" melhor esconder alguns por falta de espaço (comportamento padrão que escondia
        # barras no meio, ex. 2024/2026 Inicial/2026 Atual) - fonte menor (9px) e labelLimit maior
        # (os nomes ficaram mais longos, autoexplicativos: "2026 Inicial (Est. início ano)" etc.)
        # pra caber sem cortar o texto.
        x=alt.X("ano:N", sort=None, title=None,
                axis=alt.Axis(labelAngle=0, labelOverlap=False, labelFontSize=9, labelLimit=240)),
        y=alt.Y("valor:Q", title=None),
    )
    barras = base.mark_bar()
    texto = base.mark_text(dy=-8, color="white").encode(text="rotulo:N")
    st.altair_chart((barras + texto).properties(height=ALTURA_PX), use_container_width=True)
    for d in dados:
        if d.get("detalhe"):
            st.caption(f"{d['ano']}: {d['detalhe']}")
