"""Página de Análise da Origem dos Recursos e Autofinanciamento Eleitoral.

Explora a repartição entre Dinheiro Público (Fundo Especial / Fundo Partidário),
Financiamento Privado e Repasse entre Aliados, bem como o impacto do autofinanciamento
na viabilidade eleitoral e equidade democrática.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Origem dos Recursos & Autofinanciamento | Observatório Eleitoral",
    page_icon="🏦",
    layout="wide",
)

from src.data_loader import carregar_dados
from src.metrics import analise_autofinanciamento, analise_origem_recursos
from src.ui_components import (
    anonimizar_documento,
    formatar_moeda,
    formatar_numero,
    renderizar_sidebar,
)

# 1. Carregamento dos dados
df_completo = carregar_dados()

# 2. Barra lateral sincronizada
df_filtrado = renderizar_sidebar(df_completo)

# 3. Cabeçalho e Contextualização Metodológica
st.title("🏦 Origem dos Recursos & Autofinanciamento")
st.markdown(
    """
    Investigação da matriz de financiamento político após o veto do STF às doações empresariais diretas (ADI 4650).
    Análise da transição para a predominância de **fundos públicos** e o fenômeno do **autofinanciamento** por candidatos de alto patrimônio.
    """
)

if df_filtrado.empty:
    st.warning("⚠️ Nenhum registro encontrado para os filtros ativos. Ajuste os filtros na barra lateral.")
    st.stop()

# ==============================================================================
# SEÇÃO 1: KPIS DE ORIGEM E AUTOFINANCIAMENTO
# ==============================================================================
st.markdown("### 📌 Macroindicadores de Capitalização")

kpis_auto = analise_autofinanciamento(df_filtrado)
df_origem = analise_origem_recursos(df_filtrado)

total_captado = float(df_filtrado["valor_receita"].sum())
vol_publico = float(df_origem.loc[df_origem["tipo_receita"] == "Dinheiro Público", "total_arrecadado"].sum()) if not df_origem.empty else 0.0
pct_publico = (vol_publico / total_captado * 100.0) if total_captado > 0 else 0.0

col_k1, col_k2, col_k3, col_k4 = st.columns(4)

with col_k1:
    st.metric(
        label="Total Dinheiro Público",
        value=formatar_moeda(vol_publico),
        delta=f"{pct_publico:.1f}% do total",
        help="Volume originado de Direções Partidárias e Órgãos (Fundo Eleitoral e Fundo Partidário).",
    )

with col_k2:
    vol_privado = float(df_origem.loc[df_origem["tipo_receita"] == "Financiamento Privado", "total_arrecadado"].sum()) if not df_origem.empty else 0.0
    pct_privado = (vol_privado / total_captado * 100.0) if total_captado > 0 else 0.0
    st.metric(
        label="Total Financiamento Privado",
        value=formatar_moeda(vol_privado),
        delta=f"{pct_privado:.1f}% do total",
        help="Doações provenientes de pessoas físicas e autofinanciamento.",
    )

with col_k3:
    st.metric(
        label="Volume do Próprio Bolso",
        value=formatar_moeda(kpis_auto["volume_autofinanciamento"]),
        help="Montante que os próprios candidatos injetaram em suas respectivas campanhas (CPFs iguais).",
    )

with col_k4:
    diff_sucesso = kpis_auto["taxa_sucesso_auto"] - kpis_auto["taxa_sucesso_terceiros"]
    st.metric(
        label="Sucesso: Autofinanciados vs Terceiros",
        value=f"{kpis_auto['taxa_sucesso_auto']:.1f}%",
        delta=f"{diff_sucesso:+.1f}% vs Terceiros ({kpis_auto['taxa_sucesso_terceiros']:.1f}%)",
        help="Taxa de eleição de candidatos com autofinanciamento comparada a candidatos sem aporte próprio.",
    )

st.markdown("---")

# ==============================================================================
# SEÇÃO 2: MATRIZ DE ORIGEM DOS RECURSOS (PÚBLICO VS PRIVADO VS ALIADOS)
# ==============================================================================
col_mat1, col_mat2 = st.columns(2)

with col_mat1:
    st.subheader("🏛️ Repartição Geral por Origem do Recurso")
    st.caption("Classificação baseada nas regras de negócio oficiais do TSE e CGU.")

    if not df_origem.empty:
        cores_origem = {
            "Dinheiro Público": "#2563EB",
            "Financiamento Privado": "#10B981",
            "Repasse entre Aliados": "#F59E0B",
        }
        df_origem_sorted = df_origem.sort_values("total_arrecadado", ascending=True)
        fig_matriz_bar = px.bar(
            df_origem_sorted,
            x="total_arrecadado",
            y="tipo_receita",
            orientation="h",
            color="tipo_receita",
            color_discrete_map=cores_origem,
            text=df_origem_sorted.apply(
                lambda r: f"R$ {r['total_arrecadado']:,.0f} ({r['percentual']:.1f}%)".replace(",", "X").replace(".", ",").replace("X", "."),
                axis=1,
            ),
        )
        fig_matriz_bar.update_traces(
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Volume: R$ %{x:,.2f}<extra></extra>",
        )
        fig_matriz_bar.update_layout(
            showlegend=False,
            margin=dict(l=10, r=40, t=10, b=30),
            height=380,
            xaxis=dict(title="Volume Total (R$)"),
            yaxis=dict(title=""),
        )
        st.plotly_chart(fig_matriz_bar, use_container_width=True)


with col_mat2:
    st.subheader("📅 Evolução Histórica da Matriz (2018 - 2024)")
    st.caption("Participação relativa de fundos públicos vs. doações privadas ao longo das eleições.")

    evol_origem = (
        df_filtrado.groupby(["ano", "tipo_receita"], as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"valor_receita": "total"})
    )

    if not evol_origem.empty:
        fig_evol = px.bar(
            evol_origem,
            x="ano",
            y="total",
            color="tipo_receita",
            barmode="group",
            color_discrete_map={
                "Dinheiro Público": "#2563EB",
                "Financiamento Privado": "#10B981",
                "Repasse entre Aliados": "#F59E0B",
            },
            labels={"ano": "Ano Eleitoral", "total": "Volume Total (R$)", "tipo_receita": "Origem"},
        )
        fig_evol.update_layout(
            yaxis=dict(title="Volume Total (R$)"),
            xaxis=dict(title="Ano", type="category"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=30, b=30),
            height=380,
        )
        fig_evol.update_traces(hovertemplate="<b>%{x}</b> (%{data.name})<br>Volume: R$ %{y:,.2f}<extra></extra>")
        st.plotly_chart(fig_evol, use_container_width=True)

st.markdown("---")

# ==============================================================================
# SEÇÃO 3: AUTOFINANCIAMENTO E TOP CANDIDATOS QUE MAIS SE FINANCIARAM
# ==============================================================================
st.subheader("💰 Autofinanciamento: Os Maiores Investidores da Própria Campanha")
st.caption("Candidatos que mais aportaram capital próprio para financiar a disputa.")

cand_auto = (
    df_filtrado[df_filtrado["autofinanciamento"] == 1]
    .groupby(
        ["cpf_candidato", "nome_candidato", "uf_candidato", "cargo", "sigla_partido", "situacao"],
        as_index=False,
    )["valor_receita"]
    .sum()
    .rename(columns={"valor_receita": "total_autofinanciado"})
    .sort_values(by="total_autofinanciado", ascending=False)
    .head(15)
)

if not cand_auto.empty:
    cand_auto["cpf_anonimo"] = cand_auto["cpf_candidato"].apply(anonimizar_documento)
    cand_auto["rotulo"] = (
        cand_auto["nome_candidato"].str.title()
        + " ("
        + cand_auto["sigla_partido"]
        + "/"
        + cand_auto["uf_candidato"]
        + ")"
    )

    fig_auto = px.bar(
        cand_auto,
        x="total_autofinanciado",
        y="rotulo",
        orientation="h",
        color="situacao",
        labels={
            "total_autofinanciado": "Volume Aportado pelo Próprio Candidato (R$)",
            "rotulo": "Candidato",
            "situacao": "Situação Eleitoral",
        },
        custom_data=["cargo", "uf_candidato", "cpf_anonimo"],
    )
    fig_auto.update_layout(
        yaxis=dict(autorange="reversed", title=""),
        xaxis=dict(title="Volume Autofinanciado (R$)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=20, t=30, b=40),
        height=480,
    )
    fig_auto.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Cargo: %{customdata[0]}<br>"
            "UF: %{customdata[1]}<br>"
            "CPF: %{customdata[2]}<br>"
            "Autofinanciamento: R$ %{x:,.2f}<extra></extra>"
        )
    )
    st.plotly_chart(fig_auto, use_container_width=True)

    # Detalhamento em tabela expandida
    with st.expander("📋 Ver Tabela Completa dos 15 Maiores Autofinanciadores", expanded=False):
        tabela_exibicao = cand_auto[
            ["nome_candidato", "sigla_partido", "uf_candidato", "cargo", "situacao", "total_autofinanciado"]
        ].copy()
        tabela_exibicao["total_autofinanciado"] = tabela_exibicao["total_autofinanciado"].apply(formatar_moeda)
        st.dataframe(
            tabela_exibicao.rename(
                columns={
                    "nome_candidato": "Candidato",
                    "sigla_partido": "Partido",
                    "uf_candidato": "UF",
                    "cargo": "Cargo",
                    "situacao": "Situação",
                    "total_autofinanciado": "Aporte Próprio",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.info("Nenhuma ocorrência de autofinanciamento detectada no recorte ativo.")

# Explicação Metodológica
with st.expander("📚 Metodologia e Fundamentação Jurídica", expanded=False):
    st.markdown(
        """
        ### Categorização dos Recursos
        * **Dinheiro Público:** Mapeado automaticamente quando o doador contém os termos textuais `DIREÇÃO` ou `ÓRGÃO`. Representa repasses do Fundo Eleitoral (FEFC) e Fundo Especial de Assistência Financeira aos Partidos Políticos (Fundo Partidário).
        * **Repasse entre Aliados:** Mapeado quando a descrição do doador inclui a expressão `ELEIÇÃO`, identificando triangulações e transferências entre contas de campanha de candidatos coligados.
        * **Financiamento Privado:** Doações voluntárias de pessoas físicas e transferências do próprio candidato.
        * **Autofinanciamento:** Identificado pela flag binária `1` quando o CPF do doador é idêntico ao CPF do candidato.
        """
    )
