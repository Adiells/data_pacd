"""Página de Visão Geral Analítica do Financiamento Eleitoral.

Apresenta KPIs consolidados e visualizações gráficas interativas em Plotly
para exploração dos maiores doadores, candidatos mais financiados e assimetria
da distribuição de capital eleitoral.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 1. Configuração da página
st.set_page_config(
    page_title="Visão Geral | Observatório Eleitoral",
    page_icon="📊",
    layout="wide",
)

from src.data_loader import carregar_dados
from src.geo import gerar_heatmap_brasil
from src.metrics import analise_origem_recursos
from src.ui_components import (
    anonimizar_documento,
    formatar_moeda,
    formatar_numero,
    renderizar_sidebar,
)

# 2. Carregamento dos dados com cache
df_completo = carregar_dados()

# 3. Sincronização dos filtros da barra lateral
df_filtrado = renderizar_sidebar(df_completo)

# 4. Título da página
st.title("📊 Visão Geral do Financiamento de Campanha")
st.markdown(
    """
    Explore os macroindicadores financeiros da eleição, o perfil dos maiores doadores,
    a correlação visual com a situação eleitoral e a distribuição de recursos entre as campanhas.
    """
)

# Validação de dados após filtros
if df_filtrado.empty:
    st.warning(
        "⚠️ Nenhum registro encontrado para a combinação de filtros selecionada. "
        "Por favor, ajuste os filtros de Ano, Cargo ou Partido na barra lateral."
    )
    st.stop()

# ==============================================================================
# SEÇÃO 1: KPIs NO TOPO (st.metric)
# ==============================================================================
st.markdown("### 📌 Indicadores Estratégicos")

# Cálculo dos agregados por candidato
cand_agregado = (
    df_filtrado.groupby(
        ["cpf_candidato", "nome_candidato", "sigla_partido", "cargo", "situacao"],
        as_index=False,
    )["valor_receita"]
    .sum()
    .rename(columns={"valor_receita": "total_receita"})
    .sort_values(by="total_receita", ascending=False)
    .reset_index(drop=True)
)

situacao_limpa = cand_agregado["situacao"].fillna("").astype(str).str.lower()
cand_agregado["sucesso"] = (
    situacao_limpa.str.contains("eleito")
    & ~situacao_limpa.str.contains(r"n[aã]o[\s\-_]*eleito")
).astype(int)

# 1. Total arrecadado
total_arrecadado = float(df_filtrado["valor_receita"].sum())

# 2. Número de candidatos analisados
num_candidatos = int(df_filtrado["cpf_candidato"].nunique())

# 3. Total de doadores únicos (CPFs/CNPJs)
num_doadores = int(df_filtrado["cpf_cnpj_doador"].nunique())

# 4. Taxa de sucesso médio: Top 10% mais financiados vs. Bottom 50%
n_total = len(cand_agregado)
if n_total > 0:
    tamanho_top10 = max(1, int(np.ceil(n_total * 0.10)))
    tamanho_bottom50 = max(1, int(np.floor(n_total * 0.50)))

    taxa_top10 = float(cand_agregado.iloc[:tamanho_top10]["sucesso"].mean() * 100.0)
    taxa_bottom50 = float(cand_agregado.iloc[-tamanho_bottom50:]["sucesso"].mean() * 100.0)
    diferenca_sucesso = taxa_top10 - taxa_bottom50
else:
    taxa_top10 = 0.0
    taxa_bottom50 = 0.0
    diferenca_sucesso = 0.0

col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)

with col_kpi1:
    st.metric(
        label="Total Arrecadado",
        value=formatar_moeda(total_arrecadado),
        help="Montante financeiro acumulado por todas as doações no recorte filtrado.",
    )

with col_kpi2:
    st.metric(
        label="Candidatos Analisados",
        value=formatar_numero(num_candidatos),
        help="Quantidade única de candidatos concorrentes registrados no filtro.",
    )

with col_kpi3:
    st.metric(
        label="Doadores Únicos",
        value=formatar_numero(num_doadores),
        help="Quantidade única de pessoas físicas e jurídicas doadoras.",
    )

with col_kpi4:
    st.metric(
        label="Taxa Sucesso: Top 10% vs Bottom 50%",
        value=f"{taxa_top10:.1f}%",
        delta=f"{diferenca_sucesso:+.1f}% vs Bottom 50% ({taxa_bottom50:.1f}%)",
        help=(
            "Percentual de candidatos eleitos no decil mais financiado (Top 10%) "
            "comparado à metade menos financiada (Bottom 50%)."
        ),
    )

st.markdown("---")

# ==============================================================================
# SEÇÃO 2: PANORAMA FEDERATIVO E MAPA DE CALOR DO BRASIL (HEATMAP)
# ==============================================================================
st.subheader("🗺️ Panorama Federativo e Mapa de Calor do Brasil (Heatmap)")
st.caption(
    "Distribuição geoespacial e densidade do financiamento político nas 27 Unidades Federativas."
)

col_ctrl_mapa1, col_ctrl_mapa2 = st.columns([2, 1])
with col_ctrl_mapa1:
    opcao_metrica = st.radio(
        "Métrica do Heatmap Geográfico:",
        options=[
            "💰 Volume Arrecadado (R$)",
            "👥 Quantidade de Candidatos",
            "🤝 Doadores Únicos (CPFs)",
            "🗳️ Custo Mediano do Voto (R$/voto)",
        ],
        horizontal=True,
    )

mapa_metricas = {
    "💰 Volume Arrecadado (R$)": "total_arrecadado",
    "👥 Quantidade de Candidatos": "total_candidatos",
    "🤝 Doadores Únicos (CPFs)": "total_doadores",
    "🗳️ Custo Mediano do Voto (R$/voto)": "custo_mediano_voto",
}
chave_metrica = mapa_metricas[opcao_metrica]

col_mapa, col_grafs = st.columns([1.35, 1])

with col_mapa:
    fig_heatmap = gerar_heatmap_brasil(df_filtrado, metrica=chave_metrica, altura=520)
    st.plotly_chart(fig_heatmap, use_container_width=True)

with col_grafs:
    uf_filtro = st.session_state.get("filtro_uf", "Todas as UFs (Brasil)")
    if uf_filtro == "Todas as UFs (Brasil)":
        st.markdown("##### 📊 Ranking Federativo (Top Estados)")
        volume_ufs = (
            df_filtrado.groupby("uf_candidato", as_index=False)["valor_receita"]
            .sum()
            .rename(columns={"valor_receita": "total_uf"})
            .sort_values(by="total_uf", ascending=True)
            .tail(7)
        )
        if not volume_ufs.empty:
            fig_ufs = px.bar(
                volume_ufs,
                x="total_uf",
                y="uf_candidato",
                orientation="h",
                color="total_uf",
                color_continuous_scale="Blues",
                labels={"total_uf": "Volume Arrecadado (R$)", "uf_candidato": "UF"},
            )
            fig_ufs.update_layout(
                coloraxis_showscale=False,
                margin=dict(l=10, r=20, t=5, b=20),
                height=215,
                xaxis=dict(title=""),
                yaxis=dict(title=""),
            )
            fig_ufs.update_traces(
                hovertemplate="<b>UF: %{y}</b><br>Arrecadação: R$ %{x:,.2f}<extra></extra>"
            )
            st.plotly_chart(fig_ufs, use_container_width=True)
    else:
        st.markdown(f"##### 📍 Partidos no Estado ({uf_filtro})")
        volume_partidos = (
            df_filtrado.groupby("sigla_partido", as_index=False)["valor_receita"]
            .sum()
            .rename(columns={"valor_receita": "total_partido"})
            .sort_values(by="total_partido", ascending=True)
            .tail(7)
        )
        if not volume_partidos.empty:
            fig_part = px.bar(
                volume_partidos,
                x="total_partido",
                y="sigla_partido",
                orientation="h",
                color="total_partido",
                color_continuous_scale="Teal",
                labels={"total_partido": "Volume Arrecadado (R$)", "sigla_partido": "Partido"},
            )
            fig_part.update_layout(
                coloraxis_showscale=False,
                margin=dict(l=10, r=20, t=5, b=20),
                height=215,
                xaxis=dict(title=""),
                yaxis=dict(title=""),
            )
            fig_part.update_traces(
                hovertemplate="<b>%{y}</b><br>Volume: R$ %{x:,.2f}<extra></extra>"
            )
            st.plotly_chart(fig_part, use_container_width=True)

    st.markdown("##### 🏛️ Composição por Origem do Recurso")
    df_origem_visao = analise_origem_recursos(df_filtrado)
    if not df_origem_visao.empty:
        df_origem_sorted = df_origem_visao.sort_values("total_arrecadado", ascending=True)
        fig_origem_bar = px.bar(
            df_origem_sorted,
            x="total_arrecadado",
            y="tipo_receita",
            orientation="h",
            color="tipo_receita",
            color_discrete_map={
                "Dinheiro Público": "#2563EB",
                "Financiamento Privado": "#10B981",
                "Repasse entre Aliados": "#F59E0B",
            },
            text=df_origem_sorted.apply(
                lambda r: f"R$ {r['total_arrecadado']:,.0f} ({r['percentual']:.1f}%)".replace(",", "X").replace(".", ",").replace("X", "."),
                axis=1,
            ),
        )
        fig_origem_bar.update_traces(
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Volume: R$ %{x:,.2f}<extra></extra>",
        )
        fig_origem_bar.update_layout(
            showlegend=False,
            margin=dict(l=10, r=40, t=5, b=20),
            height=215,
            xaxis=dict(title=""),
            yaxis=dict(title=""),
        )
        st.plotly_chart(fig_origem_bar, use_container_width=True)

st.markdown("---")

# ==============================================================================
# SEÇÃO 3: RANKINGS TOP 10 DOADORES E CANDIDATOS
# ==============================================================================

# Layout de duas colunas para os Top 10 Doadores e Top 10 Candidatos
col_graf1, col_graf2 = st.columns(2)

with col_graf1:
    st.subheader("🏢 Top 10 Doadores")
    st.caption("Maiores volumes financeiros aportados (documentos anonimizados nos dígitos centrais).")

    doadores_top10 = (
        df_filtrado.groupby(["cpf_cnpj_doador", "nome_doador"], as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"valor_receita": "total_doado"})
        .sort_values(by="total_doado", ascending=False)
        .head(10)
    )

    if not doadores_top10.empty:
        doadores_top10["doc_anonimo"] = doadores_top10["cpf_cnpj_doador"].apply(anonimizar_documento)
        doadores_top10["rotulo_doador"] = (
            doadores_top10["nome_doador"].str.title() + " (" + doadores_top10["doc_anonimo"] + ")"
        )

        fig_doadores = px.bar(
            doadores_top10,
            x="total_doado",
            y="rotulo_doador",
            orientation="h",
            color="total_doado",
            color_continuous_scale="Blues",
            labels={"total_doado": "Volume Doado (R$)", "rotulo_doador": "Doador"},
        )

        fig_doadores.update_layout(
            yaxis={"categoryorder": "total ascending", "title": ""},
            xaxis={"title": "Volume Total (R$)"},
            coloraxis_showscale=False,
            margin=dict(l=10, r=20, t=20, b=30),
            height=460,
        )

        fig_doadores.update_traces(
            hovertemplate="<b>%{y}</b><br>Total Doado: R$ %{x:,.2f}<extra></extra>",
            texttemplate="R$ %{x:,.0f}",
            textposition="inside",
            insidetextanchor="middle",
        )

        st.plotly_chart(fig_doadores, use_container_width=True)
    else:
        st.info("Sem dados de doadores no filtro ativo.")

with col_graf2:
    st.subheader("🏆 Top 10 Candidatos Mais Financiados")
    st.caption("Candidatos com maior volume de receitas, estratificados por situação eleitoral.")

    candidatos_top10 = cand_agregado.head(10).copy()

    if not candidatos_top10.empty:
        candidatos_top10["rotulo_candidato"] = (
            candidatos_top10["nome_candidato"].str.title() + " (" + candidatos_top10["sigla_partido"] + ")"
        )
        candidatos_top10["status_eleito"] = np.where(
            candidatos_top10["sucesso"] == 1,
            "Eleito",
            "Não Eleito",
        )

        # Mapa de cores contrastante para Eleito vs Não Eleito
        mapa_cores = {"Eleito": "#10B981", "Não Eleito": "#3B82F6"}

        fig_candidatos = px.bar(
            candidatos_top10,
            x="rotulo_candidato",
            y="total_receita",
            color="status_eleito",
            color_discrete_map=mapa_cores,
            labels={
                "rotulo_candidato": "Candidato",
                "total_receita": "Receita Total (R$)",
                "status_eleito": "Situação",
            },
            custom_data=["cargo", "situacao"],
        )

        fig_candidatos.update_layout(
            xaxis={"tickangle": -35, "title": ""},
            yaxis={"title": "Receita Total (R$)"},
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=20, t=40, b=60),
            height=460,
        )

        fig_candidatos.update_traces(
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Cargo: %{customdata[0]}<br>"
                "Situação TSE: %{customdata[1]}<br>"
                "Receita Total: R$ %{y:,.2f}<extra></extra>"
            ),
            texttemplate="R$ %{y:,.0f}",
            textposition="outside",
        )

        st.plotly_chart(fig_candidatos, use_container_width=True)
    else:
        st.info("Sem dados de candidatos no filtro ativo.")

st.markdown("---")

# ==============================================================================
# SEÇÃO 3: HISTOGRAMA DE DISTRIBUIÇÃO DO VOLUME ARRECADADO (LOGARÍTMICA)
# ==============================================================================
st.subheader("📈 Distribuição do Volume Arrecadado (Escala Logarítmica)")
st.markdown(
    """
    A distribuição financeira de campanhas caracteriza-se por extrema assimetria.
    A escala logarítmica permite evidenciar como a grande massa de candidaturas
    opera com recursos modestos, enquanto uma fração ínfima atinge cifras milionárias.
    """
)

# Filtra apenas candidatos com receita positiva para viabilizar escala logarítmica
cand_positivos = cand_agregado[cand_agregado["total_receita"] > 0].copy()

if not cand_positivos.empty:
    valores = cand_positivos["total_receita"].values.astype(float)
    mediana_receita = float(np.median(valores))
    media_receita = float(np.mean(valores))
    max_receita = float(np.max(valores))

    log_valores = np.log10(valores)
    min_log = float(log_valores.min())
    max_log = float(log_valores.max())

    if min_log == max_log:
        min_log -= 0.5
        max_log += 0.5

    # Número adaptativo de bins com base no tamanho amostral
    num_bins = min(35, max(5, len(valores) // 10)) if len(valores) >= 10 else max(1, len(valores))
    bins = np.linspace(min_log, max_log, num_bins + 1)
    counts, bin_edges = np.histogram(log_valores, bins=bins)

    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bar_width = (bin_edges[1] - bin_edges[0]) * 0.88

    faixa_inicio = 10.0 ** bin_edges[:-1]
    faixa_fim = 10.0 ** bin_edges[1:]
    perc_faixa = (counts / max(1, len(valores))) * 100.0

    customdata = np.column_stack((faixa_inicio, faixa_fim, perc_faixa))

    # Ticks amigáveis em potências de 10
    p_min = int(np.floor(min_log))
    p_max = int(np.ceil(max_log))
    tickvals = list(range(p_min, p_max + 1))

    def formatar_rotulo_tick(p: int) -> str:
        val = 10.0 ** p
        if val >= 1_000_000:
            return f"R$ {val/1_000_000:.0f}M"
        if val >= 1_000:
            return f"R$ {val/1_000:.0f}k"
        if val >= 1.0:
            return f"R$ {val:.0f}"
        return f"R$ {val:.2f}".replace(".", ",")

    ticktext = [formatar_rotulo_tick(p) for p in tickvals]

    fig_hist = go.Figure(
        data=[
            go.Bar(
                x=bin_centers,
                y=counts,
                width=bar_width,
                marker=dict(
                    color="#2563EB",
                    line=dict(color="#1D4ED8", width=1),
                ),
                customdata=customdata,
                hovertemplate=(
                    "<b>Faixa de Receita:</b> R$ %{customdata[0]:,.2f} a R$ %{customdata[1]:,.2f}<br>"
                    "<b>Candidatos:</b> %{y:,}<br>"
                    "<b>Participação:</b> %{customdata[2]:.2f}%<extra></extra>"
                ),
            )
        ]
    )

    # Linha vertical indicadora da mediana
    fig_hist.add_vline(
        x=np.log10(mediana_receita),
        line_width=2,
        line_dash="dash",
        line_color="#F59E0B",
        annotation_text=f"Mediana: {formatar_moeda(mediana_receita)}",
        annotation_position="top left",
    )

    # Linha vertical indicadora da média
    fig_hist.add_vline(
        x=np.log10(media_receita),
        line_width=2,
        line_dash="dot",
        line_color="#EF4444",
        annotation_text=f"Média: {formatar_moeda(media_receita)}",
        annotation_position="top right",
    )

    fig_hist.update_layout(
        xaxis=dict(
            title="Receita Total Arrecadada por Candidato (R$ - Escala Logarítmica)",
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
            showgrid=True,
        ),
        yaxis=dict(title="Número de Candidatos", showgrid=True),
        margin=dict(l=20, r=20, t=30, b=40),
        height=450,
    )

    st.plotly_chart(fig_hist, use_container_width=True)

    # Métricas descritivas da distribuição
    col_dist1, col_dist2, col_dist3 = st.columns(3)
    with col_dist1:
        st.info(f"**Mediana (50%):** {formatar_moeda(mediana_receita)}")
    with col_dist2:
        st.info(f"**Média Aritmética:** {formatar_moeda(media_receita)}")
    with col_dist3:
        st.info(f"**Receita Máxima:** {formatar_moeda(max_receita)}")
else:
    st.info("Nenhuma candidatura com receita positiva para gerar o histograma.")
