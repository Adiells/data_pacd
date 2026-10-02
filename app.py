"""Página principal: Observatório do Financiamento Eleitoral.

Configura a aplicação, inicializa o estado de sessão, exibe a introdução
conceitual da pesquisa e gerencia os filtros globais da plataforma.
"""

from __future__ import annotations

import streamlit as st

# 1. Configuração inicial obrigatória da página
st.set_page_config(
    page_title="Observatório do Financiamento Eleitoral",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.data_loader import carregar_dados
from src.ui_components import (
    formatar_moeda,
    formatar_numero,
    renderizar_sidebar,
)

# 2. Carregamento dos dados com cache de alta performance
df_completo = carregar_dados()

# 3. Renderização da barra lateral com filtros sincronizados no session_state
df_filtrado = renderizar_sidebar(df_completo)

# 4. Conteúdo principal da página inicial
st.title("🗳️ Observatório do Financiamento Eleitoral")
st.markdown(
    """
    **Plataforma de inteligência analítica e investigação quantitativa sobre a influência
    do capital nas eleições do estado da Paraíba (TSE + QSA).**
    """
)

# Badges informativos
st.markdown(
    """
    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1.5rem;">
        <span style="background: #EEF2FF; color: #4338CA; padding: 0.3rem 0.8rem; border-radius: 9999px; font-size: 0.85rem; font-weight: 600;">
            🏛️ Dados Oficiais TSE
        </span>
        <span style="background: #ECFDF5; color: #047857; padding: 0.3rem 0.8rem; border-radius: 9999px; font-size: 0.85rem; font-weight: 600;">
            ⚡ Engine DuckDB + Parquet
        </span>
        <span style="background: #FEF3C7; color: #B45309; padding: 0.3rem 0.8rem; border-radius: 9999px; font-size: 0.85rem; font-weight: 600;">
            📍 Recorte Estadual (PB)
        </span>
        <span style="background: #F3F4F6; color: #374151; padding: 0.3rem 0.8rem; border-radius: 9999px; font-size: 0.85rem; font-weight: 600;">
            📅 Cobertura: 2018 a 2024
        </span>
    </div>
    """,
    unsafe_allow_html=True,
)

# Visão rápida dos dados selecionados
st.markdown("### 📊 Panorama da Seleção Ativa")
col1, col2, col3, col4 = st.columns(4)

total_receita_filtro = df_filtrado["valor_receita"].sum() if not df_filtrado.empty else 0.0
total_candidatos_filtro = df_filtrado["cpf_candidato"].nunique() if not df_filtrado.empty else 0
total_doadores_filtro = df_filtrado["cpf_cnpj_doador"].nunique() if not df_filtrado.empty else 0
total_transacoes = len(df_filtrado)

with col1:
    st.metric(
        label="Volume Financeiro Ativo",
        value=formatar_moeda(total_receita_filtro),
        help="Soma de todas as doações recebidas no recorte dos filtros ativos.",
    )

with col2:
    st.metric(
        label="Candidaturas no Recorte",
        value=formatar_numero(total_candidatos_filtro),
        help="Quantidade única de candidatos (CPFs) no filtro atual.",
    )

with col3:
    st.metric(
        label="Doadores no Recorte",
        value=formatar_numero(total_doadores_filtro),
        help="Quantidade única de doadores (CPFs/CNPJs) que aportaram recursos.",
    )

with col4:
    st.metric(
        label="Transações Registradas",
        value=formatar_numero(total_transacoes),
        help="Total de registros de doações filtrados.",
    )

st.markdown("---")

# Seções temáticas de apresentação
col_left, col_right = st.columns([1.1, 0.9])

with col_left:
    st.markdown("### 🎯 O Problema de Pesquisa")
    st.markdown(
        """
        O financiamento de campanhas eleitorais é um dos principais determinantes da
        isonomia e da competitividade democrática. Esta plataforma foi concebida para
        responder empiricamente às seguintes indagações:

        1. **Concentração Oligárquica:** Até que ponto o capital eleitoral é monopolizado
           por um grupo restrito de candidaturas de elite?
        2. **Retorno do Investimento:** Qual é o custo financeiro real de cada voto obtido
           pelos candidatos em diferentes cargos?
        3. **Relações de Conflito de Interesse:** Há repasses diretos de campanhas a
           fornecedores que atuaram concomitantemente como financiadores (*porta giratória*)?
        4. **Geopolítica do Financiamento:** Quais municípios e regiões exportam ou importam
           capital de campanha eleitoral?
        """
    )

with col_right:
    st.markdown("### 💡 Hipóteses Científicas Investigadas")
    st.markdown(
        """
        * **H1 — Plutocracia Eleitoral:** Candidatos situados no decil superior (Top 10%)
          de receita concentram desproporcionalmente as vitórias eleitorais.
        * **H2 — Assimetria de Pareto:** A distribuição da receita eleitoral segue uma lei de
          potência acentuada, com desvio padrão expressivamente maior que a mediana.
        * **H3 — Efeito Porta Giratória:** Parte relevante dos recursos declarados retorna
          para a mesma pessoa física/jurídica sob a rubrica de prestação de serviços.
        * **H4 — Endogeneidade Geográfica:** Campanhas municipais são fortemente
          autofinanciadas por capital local, enquanto pleitos majoritários atraem capital exógeno.
        """
    )

st.markdown("---")

# Guia de Navegação
st.markdown("### 🧭 Módulos Disponíveis para Navegação")
nav1, nav2, nav3 = st.columns(3)

with nav1:
    st.markdown(
        """
        <div style="padding: 1.2rem; border: 1px solid #E2E8F0; border-radius: 8px; background: #F8FAFC; min-height: 180px;">
            <h4 style="margin: 0 0 0.5rem 0; color: #1E293B;">📊 1. Visão Geral</h4>
            <p style="margin: 0; color: #64748B; font-size: 0.9rem;">
                Explore macroindicadores, maiores doadores com CPF anonimizado, candidatos recordistas
                e a distribuição de capital em escala logarítmica.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Acessar Visão Geral ➡️", key="btn_nav_1", use_container_width=True):
        st.switch_page("pages/1_visao_geral.py")

with nav2:
    st.markdown(
        """
        <div style="padding: 1.2rem; border: 1px solid #E2E8F0; border-radius: 8px; background: #F8FAFC; min-height: 180px;">
            <h4 style="margin: 0 0 0.5rem 0; color: #1E293B;">🗳️ 2. Custo do Voto (H1)</h4>
            <p style="margin: 0; color: #64748B; font-size: 0.9rem;">
                Investigue o piso de viabilidade eleitoral (teto de vidro), sumário estatístico e dispersão
                votos vs. receita com teste de significância.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Acessar Custo do Voto ➡️", key="btn_nav_2", use_container_width=True):
        st.switch_page("pages/2_custo_do_voto.py")

with nav3:
    st.markdown(
        """
        <div style="padding: 1.2rem; border: 1px solid #E2E8F0; border-radius: 8px; background: #F8FAFC; min-height: 180px;">
            <h4 style="margin: 0 0 0.5rem 0; color: #1E293B;">🔄 3. Porta Giratória (H2/H3)</h4>
            <p style="margin: 0; color: #64748B; font-size: 0.9rem;">
                Rastreie o retorno de doações via contratação de fornecedores (QSA / CNPJ Básico)
                com Diagrama Sankey e taxas de retorno.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Acessar Porta Giratória ➡️", key="btn_nav_3", use_container_width=True):
        st.switch_page("pages/3_porta_giratoria.py")

st.markdown("---")
st.caption("💡 Os filtros selecionados na barra lateral permanecem ativos durante a navegação entre todas as páginas.")
