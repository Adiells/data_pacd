"""API FastAPI de alta performance para o Painel Eleitoral (PACD).

Serve dados analíticos agregados a partir do banco consolidado DuckDB/Parquet,
aplicando rigorosamente as travas eleitorais, higienização por Regex e zero conclusões.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
    version="1.1.0",
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
    apenas_privado: bool = False,
) -> tuple[str, list[Any]]:
    """Gera cláusula WHERE parametrizada para consultas seguras no DuckDB."""
    condicoes = ["1=1"]
    params: list[Any] = []

    if isinstance(ano, (int, float)):
        condicoes.append("ano = ?")
        params.append(int(ano))
    if isinstance(cargo, str) and cargo.strip() and cargo.strip().upper() != "TODOS":
        condicoes.append("UPPER(cargo) = ?")
        params.append(cargo.strip().upper())
    if uf:
        ufs_limpas = [u.strip().upper() for u in uf.split(',') if u.strip().upper() not in ('TODAS', '')]
        if ufs_limpas:
            placeholders = ", ".join(["?"] * len(ufs_limpas))
            condicoes.append(f"UPPER(uf_candidato) IN ({placeholders})")
            params.extend(ufs_limpas)
    if isinstance(partido, str) and partido.strip() and partido.strip().upper() != "TODOS":
        condicoes.append("UPPER(sigla_partido) = ?")
        params.append(partido.strip().upper())
    if isinstance(municipio, str) and municipio.strip() and municipio.strip().upper() != "TODOS":
        condicoes.append("UPPER(municipio_candidato) = ?")
        params.append(municipio.strip().upper())
    # Filtro Global On/Off: Somente Doações Privadas
    if apenas_privado:
        # Se categoria_recurso existir no parquet, usa direto; senão, aplica a exclusão por regex e CPF
        termos_excluir = r'DIRETORIO|DIRETÓRO|PARTIDO|ELEICAO|ELEIÇÃO|ELAICAO|ELAIÇÃO|CAMPANHA|COMITE|COMITÊ|FEDERACAO|FEDERAÇÃO|DIRECAO|DIREÇÃO|ORGAO|ÓRGÃO|FUNDO ESPECIAL|PROVISORIA|PROVISÓRIA|MUNICIPAL|ESTADUAL|NACIONAL'
        condicoes.append(f"(NOT regexp_matches(UPPER(COALESCE(nome_doador, '')), '{termos_excluir}') OR autofinanciamento = 1)")

    clausula = ("WHERE " + " AND ".join(condicoes)) 
    return clausula, params


# ==============================================================================
# ENDPOINT: METADADOS E REGRAS DE FILTRO (PROMPT 2 / AGENTS.MD)
# ==============================================================================
cache_filtros = {}

@app.get("/api/meta/filtros")
def get_metadata_filtros() -> Dict[str, Any]:
    """Retorna metadados de filtros e regras eleitorais de negócio."""

    if "dados_filtros" in cache_filtros:
        return cache_filtros["dados_filtros"]

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

    resultado_final = {
        "anos": anos,
        "cargos_por_ano": cargos_por_ano,
        "ufs": ufs,
        "partidos": partidos,
    }

    cache_filtros["dados_filtros"] = resultado_final
    return resultado_final


# ==============================================================================
# ENDPOINT: TOPO FIXO GLOBAL ("TUDO E TODOS" - IMUNE A FILTROS)
# ==============================================================================
cache_global= {}

@app.get("/api/global")
def get_global_metrics(apenas_privado: bool = Query(False) )-> Dict[str, Any]:
    """Retorna os dados consolidados de toda a base histórica (Bloco Superior Fixo)."""

    if apenas_privado in cache_global:
        return cache_global[apenas_privado]
    
    where_extra = ""
    if apenas_privado:
        termos_excluir = r'DIRETORIO|PARTIDO|ELEICAO|ELEIÇÃO|ELAIÇÃO|ELAICAO|COMITE|COMITÊ|FEDERACAO|FEDERAÇÃO|DIREÇÃO|ÓRGÃO|FUNDO ESPECIAL'
        where_extra = f"WHERE (NOT regexp_matches(UPPER(COALESCE(nome_doador, '')), '{termos_excluir}'))"

    # 4 Indicadores Estratégicos Globais
    row_kpis = query_fetchone(f"""
        SELECT 
            COALESCE(SUM(valor_receita), 0.0) as volume_total,
            COUNT(DISTINCT cpf_candidato) as total_candidatos,
            COUNT(DISTINCT cpf_cnpj_doador) as total_doadores,
            COUNT(*) as total_transacoes
        FROM eleicoes
        {where_extra}
    """)
    if not row_kpis:
        row_kpis = (0.0, 0, 0, 0)

    # ---------------------------------------------------------
    # 1. TOP 10 DOADORES (Processamento 100% no motor DuckDB)
    # ---------------------------------------------------------
    regex_crowd = r'AIXMOBIL|VAKINHA|APOIA\.SE|BENFEITORIA|KICKANTE|CATARSE|CROWDFUNDING|APP CIVICO|UM A MAIS SERVICOS|GOIA SERVICOS|PAGUE JUNTO|ELEGIS GESTAO'
    
    sql_doadores = f"""
        WITH Ranking AS (
            SELECT 
                cpf_cnpj_doador, 
                MAX(nome_doador) as nome_doador, -- Pega o nome correto atrelado ao CPF
                SUM(valor_receita) as total_doador
            FROM eleicoes
            {where_extra} {'AND' if where_extra else 'WHERE'} cpf_cnpj_doador IS NOT NULL AND TRIM(cpf_cnpj_doador) != ''
            AND NOT regexp_matches(UPPER(nome_doador), '{regex_crowd}')
            GROUP BY cpf_cnpj_doador
            ORDER BY total_doador DESC
            LIMIT 10
        )
        SELECT 
            r.nome_doador, r.total_doador,
            COALESCE(e.nome_candidato, 'NÃO INFORMADO') as nome_candidato,
            COALESCE(e.sigla_partido, 'S/P') as sigla_partido,
            COALESCE(e.cargo, '-') as cargo,
            SUM(e.valor_receita) as valor_repasse
        FROM eleicoes e
        JOIN Ranking r ON e.cpf_cnpj_doador = r.cpf_cnpj_doador
        {where_extra.replace("nome_doador", "e.nome_doador").replace("autofinanciamento", "e.autofinanciamento")}
        GROUP BY r.nome_doador, r.total_doador, e.nome_candidato, e.sigla_partido, e.cargo
        ORDER BY r.total_doador DESC, valor_repasse DESC
    """
    df_doadores_bruto = query_df(sql_doadores)
    
    top_doadores = []
    for (nome, total), group in df_doadores_bruto.groupby(["nome_doador", "total_doador"], sort=False):
        destinatarios = group.apply(lambda row: {
            "candidato": row["nome_candidato"], "partido": row["sigla_partido"],
            "cargo": row["cargo"], "valor": float(row["valor_repasse"])
        }, axis=1).tolist()
        top_doadores.append({"nome": nome, "total": float(total), "destinatarios": destinatarios})

    # ---------------------------------------------------------
    # 2. TOP 10 CANDIDATOS (Processamento 100% no motor DuckDB)
    # ---------------------------------------------------------
    sql_candidatos = f"""
        WITH Ranking AS (
            SELECT 
                cpf_candidato, 
                MAX(nome_candidato) as nome_candidato, 
                MAX(sigla_partido) as sigla_partido, 
                MAX(cargo) as cargo, 
                COALESCE(MAX(uf_candidato), 'BR') as uf_candidato, 
                SUM(valor_receita) as total_candidato
            FROM eleicoes
            {where_extra} {'AND' if where_extra else 'WHERE'} cpf_candidato IS NOT NULL AND TRIM(cpf_candidato) != ''
            GROUP BY cpf_candidato
            ORDER BY total_candidato DESC
            LIMIT 10
        )
        SELECT 
            r.nome_candidato, r.sigla_partido, r.cargo, r.uf_candidato, r.total_candidato,
            CASE 
                WHEN regexp_matches(UPPER(COALESCE(MAX(e.nome_doador), '')), '{regex_crowd}') 
                THEN COALESCE(MAX(e.nome_doador), '') || ' (PLATAFORMA DE CROWDFUNDING)' 
                ELSE COALESCE(MAX(e.nome_doador), 'NÃO INFORMADO') 
            END as nome_doador,
            SUM(e.valor_receita) as valor_doado
        FROM eleicoes e
        JOIN Ranking r ON e.cpf_candidato = r.cpf_candidato
        {where_extra.replace("nome_doador", "e.nome_doador").replace("autofinanciamento", "e.autofinanciamento")}
        GROUP BY r.nome_candidato, r.sigla_partido, r.cargo, r.uf_candidato, r.total_candidato, e.cpf_cnpj_doador
        ORDER BY r.total_candidato DESC, valor_doado DESC
    """
    df_candidatos_bruto = query_df(sql_candidatos)
    
    top_candidatos = []
    for (nome, partido, cargo, uf, total), group in df_candidatos_bruto.groupby(["nome_candidato", "sigla_partido", "cargo", "uf_candidato", "total_candidato"], sort=False):
        doadores = group.sort_values(by="valor_doado", ascending=False).apply(lambda row: {
            "doador": row["nome_doador"], "valor": float(row["valor_doado"])
        }, axis=1).tolist()
        top_candidatos.append({
            "nome": nome, "partido": partido, "cargo": cargo, "uf": uf, "total": float(total), "doadores": doadores
        })

    # ---------------------------------------------------------
    # 3. Distribuição do Volume Arrecadado (Escala Logarítmica)
    # ---------------------------------------------------------
    df_receitas = query_df(f"""
        SELECT SUM(valor_receita) as total
        FROM eleicoes
        {where_extra}
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

    resultado_final = {
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

    cache_global[apenas_privado] = resultado_final
    return resultado_final

# ==============================================================================
# ENDPOINT: VISÃO GERAL (PROMPT 1 + PROMPT 2 + PROMPT 3)
# ==============================================================================

cache_visao_geral = {}

@app.get("/api/visao-geral")
def get_visao_geral(
    ano: int = Query(..., description="Ano eleitoral obrigatório e específico (não acumular anos)"),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
    apenas_privado: bool = Query(False)
) -> Dict[str, Any]:
    """Retorna dados da seção dinâmica Visão Geral para um ano eleitoral específico."""

    chave_cache = f"{ano}_{cargo}_{uf}_{partido}_{municipio}_{apenas_privado}"

    if chave_cache in cache_visao_geral:
        return cache_visao_geral[chave_cache]

    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, municipio=municipio, apenas_privado=apenas_privado)

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

    # 1. Top 10 Doadores com Detalhamento de Destinatários
    regex_crowd = r'AIXMOBIL|VAKINHA|APOIA\.SE|BENFEITORIA|KICKANTE|CATARSE|CROWDFUNDING|APP CIVICO|UM A MAIS SERVICOS|GOIA SERVICOS|PAGUE JUNTO|ELEGIS GESTAO'    
    mascara_nao_crowd = ~df_filtrado["nome_doador"].astype(str).str.upper().str.contains(regex_crowd, regex=True, na=False)
    
    top_doadores_bruto = (
        df_filtrado[mascara_nao_crowd] # Filtra as vaquinhas do ranking
        .groupby(["nome_doador", "nome_candidato", "sigla_partido", "cargo"], as_index=False)["valor_receita"]
        .sum()
    )
    
    # Descobrir quem são os Top 10 Doadores em volume total
    ranking_doadores = top_doadores_bruto.groupby("nome_doador")["valor_receita"].sum().nlargest(10).index
    
    # Filtrar apenas os dados dos Top 10
    top_doadores_filtrado = top_doadores_bruto[top_doadores_bruto["nome_doador"].isin(ranking_doadores)]
    
    # Agrupar no formato que o React precisa: {nome: "João", total: 1000, destinatarios: [{candidato: "Maria", partido: "PT", valor: 1000}]}
    top_doadores = []
    for nome, group in top_doadores_filtrado.groupby("nome_doador"):
        destinatarios = group.sort_values(by="valor_receita", ascending=False).apply(
            lambda row: {
                "candidato": row["nome_candidato"],
                "partido": row["sigla_partido"],
                "cargo": row["cargo"],
                "valor": float(row["valor_receita"])
            }, axis=1
        ).tolist()
        
        top_doadores.append({
            "nome": nome,
            "total": float(group["valor_receita"].sum()),
            "destinatarios": destinatarios
        })
    
    # Ordenar o array final do maior doador para o menor
    top_doadores = sorted(top_doadores, key=lambda x: x["total"], reverse=True)

    # 2. Top 10 Candidatos com Origens (Visão Geral)
    df_filtrado_cand = df_filtrado.copy()
    mascara_crowd = df_filtrado_cand["nome_doador"].astype(str).str.upper().str.contains(regex_crowd, regex=True, na=False)
    df_filtrado_cand.loc[mascara_crowd, "nome_doador"] = df_filtrado_cand.loc[mascara_crowd, "nome_doador"] + " (PLATAFORMA DE CROWDFUNDING)"
    
    # Adicionamos 'uf_candidato' aqui no agrupamento bruto
    top_candidatos_bruto = (
        df_filtrado_cand.groupby(["nome_candidato", "sigla_partido", "cargo", "uf_candidato", "cpf_candidato", "nome_doador"], dropna=False, as_index=False)["valor_receita"]
        .sum()
    )
    ranking_candidatos = top_candidatos_bruto.groupby("cpf_candidato")["valor_receita"].sum().nlargest(10).index
    top_candidatos_filtrado = top_candidatos_bruto[top_candidatos_bruto["cpf_candidato"].isin(ranking_candidatos)]
    
    top_candidatos = []
    # E adicionamos 'uf_candidato' aqui no loop
    for (nome, partido, cargo, uf), group in top_candidatos_filtrado.groupby(["nome_candidato", "sigla_partido", "cargo", "uf_candidato"]):
        doadores = group.sort_values(by="valor_receita", ascending=False).apply(
            lambda row: {
                "doador": str(row["nome_doador"]) if pd.notna(row["nome_doador"]) else "NÃO INFORMADO",
                "valor": float(row["valor_receita"])
            }, axis=1
        ).tolist()
        top_candidatos.append({
            "nome": str(nome),
            "partido": str(partido),
            "cargo": str(cargo),
            "uf": str(uf) if pd.notna(uf) and str(uf).strip() else "BR",
            "total": float(group["valor_receita"].sum()),
            "doadores": doadores
        })
    top_candidatos = sorted(top_candidatos, key=lambda x: x["total"], reverse=True)

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
    mascara_uf = df_filtrado["uf_candidato"].notna() & ~df_filtrado["uf_candidato"].isin(["", "BR"])
    
    panorama_uf = (
        df_filtrado[mascara_uf]
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
        col_origem = 'tipo_receita'
    else:
        termos: r'DIRETORIO|PARTIDO|ELEICAO|ELEIÇÃO|COMITE|COMITÊ|FEDERACAO|FEDERAÇÃO|DIREÇÃO|ÓRGÃO|FUNDO ESPECIAL'
        df_filtrado["tipo_receita"] = np.where(
            df_filtrado["nome_doador"].astype(str).str.upper().str.contains(termos, regex=True, na=False),
            "Institucional/Público",
            np.where(df_filtrado["autofinanciamento"] == 1, "Autofinanciamento", "Privado/Particular")
        )
        col_origem = 'tipo_receita'
    origem_recursos = (
        df_filtrado.groupby(col_origem, as_index=False)["valor_receita"]
        .sum()
        .rename(columns={"valor_receita": "total", col_origem: "origem"})
        .sort_values(by="total", ascending=False)
        .to_dict(orient="records")
    )

    resultado_final = {
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

    if len(cache_visao_geral) >= 100:
        chave_mais_antiga = next(iter(cache_visao_geral))
        del cache_visao_geral[chave_mais_antiga]

    cache_visao_geral[chave_cache] = resultado_final
    return resultado_final


# ==============================================================================
# ENDPOINT: CUSTO DO VOTO (PROMPT 2 / AGENTS.MD - SCATTER ONLY 1 ANO + 1 CARGO)
# ==============================================================================
@app.get("/api/custo-do-voto")
def get_custo_do_voto(
    ano: int = Query(..., description="Ano eleitoral obrigatório"),
    cargo: str = Query(..., description="Cargo obrigatório específico"),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    apenas_privado: bool = Query(False),
) -> Dict[str, Any]:
    """Retorna dados de Custo do Voto (Scatter Plot). Exige obrigatoriamente 1 Ano E 1 Cargo."""
    if not cargo or not cargo.strip():
        raise HTTPException(
            status_code=400,
            detail="O módulo Custo do Voto exige a seleção obrigatória de 1 Cargo específico.",
        )

    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, apenas_privado=apenas_privado
    )
    
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
    apenas_privado: bool = Query(False)
) -> Dict[str, Any]:
    """Retorna análise de Porta Giratória expurgando repasses institucionais e aliados via Regex."""
    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, municipio=municipio, apenas_privado=apenas_privado
    )

    where_pg = where + " AND valor_receita > 0 AND valor_recebido_como_fornecedor > 0"

    row_kpis = query_fetchone(f"""
        SELECT 
            SUM(valor_recebido_como_fornecedor) as volume_total,
            COUNT(*) as transacoes,
            COUNT(DISTINCT cpf_candidato) as campanhas,
            MAX(valor_recebido_como_fornecedor / NULLIF(valor_receita, 0)) as maior_taxa
        FROM eleicoes
        {where_pg}
    """, params)
    
    volume_retorno = float(row_kpis[0] or 0.0)
    transacoes = int(row_kpis[1] or 0)
    campanhas = int(row_kpis[2] or 0)
    maior_taxa = float(row_kpis[3] or 0.0)

    if transacoes == 0:
        return {
            "kpis": {
                "volume_total_retorno": 0.0,
                "transacoes_identificadas": 0,
                "campanhas_com_ocorrencia": 0,
                "maior_taxa_retorno": 0.0
            },
            "ranking_porta_giratoria": [],
            "comparativo_bidirecional": [],
        }

    filtro_servicos = r'(PAGAMENTO|TECNOLOGIA|SERVICO|SERVIÇO|BANCO|FACEBOOK|GOOGLE|CORREIOS|TELECOM|INTERNET|MIDIA|MÍDIA)'
    termos_excluir = r'DIRETORIO|PARTIDO|ELEICAO|ELEIÇÃO|ELAICAO|ELAIÇÃO|CAMPANHA|COMITE|COMITÊ|FEDERACAO|FEDERAÇÃO|DIREÇÃO|ÓRGÃO|FUNDO ESPECIAL|PROVISORIA|PROVISÓRIA|MUNICIPAL|ESTADUAL|NACIONAL'
    where_limpo = where_pg + f"""
        AND NOT regexp_matches(UPPER(COALESCE(nome_doador, '')), '{filtro_servicos}')
        AND NOT regexp_matches(UPPER(COALESCE(nome_doador, '')), '{termos_excluir}')
        AND NOT regexp_matches(UPPER(COALESCE(nome_candidato, '')), '{termos_excluir}')
    """

    # Ranking Top 15 casos
    ranking = query_df(f"""
        SELECT
            COALESCE(nome_candidato, 'NÃO INFORMADO') as nome_candidato,
            COALESCE(sigla_partido, 'S/P') as sigla_partido,
            COALESCE(nome_doador, 'NÃO INFORMADO') as nome_doador,
            SUM(valor_receita) as total_doado,
            SUM(valor_recebido_como_fornecedor) as total_fornecedor,
            (SUM(valor_recebido_como_fornecedor) / NULLIF(SUM(valor_receita), 0)) as taxa_retorno
        FROM eleicoes
        {where_limpo}
        GROUP BY nome_candidato, sigla_partido, nome_doador
        ORDER BY total_fornecedor DESC
        LIMIT 15
    """, params).to_dict(orient="records")

    # Comparativo Bidirecional Top 10 por volume recebido
    comparativo = query_df(f"""
        SELECT
            COALESCE(nome_doador, 'NÃO INFORMADO') as nome_doador,
            SUM(valor_receita) as total_doado,
            SUM(valor_recebido_como_fornecedor) as total_fornecedor
        FROM eleicoes
        {where_limpo}
        GROUP BY nome_doador
        ORDER BY total_fornecedor DESC
        LIMIT 10
    """, params).to_dict(orient="records")

    return {
        "kpis": {
            "volume_total_retorno": volume_retorno,
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
    apenas_privado: bool = Query(False)
) -> Dict[str, Any]:
    """Retorna análise de origem de recursos e autofinanciamento com taxas de sucesso corrigidas."""
    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, municipio=municipio, apenas_privado=apenas_privado
    )
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
