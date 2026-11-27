"""Gráfico de LPA - componente único, usado por TODOS os ativos do app.

27/11/2026: depois de várias rodadas corrigindo (e não resolvendo, segundo o usuário em produção)
um gráfico de barras desenhado na mão com div/CSS, trocado por um `st.bar_chart` nativo do
Streamlit - ele mesmo garante a proporção entre as alturas, sem nenhuma conta de pixel/escala no
código do projeto. Nenhuma outra tela pode desenhar seu próprio gráfico de LPA: toda tela passa
por `render_lpa_chart`.
"""
import streamlit as st
import pandas as pd


def render_lpa_chart(dados):
    """
    Regra única para todos os ativos.
    dados: list[dict] com {"ano": str, "valor": float, "detalhe": str opcional}
    PROIBIDO: calcular altura em pixel, usar div/CSS, empilhar barras, usar hachura para representar valor.
    """
    df = pd.DataFrame([{"ano": d["ano"], "valor": d["valor"]} for d in dados])
    st.bar_chart(df.set_index("ano"), height=220)
    for d in dados:
        if d.get("detalhe"):
            st.caption(f"{d['ano']}: {d['detalhe']}")
