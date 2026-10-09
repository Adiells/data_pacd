"""Componentes visuais e de navegação compartilhados para a interface Streamlit.

Inclui filtros globais de barra lateral com sincronização via st.session_state,
cartões de introdução conceitual, e formatadores de apresentação monetária e anonimização.
"""

from __future__ import annotations

import logging
from typing import Tuple

import pandas as pd
import streamlit as st

from src.data_loader import (
    listar_anos,
    listar_cargos,
    listar_partidos,
)

logger = logging.getLogger(__name__)


def formatar_moeda(valor: float) -> str:
    """Formata valor em formato de moeda brasileira (ex: R$ 1.250.300,50)."""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_numero(valor: int | float) -> str:
    """Formata número inteiro no padrão brasileiro com ponto como separador de milhar."""
    return f"{int(valor):,}".replace(",", ".")


def anonimizar_documento(doc: str | None) -> str:
    """Anonimiza os dígitos centrais de um CPF (11 dígitos) ou CNPJ (14 dígitos).

    Exemplos:
        CPF:  '03848051753'     -> '038.***.***-53'
        CNPJ: '70118955000123'  -> '70.***.***/****-23'

    Args:
        doc: String contendo o CPF ou CNPJ (formatado ou apenas dígitos).

    Returns:
        str: Documento com os blocos centrais mascarados.
    """
    if doc is None or pd.isna(doc):
        return "N/A"

    digitos = "".join(filter(str.isdigit, str(doc)))

    if len(digitos) == 11:
        # CPF: 3 primeiros e 2 últimos visíveis
        return f"{digitos[:3]}.***.***-{digitos[-2:]}"
    elif len(digitos) == 14:
        # CNPJ: 2 primeiros e 2 últimos visíveis
        return f"{digitos[:2]}.***.***/****-{digitos[-2:]}"
    elif len(digitos) >= 5:
        return f"{digitos[:2]}...{digitos[-2:]}"
    return "***"


def inicializar_session_state(df: Optional[pd.DataFrame] = None) -> None:
    """Inicializa os valores de filtros no st.session_state com todas as opções ativas."""
    if "filtro_anos" not in st.session_state:
        st.session_state["filtro_anos"] = listar_anos()

    if "filtro_uf" not in st.session_state:
        st.session_state["filtro_uf"] = "Todas as UFs (Brasil)"

    if "filtro_cargos" not in st.session_state:
        st.session_state["filtro_cargos"] = listar_cargos()

    if "filtro_partidos" not in st.session_state:
        st.session_state["filtro_partidos"] = listar_partidos()


def renderizar_sidebar(df: pd.DataFrame) -> pd.DataFrame:
    """Renderiza a barra lateral com introdução conceitual, hipóteses e filtros globais.

    Mantém os filtros sincronizados através do st.session_state para persistência
    automática durante a navegação entre subpáginas do Streamlit.

    Args:
        df: DataFrame completo consolidado.

    Returns:
        pd.DataFrame: DataFrame filtrado conforme seleção ativa nos controles.
    """
    from src.data_loader import listar_ufs, listar_tipos_receita

    inicializar_session_state(df)

    todos_anos = listar_anos()
    todos_cargos = listar_cargos()
    todos_partidos = listar_partidos()
    todas_ufs = ["Todas as UFs (Brasil)"] + listar_ufs()

    with st.sidebar:
        st.markdown(
            """
            <div style="text-align: center; margin-bottom: 1.5rem;">
                <h2 style="margin: 0; color: #1E3A8A;">🗳️ Observatório Eleitoral</h2>
                <span style="font-size: 0.85rem; color: #64748B;">
                    Análise Empírica do Financiamento Político no Brasil (27 UFs)
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("📌 Sobre o Projeto", expanded=False):
            st.markdown(
                """
                Plataforma analítica nacional para investigar a mecânica, custos e influências
                do financiamento de campanhas eleitorais em todo o Brasil (27 UFs, 2018 a 2024,
                cruzamento TSE + QSA + Fornecedores).
                """
            )

        with st.expander("🎯 Problema de Pesquisa", expanded=False):
            st.markdown(
                """
                * Qual o impacto real do volume financeiro no sucesso eleitoral?
                * Como o capital de campanha se distribui entre os estados e partidos?
                * Há sobreposição entre doadores e fornecedores contratados (porta giratória)?
                * Qual o peso do autofinanciamento e dos fundos públicos?
                """
            )

        with st.expander("💡 Hipóteses Investigadas", expanded=False):
            st.markdown(
                """
                * **H1 (Plutocracia):** Top 10% mais financiados concentram vitórias.
                * **H2 (Concentração):** Distribuição segue lei de potência assimétrica.
                * **H3 (Porta Giratória):** Recursos de campanha retornam a doadores/fornecedores.
                * **H4 (Geografia & Federalismo):** Disparidades de custo de voto entre UFs.
                * **H5 (Autofinanciamento):** Investimento do próprio bolso alavanca viabilidade.
                """
            )

        st.markdown("---")
        st.subheader("🔍 Filtros Globais")

        # 1. Filtro de UF (Visão Nacional ou Estado Específico)
        uf_atual = st.session_state.get("filtro_uf", "Todas as UFs (Brasil)")
        idx_uf = todas_ufs.index(uf_atual) if uf_atual in todas_ufs else 0
        uf_selecionada = st.selectbox(
            "📍 Âmbito Geográfico (UF)",
            options=todas_ufs,
            index=idx_uf,
            help="Selecione 'Todas as UFs (Brasil)' para a visão nacional ou um estado específico.",
        )
        st.session_state["filtro_uf"] = uf_selecionada

        # Sanitização dos defaults para evitar falhas caso a lista de opções mude
        def_anos = [a for a in st.session_state["filtro_anos"] if a in todos_anos]
        def_cargos = [c for c in st.session_state["filtro_cargos"] if c in todos_cargos]
        def_partidos = [p for p in st.session_state["filtro_partidos"] if p in todos_partidos]

        # 2. Filtro de Ano
        anos_selecionados = st.multiselect(
            "Ano da Eleição",
            options=todos_anos,
            default=def_anos,
            help="Selecione um ou mais anos eleitorais para analisar.",
        )
        st.session_state["filtro_anos"] = anos_selecionados

        # 3. Filtro de Cargo
        cargos_selecionados = st.multiselect(
            "Cargo em Disputa",
            options=todos_cargos,
            default=def_cargos,
            help="Filtre por cargos específicos (majoritários ou proporcionais).",
        )
        st.session_state["filtro_cargos"] = cargos_selecionados

        # 4. Filtro de Partido
        partidos_selecionados = st.multiselect(
            "Partido Político",
            options=todos_partidos,
            default=def_partidos,
            help="Filtre pelas siglas das legendas partidárias.",
        )
        st.session_state["filtro_partidos"] = partidos_selecionados

        # Botão para restaurar todos os filtros
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Selecionar Todos", use_container_width=True):
                st.session_state["filtro_anos"] = todos_anos
                st.session_state["filtro_uf"] = "Todas as UFs (Brasil)"
                st.session_state["filtro_cargos"] = todos_cargos
                st.session_state["filtro_partidos"] = todos_partidos
                st.rerun()

        with col_btn2:
            if st.button("Limpar Filtros", use_container_width=True):
                st.session_state["filtro_anos"] = []
                st.session_state["filtro_cargos"] = []
                st.session_state["filtro_partidos"] = []
                st.rerun()

        st.markdown("---")

    # Aplicação dos filtros no DataFrame
    df_filtrado = df.copy()

    # Filtro de UF
    if uf_selecionada and uf_selecionada != "Todas as UFs (Brasil)":
        if "uf_candidato" in df_filtrado.columns:
            df_filtrado = df_filtrado[df_filtrado["uf_candidato"].astype(str).str.upper() == uf_selecionada.upper()]

    # Filtro de Ano (compatível com string ou numérico)
    if anos_selecionados:
        anos_str = [str(a) for a in anos_selecionados]
        df_filtrado = df_filtrado[df_filtrado["ano"].astype(str).isin(anos_str)]
    else:
        df_filtrado = df_filtrado.iloc[0:0]

    # Filtro de Cargo
    if cargos_selecionados:
        cargos_limpos = [str(c).upper().strip() for c in cargos_selecionados]
        df_filtrado = df_filtrado[df_filtrado["cargo"].astype(str).str.upper().str.strip().isin(cargos_limpos)]
    else:
        df_filtrado = df_filtrado.iloc[0:0]

    # Filtro de Partido
    if partidos_selecionados:
        partidos_limpos = [str(p).upper().strip() for p in partidos_selecionados]
        df_filtrado = df_filtrado[df_filtrado["sigla_partido"].astype(str).str.upper().str.strip().isin(partidos_limpos)]
    else:
        df_filtrado = df_filtrado.iloc[0:0]

    # Indicador de registros filtrados na barra lateral
    with st.sidebar:
        percentual = (len(df_filtrado) / len(df) * 100.0) if len(df) > 0 else 0.0
        st.caption(
            f"📊 **{formatar_numero(len(df_filtrado))}** de **{formatar_numero(len(df))}** "
            f"registros ({percentual:.1f}% da base nacional)"
        )

    return df_filtrado

