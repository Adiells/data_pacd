"""Página de Rastreamento de Porta Giratória e Cruzamento QSA (Hipótese H2).

Identifica conexões entre doadores de campanha e fornecedores contratados,
mapeando a triangulação de recursos via CNPJ Básico e o retorno financeiro às empresas.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 1. Configuração inicial da página
st.set_page_config(
    page_title="Porta Giratória & QSA | Observatório Eleitoral",
    page_icon="🔄",
    layout="wide",
)

from src.data_loader import carregar_dados
from src.metrics import identificar_porta_giratoria
from src.ui_components import (
    anonimizar_documento,
    formatar_moeda,
    formatar_numero,
    renderizar_sidebar,
)

logger = logging.getLogger(__name__)

# 2. Carregamento dos dados
df_completo = carregar_dados()

# 3. Barra lateral com filtros globais sincronizados
df_filtrado = renderizar_sidebar(df_completo)

# 4. Cabeçalho e Contextualização
st.title("🔄 Efeito Porta Giratória & Cruzamento com o QSA")
st.markdown(
    """
    > **Hipótese H2 / H3 (Triangulação Empresarial):**
    > *"Recursos doados por pessoas físicas retornam a pessoas jurídicas ligadas ao próprio
    > doador (ou a ele próprio) sob a rubrica de prestação de serviços eleitorais, contornando
    > a proibição do STF a doações empresariais diretas."*
    """
)

# Detecção dos registros com efeito porta giratória (doador = fornecedor)
df_porta = identificar_porta_giratoria(df_filtrado)

# Se o filtro global esvaziar a porta giratória, oferece opção de ver a base geral
if df_porta.empty:
    st.warning(
        "⚠️ Nenhuma ocorrência de porta giratória encontrada para o recorte de filtros ativo. "
        "Experimente ampliar os filtros de Ano, Cargo ou Partido na barra lateral."
    )
    if st.button("Restaurar para Toda a Base de Dados"):
        df_porta = identificar_porta_giratoria(df_completo)
        df_filtrado = df_completo
    else:
        st.stop()

# ==============================================================================
# SEÇÃO 1: KPIS ESTRATÉGICOS
# ==============================================================================
st.markdown("### 📌 Indicadores do Efeito Porta Giratória")

# 1. Volume total detectado em retorno
volume_total_retorno = float(df_porta["valor_recebido_como_fornecedor"].sum())

# 2. Quantidade de campanhas com ocorrência
qtd_campanhas = int(df_porta["cpf_candidato"].nunique())

# 3. Maior taxa de retorno individual
maior_taxa_retorno = float(df_porta["taxa_retorno"].max()) if not df_porta.empty else 0.0

col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)

with col_kpi1:
    st.metric(
        label="Volume Total em Retorno",
        value=formatar_moeda(volume_total_retorno),
        help="Soma de todos os valores recebidos como fornecedor por pessoas/empresas que também doaram.",
    )

with col_kpi2:
    st.metric(
        label="Campanhas com Ocorrência",
        value=formatar_numero(qtd_campanhas),
        help="Número de candidaturas distintas onde foi identificado fluxo de doador-fornecedor.",
    )

with col_kpi3:
    st.metric(
        label="Maior Taxa de Retorno Individual",
        value=f"{maior_taxa_retorno:,.1f}%".replace(",", "X").replace(".", ",").replace("X", "."),
        help="Maior percentual identificado entre o valor recebido como fornecedor e o valor aportado como doação.",
    )

with col_kpi4:
    total_registros_pg = len(df_porta)
    st.metric(
        label="Transações Identificadas",
        value=formatar_numero(total_registros_pg),
        help="Contrato de prestação de serviços vinculado ao mesmo CPF/CNPJ de um doador da campanha.",
    )

st.markdown("---")

# ==============================================================================
# SEÇÃO 2: TABELA INTERATIVA COM SLIDER DE MARGEM DE RETORNO MÍNIMA
# ==============================================================================
st.subheader("📋 Relação de Doadores-Fornecedores Identificados")
st.caption(
    "Utilize o filtro deslizante para focar em casos com multiplicadores financeiros expressivos."
)

# Slider para Margem de Retorno Mínima (%)
max_taxa_slider = int(min(1000, max(100, maior_taxa_retorno)))
margem_minima = st.slider(
    "Margem de Retorno Mínima (%)",
    min_value=0,
    max_value=max_taxa_slider,
    value=0,
    step=10,
    help="Filtra transações onde a razão (Valor Fornecedor / Valor Doado) * 100 atinge ao menos este patamar.",
)

# Tratamento dos campos para apresentação canônica da tabela
df_tabela = df_porta.copy()

# Enriquecimento com CNPJ Básico vinculado e Razão Social
df_tabela["cnpj_basico_vinculado"] = df_tabela["cnpj_basico"].fillna("")
mask_cnpj_14 = (df_tabela["cnpj_basico_vinculado"] == "") & (
    df_tabela["cpf_cnpj_doador"].astype(str).str.len() == 14
)
df_tabela.loc[mask_cnpj_14, "cnpj_basico_vinculado"] = (
    df_tabela.loc[mask_cnpj_14, "cpf_cnpj_doador"].astype(str).str[:8]
)
df_tabela["cnpj_basico_vinculado"] = df_tabela["cnpj_basico_vinculado"].replace("", "Não informado")

# Saldo Líquido (Ganho da empresa/fornecedor sobre o que foi doado)
df_tabela["saldo_liquido"] = (
    df_tabela["valor_recebido_como_fornecedor"] - df_tabela["valor_receita"]
)

# Razão Social da Empresa
df_tabela["razao_social_empresa"] = df_tabela["nome_doador"].str.title()
mask_socio_qsa = (df_tabela["cpf_cnpj_doador"].astype(str).str.len() == 11) & (
    df_tabela["cnpj_basico"].notna()
)
df_tabela.loc[mask_socio_qsa, "razao_social_empresa"] = (
    "Empresa Vinculada ao QSA (CNPJ: " + df_tabela.loc[mask_socio_qsa, "cnpj_basico_vinculado"] + ")"
)

# Aplicação do filtro do slider
df_tabela_filtrada = df_tabela[df_tabela["taxa_retorno"] >= margem_minima].copy()

# Seleção e renomeação de colunas conforme solicitado
colunas_exibicao = {
    "nome_candidato": "Nome do Candidato",
    "sigla_partido": "Partido",
    "uf_candidato": "UF",
    "nome_doador": "Nome do Doador",
    "cnpj_basico_vinculado": "CNPJ Básico Vinculado",
    "valor_receita": "Valor Doado (R$)",
    "valor_recebido_como_fornecedor": "Valor Recebido como Fornecedor (R$)",
    "saldo_liquido": "Saldo Líquido (R$)",
    "taxa_retorno": "Taxa de Retorno (%)",
    "razao_social_empresa": "Razão Social da Empresa",
}

# Garante presença de uf_candidato se existir
colunas_presentes = [c for c in colunas_exibicao.keys() if c in df_tabela_filtrada.columns]
tabela_final = df_tabela_filtrada[colunas_presentes].rename(columns={c: colunas_exibicao[c] for c in colunas_presentes})


st.dataframe(
    tabela_final,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Valor Doado (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Valor Recebido como Fornecedor (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Saldo Líquido (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Taxa de Retorno (%)": st.column_config.NumberColumn(format="%.1f%%"),
    },
)

st.caption(
    f"Exibindo **{len(tabela_final)}** transações com taxa de retorno igual ou superior a **{margem_minima}%**."
)

st.markdown("---")

# ==============================================================================
# SEÇÃO 3: DIAGRAMA SANKEY & GRÁFICO BI-DIRECIONAL DO FLUXO DO DINHEIRO
# ==============================================================================
st.subheader("🔀 Rastreamento do Fluxo de Capital")
st.markdown(
    """
    Visualize o ciclo completo do capital:
    **Doador (Pessoa Física/Jurídica)** ➡️ **Campanha (Receita)** ➡️ **Empresa do Doador (Despesa / Fornecedor)**.
    """
)

aba_sankey, aba_bidirecional = st.tabs([
    "🌊 Diagrama Sankey (Fluxo de Capital)",
    "📊 Comparativo Bi-direcional (Aporte vs. Retorno)",
])

with aba_sankey:
    # Seleciona os casos mais representativos para não poluir o diagrama
    top_n_casos = min(12, len(df_tabela_filtrada))
    df_sankey = (
        df_tabela_filtrada.sort_values(by="valor_recebido_como_fornecedor", ascending=False)
        .head(top_n_casos)
        .copy()
    )

    if not df_sankey.empty:
        # Construção dos nós únicos do Sankey
        nomes_doadores = [f"Doador: {d[:22]}" for d in df_sankey["nome_doador"].str.title()]
        nomes_campanhas = [f"Campanha: {c[:22]}" for c in df_sankey["nome_candidato"].str.title()]
        nomes_empresas = [f"Retorno: {e[:22]}" for e in df_sankey["razao_social_empresa"].str.title()]

        lista_nos = []
        mapa_indices = {}

        def obter_indice_no(nome: str) -> int:
            if nome not in mapa_indices:
                mapa_indices[nome] = len(lista_nos)
                lista_nos.append(nome)
            return mapa_indices[nome]

        fontes, destinos, volumes = [], [], []

        for _, row in df_sankey.iterrows():
            d_label = f"Doador: {row['nome_doador'][:22].title()}"
            c_label = f"Campanha: {row['nome_candidato'][:22].title()}"
            e_label = f"Fornecedor: {row['razao_social_empresa'][:22].title()}"

            idx_d = obter_indice_no(d_label)
            idx_c = obter_indice_no(c_label)
            idx_e = obter_indice_no(e_label)

            # Fluxo 1: Doador -> Campanha
            fontes.append(idx_d)
            destinos.append(idx_c)
            volumes.append(max(1.0, float(row["valor_receita"])))

            # Fluxo 2: Campanha -> Empresa Fornecedora
            fontes.append(idx_c)
            destinos.append(idx_e)
            volumes.append(max(1.0, float(row["valor_recebido_como_fornecedor"])))

        # Paleta de cores moderna para o Sankey
        cores_nos = [
            "#3B82F6" if "Doador:" in n else ("#10B981" if "Campanha:" in n else "#EF4444")
            for n in lista_nos
        ]

        fig_sankey = go.Figure(
            data=[
                go.Sankey(
                    node=dict(
                        pad=18,
                        thickness=22,
                        line=dict(color="#1F2937", width=0.5),
                        label=lista_nos,
                        color=cores_nos,
                    ),
                    link=dict(
                        source=fontes,
                        target=destinos,
                        value=volumes,
                        color="rgba(148, 163, 184, 0.4)",
                    ),
                )
            ]
        )

        fig_sankey.update_layout(
            height=520,
            margin=dict(l=10, r=10, t=25, b=25),
        )

        st.plotly_chart(fig_sankey, use_container_width=True)
    else:
        st.info("Nenhuma transação atende aos critérios do slider de margem mínima.")

with aba_bidirecional:
    top_10_bi = (
        df_tabela_filtrada.sort_values(by="valor_recebido_como_fornecedor", ascending=False)
        .head(10)
        .copy()
    )

    if not top_10_bi.empty:
        rotulos_bi = [
            f"{c[:18]} (via {d[:15]})"
            for c, d in zip(top_10_bi["nome_candidato"].str.title(), top_10_bi["nome_doador"].str.title())
        ]

        fig_bi = go.Figure()

        # Barra do Valor Doado
        fig_bi.add_trace(
            go.Bar(
                y=rotulos_bi,
                x=top_10_bi["valor_receita"],
                name="Valor Doado (Receita)",
                orientation="h",
                marker_color="#3B82F6",
                hovertemplate="Valor Doado: R$ %{x:,.2f}<extra></extra>",
            )
        )

        # Barra do Valor Recebido como Fornecedor
        fig_bi.add_trace(
            go.Bar(
                y=rotulos_bi,
                x=top_10_bi["valor_recebido_como_fornecedor"],
                name="Valor Recebido (Fornecedor)",
                orientation="h",
                marker_color="#EF4444",
                hovertemplate="Valor como Fornecedor: R$ %{x:,.2f}<extra></extra>",
            )
        )

        fig_bi.update_layout(
            barmode="group",
            height=500,
            margin=dict(l=10, r=20, t=30, b=40),
            xaxis=dict(title="Volume Financeiro (R$)"),
            yaxis=dict(categoryorder="total ascending", title=""),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        st.plotly_chart(fig_bi, use_container_width=True)
    else:
        st.info("Sem dados suficientes para gerar o comparativo bi-direcional.")

st.markdown("---")

# ==============================================================================
# SEÇÃO 4: EXPLICAÇÃO METODOLÓGICA (EXPANDER)
# ==============================================================================
with st.expander("🔬 Metodologia: Como a Chave 'CNPJ Básico' Conecta Doações ao QSA", expanded=True):
    st.markdown(
        """
        ### 1. O Veto do STF e a Mudança Estrutural nas Campanhas
        Em 2015, no julgamento da **Ação Direta de Inconstitucionalidade (ADI) 4.650**, o Supremo Tribunal
        Federal julgou inconstitucionais as doações eleitorais por pessoas jurídicas. A partir dessa decisão,
        apenas **pessoas físicas**, o **Fundo Especial de Financiamento de Campanha (FEFC)** e o **Fundo Partidário**
        foram autorizados a aportar recursos em candidaturas.

        ### 2. A Mecânica da 'Porta Giratória' (Doador-Fornecedor)
        Para viabilizar a injeção ou recuperação de capital de campanha, emergiu a prática da porta giratória:
        1. **Doação como Pessoa Física:** O empresário, sócio ou executivo aporta recursos de seu patrimônio pessoal
           declarado na conta bancária eleitoral do candidato.
        2. **Contratação da Empresa:** Durante a campanha, a candidatura contrata para prestação de serviços
           (ex.: locação de veículos, gráficas, consultorias, eventos, transporte) a sociedade empresária pertencente
           ao próprio doador ou a seus familiares diretos.
        3. **Fechamento do Circuito:** O capital doado retorna à esfera patrimonial privada sob forma de receita
           operacional da empresa, muitas vezes com **taxas de retorno multiplicadoras** (> 100%), gerando saldo líquido positivo.

        ### 3. A Função do `CNPJ Básico` como Chave de Ligação
        * O **CNPJ Básico** corresponde aos **8 primeiros dígitos** de qualquer inscrição cadastral junto à Receita Federal
          (formato `XX.XXX.XXX`). Ele identifica a raiz da pessoa jurídica independentemente de ser matriz (`/0001`) ou filial.
        * Cruzando os dados do **Quadro de Sócios e Administradores (QSA)** da Receita Federal com as prestações de contas
          do TSE, o algoritmo identifica onde o CPF do doador é sócio-proprietário ou administrador de empresas que emitiram
          notas fiscais de prestação de serviços para a campanha, revelando o conflito de interesses financeiro.
        """
    )
