"""API FastAPI de alta performance para o Painel Eleitoral (PACD).

Serve dados analíticos agregados a partir do banco consolidado DuckDB/Parquet,
aplicando rigorosamente as travas eleitorais, higienização por Regex e zero conclusões.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.metrics import (
    analise_autofinanciamento,
    atribuir_status_eleitoral,
    calcular_custo_voto,
    calcular_sucesso_decil,
    identificar_porta_giratoria,
)

logger = logging.getLogger("pacd_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_PARQUET_PATH = Path("data/processed/base_consolidada_eleicoes.parquet")

app = FastAPI(
    title="PACD Electoral Analytics API",
    description="Backend API analítico para o Painel Eleitoral Brasileiro (2018-2024)",
    version="1.0.0",
)

# Habilita CORS irrestrito para desenvolvimento e consumo SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir a SPA na rota raiz
@app.get("/", include_in_schema=False)
def serve_spa():
    return FileResponse("frontend/index.html")


import threading

# Conexão DuckDB compartilhada em memória apontando para o arquivo parquet
conn = duckdb.connect(database=":memory:")
conn.execute(f"CREATE VIEW eleicoes AS SELECT * FROM '{BASE_PARQUET_PATH}'")

# Lock de concorrência para garantir operações thread-safe no DuckDB
db_lock = threading.Lock()


def query_df(sql: str, params: Optional[list[Any]] = None) -> pd.DataFrame:
    """Executa consulta e retorna DataFrame de forma estritamente thread-safe."""
    with db_lock:
        cursor = conn.cursor()
        try:
            if params is not None:
                return cursor.execute(sql, params).df()
            return cursor.execute(sql).df()
        finally:
            cursor.close()


def query_fetchall(sql: str, params: Optional[list[Any]] = None) -> list[Any]:
    """Executa consulta e retorna fetchall de forma estritamente thread-safe."""
    with db_lock:
        cursor = conn.cursor()
        try:
            if params is not None:
                return cursor.execute(sql, params).fetchall()
            return cursor.execute(sql).fetchall()
        finally:
            cursor.close()


def query_fetchone(sql: str, params: Optional[list[Any]] = None) -> Any:
    """Executa consulta e retorna fetchone de forma estritamente thread-safe."""
    with db_lock:
        cursor = conn.cursor()
        try:
            if params is not None:
                return cursor.execute(sql, params).fetchone()
            return cursor.execute(sql).fetchone()
        finally:
            cursor.close()


# ==============================================================================
# ENDPOINT: HEALTH CHECK
# ==============================================================================
@app.get("/health")
def health_check() -> Dict[str, str]:
    """Endpoint de verificação de integridade do serviço backend."""
    return {"status": "ok"}


def formatar_moeda(valor: float) -> str:
    """Formata valor em R$ monetário canônico."""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def construir_clausula_where(
    ano: Optional[int] = None,
    cargo: Optional[str] = None,
    uf: Optional[str] = None,
    partido: Optional[str] = None,
    municipio: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Gera cláusula WHERE parametrizada para consultas seguras no DuckDB."""
    condicoes = []
    params: list[Any] = []

    if isinstance(ano, (int, float)):
        condicoes.append("ano = ?")
        params.append(int(ano))
    if isinstance(cargo, str) and cargo.strip() and cargo.strip().upper() != "TODOS":
        condicoes.append("UPPER(cargo) = ?")
        params.append(cargo.strip().upper())
    if isinstance(uf, str) and uf.strip() and uf.strip().upper() != "TODAS":
        condicoes.append("UPPER(uf_candidato) = ?")
        params.append(uf.strip().upper())
    if isinstance(partido, str) and partido.strip() and partido.strip().upper() != "TODOS":
        condicoes.append("UPPER(sigla_partido) = ?")
        params.append(partido.strip().upper())
    if isinstance(municipio, str) and municipio.strip() and municipio.strip().upper() != "TODOS":
        condicoes.append("UPPER(municipio_candidato) = ?")
        params.append(municipio.strip().upper())

    clausula = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""
    return clausula, params


# ==============================================================================
# ENDPOINT: METADADOS E REGRAS DE FILTRO (PROMPT 2 / AGENTS.MD)
# ==============================================================================
@app.get("/api/meta/filtros")
def get_metadata_filtros() -> Dict[str, Any]:
    """Retorna metadados de filtros e regras eleitorais de negócio."""
    anos_raw = query_fetchall("SELECT DISTINCT ano FROM eleicoes ORDER BY ano")
    anos = [int(r[0]) for r in anos_raw if r[0] is not None]

    ufs_raw = query_fetchall("SELECT DISTINCT uf_candidato FROM eleicoes WHERE uf_candidato IS NOT NULL AND uf_candidato != '' ORDER BY uf_candidato")
    ufs = [str(r[0]).upper() for r in ufs_raw]

    partidos_raw = query_fetchall("SELECT DISTINCT sigla_partido FROM eleicoes WHERE sigla_partido IS NOT NULL AND sigla_partido != '' ORDER BY sigla_partido")
    partidos = [str(r[0]).upper() for r in partidos_raw]

    # Regras Estritas de Cargos por Ano (Prompt 2 e AGENTS.md):
    # 2018 e 2022 (Eleições Gerais): Presidente, Governador, Senador, Deputado Federal, Deputado Estadual, Deputado Distrital. Desativar Município.
    # 2020 e 2024 (Eleições Municipais): Prefeito, Vereador.
    cargos_por_ano = {
        2018: ["PRESIDENTE", "GOVERNADOR", "SENADOR", "DEPUTADO FEDERAL", "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL"],
        2022: ["PRESIDENTE", "GOVERNADOR", "SENADOR", "DEPUTADO FEDERAL", "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL"],
        2020: ["PREFEITO", "VEREADOR"],
        2024: ["PREFEITO", "VEREADOR"],
    }

    return {
        "anos": anos,
        "cargos_por_ano": cargos_por_ano,
        "ufs": ufs,
        "partidos": partidos,
    }


# ==============================================================================
# ENDPOINT: TOPO FIXO GLOBAL ("TUDO E TODOS" - IMUNE A FILTROS)
# ==============================================================================
@app.get("/api/global")
def get_global_metrics() -> Dict[str, Any]:
    """Retorna os dados consolidados de toda a base histórica (Bloco Superior Fixo)."""
    # 4 Indicadores Estratégicos Globais
    row_kpis = query_fetchone("""
        SELECT 
            COALESCE(SUM(valor_receita), 0.0) as volume_total,
            COUNT(DISTINCT cpf_candidato) as total_candidatos,
            COUNT(DISTINCT cpf_cnpj_doador) as total_doadores,
            COUNT(*) as total_transacoes
        FROM eleicoes
    """)
    if not row_kpis:
        row_kpis = (0.0, 0, 0, 0)

    # 1. Top 10 Doadores
    top_doadores = query_df("""
        SELECT 
            COALESCE(nome_doador, 'NÃO INFORMADO') as nome,
            SUM(valor_receita) as total
        FROM eleicoes
        WHERE nome_doador IS NOT NULL AND TRIM(nome_doador) != ''
        GROUP BY nome_doador
        ORDER BY total DESC
        LIMIT 10
    """).to_dict(orient="records")

    # 2. Top 10 Candidatos Mais Financiados
    top_candidatos = query_df("""
        SELECT 
            COALESCE(nome_candidato, 'NÃO INFORMADO') as nome,
            COALESCE(sigla_partido, '-') as partido,
            COALESCE(cargo, '-') as cargo,
            COALESCE(uf_candidato, '-') as uf,
            SUM(valor_receita) as total
        FROM eleicoes
        WHERE nome_candidato IS NOT NULL AND TRIM(nome_candidato) != ''
        GROUP BY cpf_candidato, nome_candidato, sigla_partido, cargo, uf_candidato
        ORDER BY total DESC
        LIMIT 10
    """).to_dict(orient="records")

    # 3. Distribuição do Volume Arrecadado (Escala Logarítmica - Bins de Histograma)
    df_receitas = query_df("""
        SELECT SUM(valor_receita) as total
        FROM eleicoes
        GROUP BY cpf_candidato
        HAVING SUM(valor_receita) > 0
    """)
    receitas_cand = df_receitas["total"].values if not df_receitas.empty else np.array([])

    if len(receitas_cand) > 0:
        log_vals = np.log10(receitas_cand)
        counts, bin_edges = np.histogram(log_vals, bins=15)
        distribuicao_log = [
            {
                "faixa_log": f"10^{bin_edges[i]:.1f} - 10^{bin_edges[i+1]:.1f}",
                "faixa_reais": f"R$ {10**bin_edges[i]:,.0f} a R$ {10**bin_edges[i+1]:,.0f}",
                "contagem": int(counts[i]),
            }
            for i in range(len(counts))
        ]
    else:
        distribuicao_log = []

    # 4. Autofinanciamento: Os Maiores Investidores da Própria Campanha
    top_autofinanciamento = query_df("""
        SELECT 
            COALESCE(nome_candidato, 'NÃO INFORMADO') as nome,
            COALESCE(sigla_partido, '-') as partido,
            COALESCE(cargo, '-') as cargo,
            COALESCE(uf_candidato, '-') as uf,
            SUM(valor_receita) as total_proprio
        FROM eleicoes
        WHERE autofinanciamento = 1
        GROUP BY cpf_candidato, nome_candidato, sigla_partido, cargo, uf_candidato
        ORDER BY total_proprio DESC
        LIMIT 10
    """).to_dict(orient="records")

    return {
        "kpis": {
            "volume_financeiro_ativo": float(row_kpis[0] or 0.0),
            "candidaturas_no_recorte": int(row_kpis[1] or 0),
            "doadores_no_recorte": int(row_kpis[2] or 0),
            "transacoes_registradas": int(row_kpis[3] or 0),
        },
        "graficos": {
            "top_10_doadores": top_doadores,
            "top_10_candidatos": top_candidatos,
            "distribuicao_log": distribuicao_log,
            "top_autofinanciamento": top_autofinanciamento,
        },
    }


# ==============================================================================
# ENDPOINT: VISÃO GERAL (PROMPT 1 + PROMPT 2 + PROMPT 3)
# ==============================================================================
@app.get("/api/visao-geral")
def get_visao_geral(
    ano: int = Query(..., description="Ano eleitoral obrigatório e específico (não acumular anos)"),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna dados da seção dinâmica Visão Geral para um ano eleitoral específico."""
    where, params = construir_clausula_where(ano=ano, cargo=cargo, uf=uf, partido=partido, municipio=municipio)

    # DataFrame filtrado
    df_filtrado = query_df(f"SELECT * FROM eleicoes {where}", params)

    if df_filtrado.empty:
        return {
            "kpis": {
                "total_arrecadado": 0.0,
                "num_candidatos": 0,
                "num_doadores": 0,
                "taxa_sucesso_decil": {"taxa_top10": 0.0, "taxa_bottom50": 0.0, "diferenca_sucesso": 0.0},
            },
            "top_10_doadores": [],
            "top_10_candidatos": [],
            "distribuicao_log": [],
            "panorama_uf": [],
            "ranking_estados": [],
            "origem_recursos": [],
        }

    # KPIs
    total_arrecadado = float(df_filtrado["valor_receita"].sum())
    num_candidatos = int(df_filtrado["cpf_candidato"].nunique())
    num_doadores = int(df_filtrado["cpf_cnpj_doador"].nunique())
    taxa_sucesso = calcular_sucesso_decil(df_filtrado)

    # 1. Top 10 Doadores
    top_doadores = (
        df_filtrado.groupby("nome_doador", as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"valor_receita": "total", "nome_doador": "nome"})
        .sort_values(by="total", ascending=False)
        .head(10)
        .to_dict(orient="records")
    )

    # 2. Top 10 Candidatos
    top_candidatos = (
        df_filtrado.groupby(["nome_candidato", "sigla_partido", "cargo"], as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"valor_receita": "total", "nome_candidato": "nome", "sigla_partido": "partido"})
        .sort_values(by="total", ascending=False)
        .head(10)
        .to_dict(orient="records")
    )

    # 3. Distribuição Log
    receitas_cand = df_filtrado.groupby("cpf_candidato")["valor_receita"].sum().values
    receitas_cand = receitas_cand[receitas_cand > 0]
    if len(receitas_cand) > 0:
        log_vals = np.log10(receitas_cand)
        counts, bin_edges = np.histogram(log_vals, bins=12)
        distribuicao_log = [
            {
                "faixa_reais": f"R$ {10**bin_edges[i]:,.0f} - {10**bin_edges[i+1]:,.0f}",
                "contagem": int(counts[i]),
            }
            for i in range(len(counts))
        ]
    else:
        distribuicao_log = []

    # 4. Panorama por UF / Mapa
    panorama_uf = (
        df_filtrado[df_filtrado["uf_candidato"].notna() & (df_filtrado["uf_candidato"] != "")]
        .groupby("uf_candidato", as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"valor_receita": "total", "uf_candidato": "uf"})
        .sort_values(by="total", ascending=False)
        .to_dict(orient="records")
    )

    # 5. Ranking Estados (Top 10)
    ranking_estados = [
        {"uf": str(r["uf"]), "total": float(r["total"])}
        for r in panorama_uf[:10]
    ]

    # 6. Composição por Origem do Recurso
    if "tipo_receita" in df_filtrado.columns:
        origem_recursos = (
            df_filtrado.groupby("tipo_receita", as_index=False)["valor_receita"]
            .sum()
            .rename(columns={"valor_receita": "total", "tipo_receita": "origem"})
            .sort_values(by="total", ascending=False)
            .to_dict(orient="records")
        )
    else:
        origem_recursos = []

    return {
        "kpis": {
            "total_arrecadado": total_arrecadado,
            "num_candidatos": num_candidatos,
            "num_doadores": num_doadores,
            "taxa_sucesso_decil": taxa_sucesso,
        },
        "top_10_doadores": top_doadores,
        "top_10_candidatos": top_candidatos,
        "distribuicao_log": distribuicao_log,
        "panorama_uf": panorama_uf,
        "ranking_estados": ranking_estados,
        "origem_recursos": origem_recursos,
    }


# ==============================================================================
# ENDPOINT: CUSTO DO VOTO (PROMPT 2 / AGENTS.MD - SCATTER ONLY 1 ANO + 1 CARGO)
# ==============================================================================
@app.get("/api/custo-do-voto")
def get_custo_do_voto(
    ano: int = Query(..., description="Ano eleitoral obrigatório"),
    cargo: str = Query(..., description="Cargo obrigatório específico"),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna dados de Custo do Voto (Scatter Plot). Exige obrigatoriamente 1 Ano E 1 Cargo."""
    if not cargo or not cargo.strip():
        raise HTTPException(
            status_code=400,
            detail="O módulo Custo do Voto exige a seleção obrigatória de 1 Cargo específico.",
        )

    where, params = construir_clausula_where(ano=ano, cargo=cargo, uf=uf, partido=partido)
    df_recorte = query_df(f"SELECT * FROM eleicoes {where}", params)

    if df_recorte.empty:
        return {
            "piso_viabilidade": 0.0,
            "pontos": [],
            "resumo": {
                "total_candidatos": 0,
                "total_eleitos": 0,
                "total_nao_eleitos": 0,
                "mediana_custo_voto": 0.0,
            },
        }

    # Agrupa por candidato e calcula custo por voto
    df_cand = calcular_custo_voto(df_recorte)
    df_cand = atribuir_status_eleitoral(df_cand)

    df_cand["status_eleicao"] = np.where(df_cand["eleito"] == 1, "Eleito", "Não Eleito")

    # Piso de viabilidade = menor receita positiva entre eleitos
    eleitos = df_cand[df_cand["eleito"] == 1]
    if not eleitos.empty and (eleitos["total_receita"] > 0).any():
        piso_viabilidade = float(eleitos.loc[eleitos["total_receita"] > 0, "total_receita"].min())
    else:
        piso_viabilidade = 0.0

    # Pontos para o Scatter Plot
    pontos = (
        df_cand[df_cand["total_votos"] > 0][
            ["cpf_candidato", "nome_candidato", "sigla_partido", "cargo", "total_votos", "total_receita", "custo_voto", "status_eleicao"]
        ]
        .rename(columns={"sigla_partido": "partido"})
        .to_dict(orient="records")
    )

    mediana_custo = float(df_cand.loc[df_cand["custo_voto"] > 0, "custo_voto"].median()) if (df_cand["custo_voto"] > 0).any() else 0.0

    return {
        "piso_viabilidade": piso_viabilidade,
        "pontos": pontos,
        "resumo": {
            "total_candidatos": len(df_cand),
            "total_eleitos": int(df_cand["eleito"].sum()),
            "total_nao_eleitos": int((df_cand["eleito"] == 0).sum()),
            "mediana_custo_voto": mediana_custo,
        },
    }


# ==============================================================================
# ENDPOINT: PORTA GIRATÓRIA (PROMPT 3 / AGENTS.MD - REGEX HIGIENIZADO)
# ==============================================================================
@app.get("/api/porta-giratoria")
def get_porta_giratoria(
    ano: Optional[int] = Query(None),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna análise de Porta Giratória expurgando repasses institucionais e aliados via Regex."""
    where, params = construir_clausula_where(ano=ano, cargo=cargo, uf=uf, partido=partido, municipio=municipio)
    df_raw = query_df(f"SELECT * FROM eleicoes {where}", params)

    if df_raw.empty:
        return {
            "kpis": {
                "volume_total_retorno": 0.0,
                "campanhas_com_ocorrencia": 0,
                "maior_taxa_retorno": 0.0,
                "transacoes_identificadas": 0,
            },
            "ranking_porta_giratoria": [],
            "comparativo_bidirecional": [],
        }

    # Aplica identificar_porta_giratoria (que executa a malha fina Regex)
    df_pg = identificar_porta_giratoria(df_raw)

    if df_pg.empty:
        return {
            "kpis": {
                "volume_total_retorno": 0.0,
                "campanhas_com_ocorrencia": 0,
                "maior_taxa_retorno": 0.0,
                "transacoes_identificadas": 0,
            },
            "ranking_porta_giratoria": [],
            "comparativo_bidirecional": [],
        }

    volume_retorno = float(df_pg["valor_recebido_como_fornecedor"].sum())
    campanhas = int(df_pg["cpf_candidato"].nunique())
    
    taxas_validas = df_pg["taxa_retorno"].replace([np.inf, -np.inf], np.nan).dropna()
    maior_taxa = float(taxas_validas.max()) if not taxas_validas.empty else 0.0
    if np.isnan(maior_taxa) or np.isinf(maior_taxa):
        maior_taxa = 0.0
    transacoes = len(df_pg)

    # Ranking Top 15 casos
    ranking_df = (
        df_pg.groupby(["nome_candidato", "sigla_partido", "nome_doador"], as_index=False)
        .agg(
            total_doado=("valor_receita", "sum"),
            total_fornecedor=("valor_recebido_como_fornecedor", "sum"),
            taxa_retorno=("taxa_retorno", "max"),
        )
        .sort_values(by="total_fornecedor", ascending=False)
        .head(15)
    )
    ranking_df["taxa_retorno"] = ranking_df["taxa_retorno"].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    ranking_df["nome_candidato"] = ranking_df["nome_candidato"].fillna("Não informado")
    ranking_df["sigla_partido"] = ranking_df["sigla_partido"].fillna("S/P")
    ranking_df["nome_doador"] = ranking_df["nome_doador"].fillna("Não informado")
    ranking = ranking_df.to_dict(orient="records")

    # Comparativo Bidirecional Top 10 por volume recebido
    comparativo_df = (
        df_pg.groupby("nome_doador", as_index=False)
        .agg(
            total_doado=("valor_receita", "sum"),
            total_fornecedor=("valor_recebido_como_fornecedor", "sum"),
        )
        .sort_values(by="total_fornecedor", ascending=False)
        .head(10)
        .rename(columns={"nome_doador": "entidade"})
    )
    comparativo_df["entidade"] = comparativo_df["entidade"].fillna("Não informado")
    comparativo = comparativo_df.to_dict(orient="records")

    return {
        "kpis": {
            "volume_total_retorno": volume_retorno,
            "campanhas_com_ocorrencia": campanhas,
            "maior_taxa_retorno": maior_taxa,
            "transacoes_identificadas": transacoes,
        },
        "ranking_porta_giratoria": ranking,
        "comparativo_bidirecional": comparativo,
    }


# ==============================================================================
# ENDPOINT: ORIGEM DOS RECURSOS & AUTOFINANCIAMENTO (PROMPT 3 / AGENTS.MD)
# ==============================================================================
@app.get("/api/origem-autofinanciamento")
def get_origem_autofinanciamento(
    ano: Optional[int] = Query(None),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna análise de origem de recursos e autofinanciamento com taxas de sucesso corrigidas."""
    where, params = construir_clausula_where(ano=ano, cargo=cargo, uf=uf, partido=partido, municipio=municipio)
    df_raw = query_df(f"SELECT * FROM eleicoes {where}", params)

    if df_raw.empty:
        return {
            "kpis": {
                "taxa_autofinanciamento": 0.0,
                "volume_autofinanciamento": 0.0,
                "volume_terceiros": 0.0,
                "taxa_sucesso_auto": 0.0,
                "taxa_sucesso_terceiros": 0.0,
            },
            "top_investidores_proprios": [],
            "evolucao_historica": [],
        }

    kpis_auto = analise_autofinanciamento(df_raw)

    # Maiores Investidores da Própria Campanha no recorte
    top_investidores_df = (
        df_raw[df_raw["autofinanciamento"] == 1]
        .groupby(["nome_candidato", "sigla_partido", "cargo"], as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"nome_candidato": "nome", "sigla_partido": "partido", "valor_receita": "total"})
        .sort_values(by="total", ascending=False)
        .head(10)
    )
    top_investidores_df["nome"] = top_investidores_df["nome"].fillna("Não informado")
    top_investidores_df["partido"] = top_investidores_df["partido"].fillna("S/P")
    top_investidores = top_investidores_df.to_dict(orient="records")

    # Evolução histórica do autofinanciamento
    evolucao = (
        df_raw.groupby(["ano", "autofinanciamento"], as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"valor_receita": "total"})
    )
    evolucao["tipo"] = np.where(evolucao["autofinanciamento"] == 1, "Recursos Próprios", "Terceiros")
    evolucao_records = evolucao[["ano", "tipo", "total"]].to_dict(orient="records")

    return {
        "kpis": kpis_auto,
        "top_investidores_proprios": top_investidores,
        "evolucao_historica": evolucao_records,
    }
