"""Módulo de visualização geoespacial e mapas de calor (heatmaps) do Brasil.

Fornece funções com cache inteligente para carregamento de malhas cartográficas (GeoJSON)
e geração de mapas coropléticos interativos de calor para as 27 Unidades Federativas.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GEOJSON_PATH = PROJECT_ROOT / "data" / "geo" / "brazil-states.geojson"

NOMES_ESTADOS: Dict[str, str] = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AM": "Amazonas",
    "AP": "Amapá",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul",
    "MT": "Mato Grosso",
    "PA": "Pará",
    "PB": "Paraíba",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "PR": "Paraná",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RO": "Rondônia",
    "RR": "Roraima",
    "RS": "Rio Grande do Sul",
    "SC": "Santa Catarina",
    "SE": "Sergipe",
    "SP": "São Paulo",
    "TO": "Tocantins",
}

TODAS_UFS = sorted(list(NOMES_ESTADOS.keys()))


def carregar_geojson_brasil() -> Dict[str, Any]:
    """Carrega a malha vetorial GeoJSON oficial dos 27 estados brasileiros com cache.

    Returns:
        dict: Estrutura GeoJSON contendo polígonos das 27 UFs.
    """
    if not GEOJSON_PATH.exists():
        logger.error("Arquivo GeoJSON não encontrado em '%s'", GEOJSON_PATH)
        return {}

    try:
        with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Erro ao carregar GeoJSON de estados: %s", exc)
        return {}


def agregar_dados_por_uf(df: pd.DataFrame) -> pd.DataFrame:
    """Consolida as principais métricas eleitorais e de financiamento por UF.

    Args:
        df: DataFrame de doações ou candidaturas.

    Returns:
        pd.DataFrame: DataFrame contendo todas as 27 UFs com agregações.
    """
    if df.empty or "uf_candidato" not in df.columns:
        df_base = pd.DataFrame({"uf_candidato": TODAS_UFS})
        df_base["total_arrecadado"] = 0.0
        df_base["total_candidatos"] = 0
        df_base["total_doadores"] = 0
        df_base["total_doacoes"] = 0
        df_base["custo_mediano_voto"] = 0.0
        df_base["pct_nacional"] = 0.0
        df_base["nome_estado"] = df_base["uf_candidato"].map(NOMES_ESTADOS)
        return df_base

    # Agregação básica
    agrupado = (
        df.groupby("uf_candidato", as_index=False)
        .agg(
            total_arrecadado=("valor_receita", "sum") if "valor_receita" in df.columns else ("total_receita", "sum"),
            total_candidatos=("cpf_candidato", "nunique"),
            total_doadores=("cpf_cnpj_doador", "nunique") if "cpf_cnpj_doador" in df.columns else ("cpf_candidato", "nunique"),
            total_doacoes=("valor_receita", "count") if "valor_receita" in df.columns else ("cpf_candidato", "count"),
        )
    )

    # Custo mediano do voto se disponível
    if "total_votos" in df.columns and "valor_receita" in df.columns:
        cand = (
            df.groupby(["cpf_candidato", "uf_candidato"], as_index=False)
            .agg(
                total_rec=("valor_receita", "sum"),
                total_votos=("total_votos", "max"),
            )
        )
        cand["custo_voto"] = np.where(
            cand["total_votos"] > 0,
            cand["total_rec"] / cand["total_votos"],
            0.0,
        )
        cand_positivos = cand[cand["custo_voto"] > 0]
        custo_uf = (
            cand_positivos.groupby("uf_candidato", as_index=False)["custo_voto"]
            .median()
            .rename(columns={"custo_voto": "custo_mediano_voto"})
        )
        agrupado = agrupado.merge(custo_uf, on="uf_candidato", how="left")
    elif "custo_voto" in df.columns:
        cand_positivos = df[df["custo_voto"] > 0]
        custo_uf = (
            cand_positivos.groupby("uf_candidato", as_index=False)["custo_voto"]
            .median()
            .rename(columns={"custo_voto": "custo_mediano_voto"})
        )
        agrupado = agrupado.merge(custo_uf, on="uf_candidato", how="left")
    else:
        agrupado["custo_mediano_voto"] = 0.0

    agrupado["custo_mediano_voto"] = agrupado["custo_mediano_voto"].fillna(0.0)

    # Garante presença de todas as 27 UFs para renderização geográfica completa
    df_base = pd.DataFrame({"uf_candidato": TODAS_UFS})
    df_completo = df_base.merge(agrupado, on="uf_candidato", how="left").fillna(0.0)

    total_nac = df_completo["total_arrecadado"].sum()
    df_completo["pct_nacional"] = np.where(
        total_nac > 0,
        (df_completo["total_arrecadado"] / total_nac) * 100.0,
        0.0,
    )
    df_completo["nome_estado"] = df_completo["uf_candidato"].map(NOMES_ESTADOS).fillna(df_completo["uf_candidato"])

    return df_completo


def gerar_heatmap_brasil(
    df: pd.DataFrame,
    metrica: str = "total_arrecadado",
    altura: int = 540,
) -> go.Figure:
    """Gera o mapa coroplético (heatmap) do Brasil com as 27 UFs.

    Args:
        df: DataFrame de dados eleitorais.
        metrica: Coluna alvo ('total_arrecadado', 'total_candidatos',
                 'total_doadores' ou 'custo_mediano_voto').
        altura: Altura em pixels do gráfico.

    Returns:
        go.Figure: Figura interativa Plotly com o mapa de calor do Brasil.
    """
    geojson = carregar_geojson_brasil()
    df_uf = agregar_dados_por_uf(df)

    config_metricas = {
        "total_arrecadado": {
            "titulo": "Volume Arrecadado",
            "escala": "YlOrRd",
            "prefixo": "R$ ",
            "format": ":,.2f",
            "rotulo_barra": "Total (R$)",
        },
        "total_candidatos": {
            "titulo": "Quantidade de Candidatos",
            "escala": "Blues",
            "prefixo": "",
            "format": ":,.0f",
            "rotulo_barra": "Candidatos",
        },
        "total_doadores": {
            "titulo": "Doadores Únicos (CPFs)",
            "escala": "Greens",
            "prefixo": "",
            "format": ":,.0f",
            "rotulo_barra": "Doadores",
        },
        "custo_mediano_voto": {
            "titulo": "Custo Mediano do Voto",
            "escala": "Purples",
            "prefixo": "R$ ",
            "format": ":,.2f",
            "rotulo_barra": "R$/voto",
        },
    }

    cfg = config_metricas.get(metrica, config_metricas["total_arrecadado"])

    if not geojson:
        # Fallback gracioso se o GeoJSON falhar ao carregar
        fig_fallback = px.bar(
            df_uf.sort_values(by=metrica, ascending=True),
            x=metrica,
            y="uf_candidato",
            orientation="h",
            color=metrica,
            color_continuous_scale=cfg["escala"],
            title=f"Distribuição Federativa: {cfg['titulo']}",
        )
        fig_fallback.update_layout(height=altura)
        return fig_fallback

    fig = px.choropleth(
        df_uf,
        geojson=geojson,
        locations="uf_candidato",
        featureidkey="properties.sigla",
        color=metrica,
        color_continuous_scale=cfg["escala"],
        custom_data=[
            "nome_estado",
            "total_arrecadado",
            "total_candidatos",
            "total_doadores",
            "pct_nacional",
            "custo_mediano_voto",
        ],
    )

    fig.update_geos(
        fitbounds="locations",
        visible=False,
        bgcolor="rgba(0,0,0,0)",
    )

    fig.update_traces(
        marker_line_width=1.0,
        marker_line_color="#4B5563",
        hovertemplate=(
            "<b>%{customdata[0]} (%{location})</b><br><br>"
            "💰 <b>Arrecadação:</b> R$ %{customdata[1]:,.2f}<br>"
            "👥 <b>Candidatos:</b> %{customdata[2]:,.0f}<br>"
            "🤝 <b>Doadores Únicos:</b> %{customdata[3]:,.0f}<br>"
            "🗳️ <b>Custo Mediano:</b> R$ %{customdata[5]:,.2f}/voto<br>"
            "📊 <b>Participação Nacional:</b> %{customdata[4]:.2f}%<br>"
            "<extra></extra>"
        ),
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=10),
        height=altura,
        coloraxis_colorbar=dict(
            title=cfg["rotulo_barra"],
            tickprefix=cfg["prefixo"],
            len=0.75,
            thickness=16,
            yanchor="middle",
            y=0.5,
        ),
    )

    return fig
