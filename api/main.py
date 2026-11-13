"""API FastAPI de alta performance para o Painel Eleitoral (PACD).

Serve dados analíticos agregados a partir do banco consolidado DuckDB/Parquet,
aplicando rigorosamente as travas eleitorais, higienização por Regex e zero conclusões.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.metrics import calcular_sucesso_decil

logger = logging.getLogger("pacd_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_PARQUET_PATH = PROJECT_ROOT / "data/processed/base_consolidada_eleicoes.parquet"

REGEX_CROWD = (
    r"AIXMOBIL|VAKINHA|APOIA\.SE|BENFEITORIA|KICKANTE|CATARSE|CROWDFUNDING|"
    r"APPCIVICO|APP CIVICO|APPCÍVICO|APP CÍVICO|UM A MAIS|GOIA SERVI|PAGUE JUNTO|ELEGIS GEST|QUEROAPOIAR|QUERO APOIAR|VOTO LEGAL"
)

app = FastAPI(
    title="PACD Electoral Analytics API",
    description="Backend API analítico para o Painel Eleitoral Brasileiro (2018-2024)",
    version="1.2.0",
)

# Habilita CORS irrestrito para desenvolvimento e consumo SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Servir a SPA na rota raiz sem cache no navegador
@app.get("/", include_in_schema=False)
def serve_spa():
    return FileResponse(
        PROJECT_ROOT / "frontend/index.html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# Conexão DuckDB compartilhada em memória apontando para o arquivo parquet
conn = duckdb.connect(database=":memory:")

# Inspeção dinâmica de colunas para retrocompatibilidade perfeita (com ou sem uf_empresa)
colunas_parquet = set(
    conn.execute(f"DESCRIBE SELECT * FROM '{BASE_PARQUET_PATH.as_posix()}' LIMIT 0")
    .df()["column_name"]
    .str.lower()
    .tolist()
)
col_uf_empresa_proj = "uf_empresa" if "uf_empresa" in colunas_parquet else "NULL::VARCHAR AS uf_empresa"

conn.execute(f"""
    CREATE VIEW eleicoes AS
    SELECT
        * REPLACE (
            COALESCE(NULLIF(TRIM(cpf_candidato), ''), sequencial_candidato) AS cpf_candidato,
            CASE 
                -- Saneamento cirúrgico de anomalias de digitação contábil autodeclaradas no SPCE/TSE
                -- 1. Candidatura a vereador em Salvador/BA (repetição de '1250' sem pontuação decimal)
                WHEN cpf_cnpj_doador = '16068108000156' AND valor_receita = 1250125000.0 THEN 1250.00
                -- 2. Candidaturas a vereador no AM (rateio de material gráfico estimado onde R$ 207,17 por candidato foi lançado sem decimais como R$ 207.166.666,66)
                WHEN cpf_cnpj_doador = '38121911000140' AND valor_receita > 200000000.0 THEN 207.17
                ELSE valor_receita
            END AS valor_receita
        ),
        {col_uf_empresa_proj},
        0.0 AS valor_recebido_como_fornecedor,
        CASE
            WHEN LOWER(COALESCE(origem_receita, '')) IN (
                'recursos de pessoas fisicas',
                'recursos proprios',
                'recursos de financiamento coletivo',
                'doacoes pela internet',
                'comercializacao de bens ou realizacao de eventos'
            ) OR autofinanciamento = 1
            THEN 'Financiamento Privado'
            WHEN LOWER(COALESCE(origem_receita, '')) = 'recursos de outros candidatos'
            THEN 'Repasse entre Aliados'
            ELSE 'Dinheiro Público'
        END AS tipo_receita
    FROM '{BASE_PARQUET_PATH.as_posix()}'
""")

# Tabela em memória para resolução canônica do domicílio/sede federativa de doadores
conn.execute("""
    CREATE TABLE sede_doadores AS
    SELECT 
        nome_doador,
        COALESCE(
            MAX(NULLIF(NULLIF(TRIM(uf_empresa), ''), 'BR')),
            MAX(NULLIF(NULLIF(NULLIF(TRIM(sigla_uf_doador), ''), 'BR'), '-')),
            MODE(CASE WHEN uf_candidato IS NOT NULL AND TRIM(uf_candidato) NOT IN ('', 'BR', '-') THEN uf_candidato END)
        ) as uf_origem
    FROM eleicoes
    WHERE nome_doador IS NOT NULL AND TRIM(nome_doador) != ''
    GROUP BY nome_doador
""")

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
    modo_recurso: Optional[str] = None,
    alias: str = "",
) -> tuple[str, list[Any]]:
    """Gera cláusula WHERE parametrizada para consultas seguras no DuckDB."""
    prefix = f"{alias}." if alias else ""
    condicoes = ["1=1"]
    params: list[Any] = []

    if isinstance(ano, (int, float)):
        condicoes.append(f"{prefix}ano = ?")
        params.append(int(ano))
    elif isinstance(ano, str) and ano.strip() and ano.strip().upper() != "TODOS":
        anos_limpos = [int(a.strip()) for a in ano.split(",") if a.strip().isdigit()]
        if len(anos_limpos) == 1:
            condicoes.append(f"{prefix}ano = ?")
            params.append(anos_limpos[0])
        elif len(anos_limpos) > 1:
            placeholders_a = ", ".join(["?"] * len(anos_limpos))
            condicoes.append(f"{prefix}ano IN ({placeholders_a})")
            params.extend(anos_limpos)

    if isinstance(cargo, str) and cargo.strip() and cargo.strip().upper() != "TODOS":
        condicoes.append(f"UPPER({prefix}cargo) = ?")
        params.append(cargo.strip().upper())
    if isinstance(uf, str) and uf.strip():
        ufs_limpas = [u.strip().upper() for u in uf.split(",") if u.strip().upper() not in ("TODAS", "")]
        if ufs_limpas:
            placeholders = ", ".join(["?"] * len(ufs_limpas))
            condicoes.append(f"UPPER({prefix}uf_candidato) IN ({placeholders})")
            params.extend(ufs_limpas)
    if isinstance(partido, str) and partido.strip() and partido.strip().upper() != "TODOS":
        partidos_limpos = [p.strip().upper() for p in partido.split(",") if p.strip().upper() not in ("TODOS", "")]
        if len(partidos_limpos) == 1:
            condicoes.append(f"UPPER({prefix}sigla_partido) = ?")
            params.append(partidos_limpos[0])
        elif len(partidos_limpos) > 1:
            placeholders_p = ", ".join(["?"] * len(partidos_limpos))
            condicoes.append(f"UPPER({prefix}sigla_partido) IN ({placeholders_p})")
            params.extend(partidos_limpos)

    # Filtro Global de Origem (3 fases: 'todos', 'privado', 'elite')
    modo = str(modo_recurso).lower() if modo_recurso else None
    if modo == "elite":
        condicoes.append(f"{prefix}tipo_receita = 'Financiamento Privado'")
        condicoes.append(f"{prefix}is_empresario = TRUE")
    elif modo == "privado" or (apenas_privado and modo != "todos"):
        condicoes.append(f"{prefix}tipo_receita = 'Financiamento Privado'")

    clausula = "WHERE " + " AND ".join(condicoes)
    return clausula, params


# ==============================================================================
# ENDPOINT: METADADOS E REGRAS DE FILTRO (PROMPT 2 / AGENTS.MD)
# ==============================================================================
cache_filtros: Dict[str, Any] = {}


@app.get("/api/meta/filtros")
def get_metadata_filtros() -> Dict[str, Any]:
    """Retorna metadados de filtros e regras eleitorais de negócio."""
    if "dados_filtros" in cache_filtros:
        return cache_filtros["dados_filtros"]

    anos_raw = query_fetchall("SELECT DISTINCT ano FROM eleicoes ORDER BY ano")
    anos = [int(r[0]) for r in anos_raw if r[0] is not None]

    ufs_raw = query_fetchall(
        "SELECT DISTINCT uf_candidato FROM eleicoes WHERE uf_candidato IS NOT NULL AND uf_candidato NOT IN ('', 'BR') ORDER BY uf_candidato"
    )
    ufs = [str(r[0]).upper() for r in ufs_raw]

    partidos_raw = query_fetchall(
        "SELECT DISTINCT sigla_partido FROM eleicoes WHERE sigla_partido IS NOT NULL AND sigla_partido != '' ORDER BY sigla_partido"
    )
    partidos = [str(r[0]).upper() for r in partidos_raw]

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
cache_global: Dict[str, Any] = {}


@app.get("/api/global")
def get_global_metrics(
    apenas_privado: bool = Query(False),
    modo_recurso: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna os dados consolidados de toda a base histórica (Bloco Superior Fixo)."""
    modo = str(modo_recurso).lower() if modo_recurso else ("privado" if apenas_privado else "todos")
    if modo in cache_global:
        return cache_global[modo]

    where_extra, _ = construir_clausula_where(modo_recurso=modo)
    if where_extra == "WHERE 1=1":
        where_extra = ""
    else:
        where_extra = where_extra.replace("WHERE 1=1 AND ", "WHERE ")

    where_extra_e, _ = construir_clausula_where(modo_recurso=modo, alias="e")
    if where_extra_e == "WHERE 1=1":
        where_extra_e = ""
    else:
        where_extra_e = where_extra_e.replace("WHERE 1=1 AND ", "WHERE ")

    # 4 Indicadores Estratégicos Globais
    row_kpis = query_fetchone(f"""
        SELECT
            COALESCE(SUM(valor_receita), 0.0) as volume_total,
            COUNT(DISTINCT sequencial_candidato) as total_candidatos,
            COUNT(DISTINCT CASE WHEN valor_receita > 0 AND cpf_cnpj_doador IS NOT NULL AND TRIM(cpf_cnpj_doador) != '' THEN cpf_cnpj_doador END) as total_doadores,
            COUNT(*) as total_transacoes
        FROM eleicoes
        {where_extra}
    """)
    if not row_kpis:
        row_kpis = (0.0, 0, 0, 0)

    # 1. TOP 10 DOADORES (Otimizado via Window Function no DuckDB, reduzindo payload de 10.6MB para ~40KB)
    sql_doadores = f"""
        WITH Ranking AS (
            SELECT
                e.cpf_cnpj_doador,
                MAX(COALESCE(e.nome_doador, 'NÃO INFORMADO')) as nome_doador,
                COALESCE(
                    MAX(NULLIF(NULLIF(TRIM(e.uf_empresa), ''), 'BR')),
                    MAX(s.uf_origem),
                    MAX(NULLIF(NULLIF(NULLIF(TRIM(e.sigla_uf_doador), ''), 'BR'), '-')),
                    MAX(NULLIF(NULLIF(TRIM(e.uf_candidato), ''), 'BR')),
                    '-'
                ) as uf_doador,
                SUM(e.valor_receita) as total_doador
            FROM eleicoes e
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_extra_e} {'AND' if where_extra_e else 'WHERE'} e.cpf_cnpj_doador IS NOT NULL AND TRIM(e.cpf_cnpj_doador) != ''
            AND e.valor_receita > 0
            AND NOT regexp_matches(UPPER(COALESCE(e.nome_doador, '')), '{REGEX_CROWD}')
            GROUP BY e.cpf_cnpj_doador
            ORDER BY total_doador DESC
            LIMIT 10
        ),
        DestinatariosAgg AS (
            SELECT
                r.cpf_cnpj_doador,
                r.nome_doador,
                r.uf_doador,
                r.total_doador,
                COALESCE(e.nome_candidato, 'NÃO INFORMADO') as nome_candidato,
                COALESCE(e.sigla_partido, 'S/P') as sigla_partido,
                COALESCE(e.cargo, '-') as cargo,
                COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR') as uf_candidato,
                SUM(e.valor_receita) as valor_repasse,
                ROW_NUMBER() OVER (PARTITION BY r.cpf_cnpj_doador ORDER BY SUM(e.valor_receita) DESC) as rn
            FROM eleicoes e
            JOIN Ranking r ON e.cpf_cnpj_doador = r.cpf_cnpj_doador
            {where_extra_e} {'AND' if where_extra_e else 'WHERE'} e.valor_receita > 0
            GROUP BY r.cpf_cnpj_doador, r.nome_doador, r.uf_doador, r.total_doador, e.nome_candidato, e.sigla_partido, e.cargo, COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR')
        )
        SELECT * FROM DestinatariosAgg
        WHERE rn <= 50
        ORDER BY total_doador DESC, valor_repasse DESC
    """
    df_doadores_bruto = query_df(sql_doadores)

    top_doadores = []
    if not df_doadores_bruto.empty:
        for (_, nome, uf_d, total), group in df_doadores_bruto.groupby(["cpf_cnpj_doador", "nome_doador", "uf_doador", "total_doador"], sort=False):
            destinatarios = [
                {
                    "candidato": cand,
                    "partido": part,
                    "cargo": crg,
                    "uf": ufe,
                    "valor": float(vlr),
                }
                for cand, part, crg, ufe, vlr in zip(
                    group["nome_candidato"],
                    group["sigla_partido"],
                    group["cargo"],
                    group["uf_candidato"],
                    group["valor_repasse"],
                )
            ]
            top_doadores.append({"nome": nome, "uf": uf_d, "total": float(total), "destinatarios": destinatarios})

    # 2. TOP 10 CANDIDATOS (Otimizado via Window Function no DuckDB com Blindagem de Candidatura)
    sql_candidatos = f"""
        WITH Ranking AS (
            SELECT
                ano,
                cpf_candidato,
                cargo,
                MAX(nome_candidato) as nome_candidato,
                MAX(sigla_partido) as sigla_partido,
                COALESCE(NULLIF(TRIM(MAX(uf_candidato)), ''), 'BR') as uf_candidato,
                SUM(valor_receita) as total_candidato
            FROM eleicoes
            {where_extra} {'AND' if where_extra else 'WHERE'} cpf_candidato IS NOT NULL AND TRIM(cpf_candidato) != ''
            GROUP BY ano, cpf_candidato, cargo
            ORDER BY total_candidato DESC
            LIMIT 10
        ),
        DoadoresAgg AS (
            SELECT
                r.ano,
                r.cpf_candidato,
                r.nome_candidato,
                r.sigla_partido,
                r.cargo,
                r.uf_candidato,
                r.total_candidato,
                CASE
                    WHEN regexp_matches(UPPER(COALESCE(MAX(e.nome_doador), '')), '{REGEX_CROWD}')
                    THEN COALESCE(MAX(e.nome_doador), '') || ' (PLATAFORMA DE CROWDFUNDING)'
                    ELSE COALESCE(MAX(e.nome_doador), 'NÃO INFORMADO')
                END as nome_doador,
                COALESCE(
                    MAX(NULLIF(NULLIF(TRIM(e.uf_empresa), ''), 'BR')),
                    MAX(s.uf_origem),
                    MAX(NULLIF(NULLIF(NULLIF(TRIM(e.sigla_uf_doador), ''), 'BR'), '-')),
                    MAX(NULLIF(NULLIF(TRIM(e.uf_candidato), ''), 'BR')),
                    '-'
                ) as uf_doador,
                SUM(e.valor_receita) as valor_doado,
                ROW_NUMBER() OVER (PARTITION BY r.ano, r.cpf_candidato, r.cargo ORDER BY SUM(e.valor_receita) DESC) as rn
            FROM eleicoes e
            JOIN Ranking r ON e.ano = r.ano AND e.cpf_candidato = r.cpf_candidato AND e.cargo = r.cargo
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_extra_e} {'AND' if where_extra_e else 'WHERE'} e.valor_receita > 0
            GROUP BY r.ano, r.cpf_candidato, r.nome_candidato, r.sigla_partido, r.cargo, r.uf_candidato, r.total_candidato, e.cpf_cnpj_doador
        )
        SELECT * FROM DoadoresAgg
        WHERE rn <= 50
        ORDER BY total_candidato DESC, valor_doado DESC
    """
    df_candidatos_bruto = query_df(sql_candidatos)

    top_candidatos = []
    if not df_candidatos_bruto.empty:
        for (ano_c, _, nome, partido, cargo, uf, total), group in df_candidatos_bruto.groupby(
            ["ano", "cpf_candidato", "nome_candidato", "sigla_partido", "cargo", "uf_candidato", "total_candidato"],
            sort=False,
        ):
            doadores = [
                {"doador": d_nome, "uf": d_uf, "valor": float(d_val)}
                for d_nome, d_uf, d_val in zip(
                    group["nome_doador"],
                    group["uf_doador"],
                    group["valor_doado"],
                )
                if float(d_val or 0.0) > 0.0
            ]
            top_candidatos.append(
                {"ano": int(ano_c), "nome": nome, "partido": partido, "cargo": cargo, "uf": uf, "total": float(total), "doadores": doadores}
            )

    # 3. Distribuição do Volume Arrecadado (Escala Logarítmica)
    df_receitas = query_df(f"""
        SELECT SUM(valor_receita) as total
        FROM eleicoes
        {where_extra}
        GROUP BY ano, cpf_candidato, cargo
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
        GROUP BY ano, cpf_candidato, nome_candidato, sigla_partido, cargo, uf_candidato
        ORDER BY total_proprio DESC
        LIMIT 10
    """).to_dict(orient="records")

    # 5. Top 10 Partidos em Volume Financeiro
    top_partidos_global = query_df(f"""
        SELECT
            COALESCE(sigla_partido, 'S/P') as partido,
            SUM(valor_receita) as total
        FROM eleicoes
        {where_extra}
        GROUP BY sigla_partido
        ORDER BY total DESC
        LIMIT 10
    """).to_dict(orient="records")

    # 6. Ranking Federativo Global (Top Estados)
    ranking_estados_global = query_df(f"""
        SELECT
            uf_candidato as uf,
            SUM(valor_receita) as total
        FROM eleicoes
        {where_extra} {'AND' if where_extra else 'WHERE'} uf_candidato IS NOT NULL AND uf_candidato NOT IN ('', 'BR')
        GROUP BY uf_candidato
        ORDER BY total DESC
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
            "top_10_partidos": top_partidos_global,
            "ranking_estados": ranking_estados_global,
        },
    }

    cache_global[modo] = resultado_final
    return resultado_final


# ==============================================================================
# ENDPOINT: VISÃO GERAL (PROMPT 1 + PROMPT 2 + PROMPT 3)
# ==============================================================================
cache_visao_geral: Dict[str, Any] = {}


@app.get("/api/visao-geral")
def get_visao_geral(
    ano: int | str = Query(..., description="Ano eleitoral ou anos agregados por ciclo"),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
    apenas_privado: bool = Query(False),
    modo_recurso: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna dados da seção dinâmica Visão Geral para um ano eleitoral específico via DuckDB."""
    modo = str(modo_recurso).lower() if modo_recurso else ("privado" if apenas_privado else "todos")
    chave_cache = f"{ano}_{cargo}_{uf}_{partido}_{modo}"
    if chave_cache in cache_visao_geral:
        return cache_visao_geral[chave_cache]

    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo
    )
    where_e, params_e = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo, alias="e"
    )

    # 0. KPIs diretos no DuckDB (com Blindagem de Candidatura e Doadores Efetivos > 0)
    row_kpis = query_fetchone(
        f"""
        SELECT
            COALESCE(SUM(valor_receita), 0.0) as total_arrecadado,
            COUNT(DISTINCT (CAST(ano AS VARCHAR) || '_' || cpf_candidato || '_' || COALESCE(cargo, ''))) as num_candidatos,
            COUNT(DISTINCT CASE WHEN valor_receita > 0 AND cpf_cnpj_doador IS NOT NULL AND TRIM(cpf_cnpj_doador) != '' THEN cpf_cnpj_doador END) as num_doadores,
            COUNT(*) as num_transacoes
        FROM eleicoes
        {where}
        """,
        params,
    )

    if not row_kpis or int(row_kpis[3] or 0) == 0:
        return {
            "kpis": {
                "total_arrecadado": 0.0,
                "num_candidatos": 0,
                "num_doadores": 0,
                "total_eleitos": 0,
                "taxa_sucesso_decil": {"taxa_top10": 0.0, "taxa_bottom50": 0.0, "diferenca_sucesso": 0.0},
            },
            "top_10_doadores": [],
            "top_10_candidatos": [],
            "distribuicao_log": [],
            "top_10_partidos": [],
            "is_partido_unico": False,
            "partido_selecionado": None,
            "cargo_selecionado": None,
            "modo_grafico_partidos": "oculto",
            "panorama_uf": [],
            "ranking_estados": [],
            "origem_recursos": [],
            "autofinanciamento_recorte": [],
            "top_setores_elite": [],
            "assertividade_elite": [],
        }

    total_arrecadado = float(row_kpis[0] or 0.0)
    num_candidatos = int(row_kpis[1] or 0)
    num_doadores = int(row_kpis[2] or 0)

    # Tabela agregada por candidatura canônica (ano, cpf_candidato, cargo)
    df_cand = query_df(
        f"""
        SELECT
            ano,
            cpf_candidato,
            cargo,
            MAX(CAST(is_eleito AS INT)) as is_eleito,
            SUM(valor_receita) as total_receita
        FROM eleicoes
        {where}
        GROUP BY ano, cpf_candidato, cargo
        """,
        params,
    )
    taxa_sucesso = calcular_sucesso_decil(df_cand)
    total_eleitos = int(df_cand["is_eleito"].fillna(0).sum()) if not df_cand.empty else 0

    # 1. Top 10 Doadores com Detalhamento de Destinatários e Resolução Canônica de UF
    sql_doadores = f"""
        WITH Ranking AS (
            SELECT
                e.cpf_cnpj_doador,
                MAX(COALESCE(e.nome_doador, 'NÃO INFORMADO')) as nome_doador,
                COALESCE(
                    MAX(NULLIF(NULLIF(TRIM(e.uf_empresa), ''), 'BR')),
                    MAX(s.uf_origem),
                    MAX(NULLIF(NULLIF(NULLIF(TRIM(e.sigla_uf_doador), ''), 'BR'), '-')),
                    MAX(NULLIF(NULLIF(TRIM(e.uf_candidato), ''), 'BR')),
                    '-'
                ) as uf_doador,
                SUM(e.valor_receita) as total_doador
            FROM eleicoes e
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_e} AND e.cpf_cnpj_doador IS NOT NULL AND TRIM(e.cpf_cnpj_doador) != ''
            AND e.valor_receita > 0
            AND NOT regexp_matches(UPPER(COALESCE(e.nome_doador, '')), '{REGEX_CROWD}')
            GROUP BY e.cpf_cnpj_doador
            ORDER BY total_doador DESC
            LIMIT 10
        ),
        DestinatariosAgg AS (
            SELECT
                r.cpf_cnpj_doador,
                r.nome_doador,
                r.uf_doador,
                r.total_doador,
                COALESCE(e.nome_candidato, 'NÃO INFORMADO') as nome_candidato,
                COALESCE(e.sigla_partido, 'S/P') as sigla_partido,
                COALESCE(e.cargo, '-') as cargo,
                COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR') as uf_candidato,
                SUM(e.valor_receita) as valor_repasse,
                ROW_NUMBER() OVER (PARTITION BY r.cpf_cnpj_doador ORDER BY SUM(e.valor_receita) DESC) as rn
            FROM eleicoes e
            JOIN Ranking r ON e.cpf_cnpj_doador = r.cpf_cnpj_doador
            {where_e} AND e.valor_receita > 0
            GROUP BY r.cpf_cnpj_doador, r.nome_doador, r.uf_doador, r.total_doador, e.nome_candidato, e.sigla_partido, e.cargo, COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR')
        )
        SELECT * FROM DestinatariosAgg
        WHERE rn <= 50
        ORDER BY total_doador DESC, valor_repasse DESC
    """
    df_doadores_bruto = query_df(sql_doadores, params_e + params_e)

    top_doadores = []
    if not df_doadores_bruto.empty:
        for (_, nome, uf_d, total), group in df_doadores_bruto.groupby(["cpf_cnpj_doador", "nome_doador", "uf_doador", "total_doador"], sort=False):
            destinatarios = [
                {
                    "candidato": cand,
                    "partido": part,
                    "cargo": crg,
                    "uf": ufe,
                    "valor": float(vlr),
                }
                for cand, part, crg, ufe, vlr in zip(
                    group["nome_candidato"],
                    group["sigla_partido"],
                    group["cargo"],
                    group["uf_candidato"],
                    group["valor_repasse"],
                )
            ]
            top_doadores.append({"nome": str(nome), "uf": uf_d, "total": float(total), "destinatarios": destinatarios})

    # 2. Top 10 Candidatos com Origens (Blindagem por ano, cpf_candidato, cargo + filtro de doadores > 0)
    sql_candidatos = f"""
        WITH Ranking AS (
            SELECT
                ano,
                cpf_candidato,
                cargo,
                MAX(nome_candidato) as nome_candidato,
                MAX(sigla_partido) as sigla_partido,
                COALESCE(NULLIF(TRIM(MAX(uf_candidato)), ''), 'BR') as uf_candidato,
                SUM(valor_receita) as total_candidato
            FROM eleicoes
            {where} AND cpf_candidato IS NOT NULL AND TRIM(cpf_candidato) != ''
            GROUP BY ano, cpf_candidato, cargo
            ORDER BY total_candidato DESC
            LIMIT 10
        ),
        DoadoresAgg AS (
            SELECT
                r.ano,
                r.cpf_candidato,
                r.nome_candidato,
                r.sigla_partido,
                r.cargo,
                r.uf_candidato,
                r.total_candidato,
                CASE
                    WHEN regexp_matches(UPPER(COALESCE(MAX(e.nome_doador), '')), '{REGEX_CROWD}')
                    THEN COALESCE(MAX(e.nome_doador), '') || ' (PLATAFORMA DE CROWDFUNDING)'
                    ELSE COALESCE(MAX(e.nome_doador), 'NÃO INFORMADO')
                END as nome_doador,
                COALESCE(
                    MAX(NULLIF(NULLIF(TRIM(e.uf_empresa), ''), 'BR')),
                    MAX(s.uf_origem),
                    MAX(NULLIF(NULLIF(NULLIF(TRIM(e.sigla_uf_doador), ''), 'BR'), '-')),
                    MAX(NULLIF(NULLIF(TRIM(e.uf_candidato), ''), 'BR')),
                    '-'
                ) as uf_doador,
                SUM(e.valor_receita) as valor_doado,
                ROW_NUMBER() OVER (PARTITION BY r.ano, r.cpf_candidato, r.cargo ORDER BY SUM(e.valor_receita) DESC) as rn
            FROM eleicoes e
            JOIN Ranking r ON e.ano = r.ano AND e.cpf_candidato = r.cpf_candidato AND e.cargo = r.cargo
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_e}
            GROUP BY r.ano, r.cpf_candidato, r.nome_candidato, r.sigla_partido, r.cargo, r.uf_candidato, r.total_candidato, e.cpf_cnpj_doador
        )
        SELECT * FROM DoadoresAgg
        WHERE rn <= 50
        ORDER BY total_candidato DESC, valor_doado DESC
    """
    df_candidatos_bruto = query_df(sql_candidatos, params + params_e)

    top_candidatos = []
    if not df_candidatos_bruto.empty:
        for (ano_c, _, nome, partido_c, cargo_c, uf_c, total), group in df_candidatos_bruto.groupby(
            ["ano", "cpf_candidato", "nome_candidato", "sigla_partido", "cargo", "uf_candidato", "total_candidato"],
            sort=False,
        ):
            doadores = [
                {"doador": d_nome, "uf": d_uf, "valor": float(d_val)}
                for d_nome, d_uf, d_val in zip(
                    group["nome_doador"],
                    group["uf_doador"],
                    group["valor_doado"],
                )
                if float(d_val or 0.0) > 0.0
            ]
            top_candidatos.append(
                {
                    "ano": int(ano_c),
                    "nome": str(nome),
                    "partido": str(partido_c),
                    "cargo": str(cargo_c),
                    "uf": str(uf_c) if pd.notna(uf_c) and str(uf_c).strip() else "BR",
                    "total": float(total),
                    "doadores": doadores,
                }
            )

    # 3. Distribuição Logarítmica (usando df_cand já agregado)
    receitas_cand = df_cand["total_receita"].values
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
    panorama_uf = query_df(
        f"""
        SELECT
            uf_candidato as uf,
            SUM(valor_receita) as total
        FROM eleicoes
        {where} AND uf_candidato IS NOT NULL AND uf_candidato NOT IN ('', 'BR')
        GROUP BY uf_candidato
        ORDER BY total DESC
        """,
        params,
    ).to_dict(orient="records")

    # 5. Ranking Estados (Top 10)
    ranking_estados = [{"uf": str(r["uf"]), "total": float(r["total"])} for r in panorama_uf[:10]]

    # 6. Composição por Origem do Recurso (Adaptativo às 3 fases do interruptor)
    if modo == "elite":
        origem_recursos = []
    elif modo == "privado":
        origem_recursos = query_df(
            f"""
            SELECT
                CASE 
                    WHEN autofinanciamento = 1 THEN 'Aporte Próprio (Candidato)'
                    WHEN LOWER(COALESCE(origem_receita, '')) IN ('recursos de financiamento coletivo', 'doacoes pela internet') THEN 'Financiamento Coletivo / Internet'
                    ELSE 'Doação de Cidadão (Pessoa Física)'
                END as origem,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            GROUP BY 1
            ORDER BY total DESC
            """,
            params,
        ).to_dict(orient="records")
    else:
        origem_recursos = query_df(
            f"""
            SELECT
                tipo_receita as origem,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            GROUP BY tipo_receita
            ORDER BY total DESC
            """,
            params,
        ).to_dict(orient="records")

    # 6.1 Aporte Próprio vs Recursos de Terceiros no Recorte (Simetria perfeita no grid)
    autofinanciamento_recorte = query_df(
        f"""
        SELECT
            CASE WHEN autofinanciamento = 1 THEN 'Aporte Próprio (Candidato)' ELSE 'Recursos de Terceiros / Aliados' END as tipo,
            SUM(valor_receita) as total
        FROM eleicoes
        {where}
        GROUP BY 1
        ORDER BY total DESC
        """,
        params,
    ).to_dict(orient="records")

    # 6.2 Métricas exclusivas para a Linha 3 no modo 'Elite Empresarial' (Perfil Setorial + Assertividade)
    top_setores_elite = []
    assertividade_elite = []
    if modo == "elite":
        top_setores_elite = query_df(
            f"""
            SELECT
                COALESCE(setor_economico, 'NÃO INFORMADO') as setor,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            AND is_empresario = TRUE
            AND setor_economico IS NOT NULL AND TRIM(setor_economico) != ''
            GROUP BY setor_economico
            ORDER BY total DESC
            LIMIT 5
            """,
            params,
        ).to_dict(orient="records")

        # Taxa de Sucesso Comparativa no Recorte (Com Apoio da Elite vs Sem Apoio)
        where_recorte, params_recorte = construir_clausula_where(
            ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=None
        )
        assertividade_elite = query_df(
            f"""
            WITH Candidaturas AS (
                SELECT
                    ano,
                    cpf_candidato,
                    cargo,
                    MAX(CAST(COALESCE(is_empresario, FALSE) AS INT)) as com_elite,
                    MAX(CAST(COALESCE(is_eleito, FALSE) AS INT)) as eleito,
                    SUM(CASE WHEN is_empresario = TRUE THEN valor_receita ELSE 0.0 END) as vol_elite
                FROM eleicoes
                {where_recorte}
                GROUP BY ano, cpf_candidato, cargo
            )
            SELECT
                'Com Apoio da Elite' as status,
                ROUND(COALESCE(AVG(CASE WHEN com_elite = 1 THEN eleito * 100.0 END), 0.0), 1) as taxa_sucesso,
                COUNT(CASE WHEN com_elite = 1 THEN 1 END) as total_candidatos,
                SUM(CASE WHEN com_elite = 1 THEN eleito ELSE 0 END) as eleitos,
                SUM(vol_elite) as total
            FROM Candidaturas
            UNION ALL
            SELECT
                'Sem Apoio da Elite' as status,
                ROUND(COALESCE(AVG(CASE WHEN com_elite = 0 THEN eleito * 100.0 END), 0.0), 1) as taxa_sucesso,
                COUNT(CASE WHEN com_elite = 0 THEN 1 END) as total_candidatos,
                SUM(CASE WHEN com_elite = 0 THEN eleito ELSE 0 END) as eleitos,
                0.0 as total
            FROM Candidaturas
            """,
            params_recorte,
        ).to_dict(orient="records")

    # 7. Gráfico Adaptativo de Partidos / Cargos / Estados no Recorte Dinâmico
    partidos_str = partido if isinstance(partido, str) else ""
    partidos_lista = [p.strip() for p in partidos_str.split(",") if p.strip() and p.strip().upper() != "TODOS"]
    is_partido_unico = len(partidos_lista) == 1
    partido_selecionado = partidos_lista[0] if is_partido_unico else None

    cargo_str = cargo if isinstance(cargo, str) else ""
    is_cargo_unico = bool(cargo_str.strip() and cargo_str.strip().upper() != "TODOS")
    cargo_selecionado = cargo_str.strip().upper() if is_cargo_unico else None

    uf_str = uf if isinstance(uf, str) else ""
    ufs_lista = [u.strip().upper() for u in uf_str.split(",") if u.strip().upper() not in ("TODAS", "")]
    is_uf_unica = len(ufs_lista) == 1 or cargo_selecionado in ("PRESIDENTE", "DEPUTADO DISTRITAL")

    if is_partido_unico and is_cargo_unico and is_uf_unica:
        # Todos os 3 filtros unitários: oculta gráfico para evitar barra única redundante
        modo_grafico_partidos = "oculto"
        top_partidos_recorte = []
    elif is_partido_unico and is_cargo_unico and not is_uf_unica:
        # 1 Partido + 1 Cargo + múltiplas UFs: mostra distribuição por UF das candidaturas do partido para o cargo
        modo_grafico_partidos = "ufs_do_partido_cargo"
        top_partidos_recorte = query_df(
            f"""
            SELECT
                uf_candidato as partido,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            AND uf_candidato IS NOT NULL AND TRIM(uf_candidato) NOT IN ('', 'BR', '-')
            GROUP BY uf_candidato
            ORDER BY total DESC
            LIMIT 10
            """,
            params,
        ).to_dict(orient="records")
    elif is_partido_unico and not is_cargo_unico:
        # 1 Partido + Todos os Cargos: mostra distribuição do partido por cargo
        modo_grafico_partidos = "cargos_do_partido"
        top_partidos_recorte = query_df(
            f"""
            SELECT
                cargo as partido,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            AND cargo IS NOT NULL AND TRIM(cargo) != '' AND UPPER(cargo) NOT IN ('-', 'NÃO INFORMADO', 'NAN')
            GROUP BY cargo
            ORDER BY total DESC
            LIMIT 10
            """,
            params,
        ).to_dict(orient="records")
    else:
        modo_grafico_partidos = "partidos"
        top_partidos_recorte = query_df(
            f"""
            SELECT
                COALESCE(sigla_partido, 'S/P') as partido,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            GROUP BY sigla_partido
            ORDER BY total DESC
            LIMIT 10
            """,
            params,
        ).to_dict(orient="records")

    resultado_final = {
        "kpis": {
            "total_arrecadado": total_arrecadado,
            "num_candidatos": num_candidatos,
            "num_doadores": num_doadores,
            "total_eleitos": total_eleitos,
            "taxa_sucesso_decil": taxa_sucesso,
        },
        "top_10_doadores": top_doadores,
        "top_10_candidatos": top_candidatos,
        "distribuicao_log": distribuicao_log,
        "top_10_partidos": top_partidos_recorte,
        "is_partido_unico": is_partido_unico,
        "partido_selecionado": partido_selecionado,
        "cargo_selecionado": cargo_selecionado,
        "modo_grafico_partidos": modo_grafico_partidos,
        "panorama_uf": panorama_uf,
        "ranking_estados": ranking_estados,
        "origem_recursos": origem_recursos,
        "autofinanciamento_recorte": autofinanciamento_recorte,
        "top_setores_elite": top_setores_elite,
        "assertividade_elite": assertividade_elite,
    }

    if len(cache_visao_geral) >= 100:
        chave_mais_antiga = next(iter(cache_visao_geral))
        del cache_visao_geral[chave_mais_antiga]

    cache_visao_geral[chave_cache] = resultado_final
    return resultado_final


# ==============================================================================
# ENDPOINT: ANÁLISE GEOGRÁFICA & FLUXO DE INFLUÊNCIA (ITENS 3 & 4)
# ==============================================================================
cache_geografia: Dict[str, Any] = {}


@app.get("/api/geografia")
def get_analise_geografica(
    ano: Optional[int | str] = Query(None),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
    apenas_privado: bool = Query(False),
    modo_recurso: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna análise territorial e rotas de financiamento interestadual."""
    modo = str(modo_recurso).lower() if modo_recurso else ("privado" if apenas_privado else "todos")
    chave_cache = f"{ano}_{cargo}_{uf}_{partido}_{modo}"
    if chave_cache in cache_geografia:
        return cache_geografia[chave_cache]

    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo
    )

    # 1. Panorama UF para o Heatmap (Para Presidente, mapeia a origem das doações por estado)
    is_presidente = bool(cargo and str(cargo).strip().upper() == "PRESIDENTE")
    if is_presidente:
        coluna_geo = "sigla_uf_doador"
        cond_geo = "sigla_uf_doador IS NOT NULL AND sigla_uf_doador NOT IN ('', 'BR', '-')"
    else:
        coluna_geo = "uf_candidato"
        cond_geo = "uf_candidato IS NOT NULL AND uf_candidato NOT IN ('', 'BR')"

    panorama_uf = query_df(
        f"""
        SELECT
            {coluna_geo} as uf,
            SUM(valor_receita) as total
        FROM eleicoes
        {where} AND {cond_geo}
        GROUP BY {coluna_geo}
        ORDER BY total DESC
        """,
        params,
    ).to_dict(orient="records")

    ranking_estados = [{"uf": str(r["uf"]), "total": float(r["total"])} for r in panorama_uf[:10]]

    # 1.1 Análise específica para quando 1 único estado é filtrado
    uf_str = uf if isinstance(uf, str) else ""
    ufs_limpas = [u.strip().upper() for u in uf_str.split(",") if u.strip().upper() not in ("TODAS", "")]
    cargo_str = cargo if isinstance(cargo, str) else ""
    if not ufs_limpas and cargo_str and cargo_str.strip().upper() == "DEPUTADO DISTRITAL":
        ufs_limpas = ["DF"]
    is_estado_unico = len(ufs_limpas) == 1
    uf_selecionada = ufs_limpas[0] if is_estado_unico else None
    distribuicao_partidos_uf = []
    distribuicao_cargos_uf = []

    if is_estado_unico:
        distribuicao_partidos_uf = query_df(
            f"""
            SELECT
                COALESCE(sigla_partido, 'S/P') as partido,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            GROUP BY sigla_partido
            ORDER BY total DESC
            LIMIT 10
            """,
            params,
        ).to_dict(orient="records")

        distribuicao_cargos_uf = query_df(
            f"""
            SELECT
                cargo,
                SUM(valor_receita) as total
            FROM eleicoes
            {where}
            AND cargo IS NOT NULL AND TRIM(cargo) != '' AND UPPER(cargo) NOT IN ('-', 'NÃO INFORMADO', 'NAN')
            GROUP BY cargo
            ORDER BY total DESC
            LIMIT 10
            """,
            params,
        ).to_dict(orient="records")

    # 2. Rotas Interestaduais de Influência (Origem != Destino) - Consulta Bidirecional com Resolução de Sede
    where_rotas_e, params_rotas = construir_clausula_where(
        ano=ano, cargo=cargo, uf=None, partido=partido, modo_recurso=modo, alias="e"
    )
    if is_estado_unico:
        where_rotas_e += " AND (UPPER(e.uf_candidato) = ? OR UPPER(COALESCE(e.uf_empresa, e.sigla_uf_doador, s.uf_origem)) = ?)"
        params_rotas.extend([uf_selecionada, uf_selecionada])
    elif ufs_limpas:
        ph = ", ".join(["?"] * len(ufs_limpas))
        where_rotas_e += f" AND (UPPER(e.uf_candidato) IN ({ph}) OR UPPER(COALESCE(e.uf_empresa, e.sigla_uf_doador, s.uf_origem)) IN ({ph}))"
        params_rotas.extend(ufs_limpas + ufs_limpas)

    rotas_df = query_df(
        f"""
        WITH DoacoesComOrigem AS (
            SELECT
                COALESCE(NULLIF(e.uf_empresa, 'BR'), NULLIF(e.sigla_uf_doador, 'BR'), s.uf_origem) as uf_origem,
                COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR') as uf_destino,
                e.valor_receita,
                e.cpf_cnpj_doador,
                e.nome_doador,
                e.nome_candidato,
                e.cargo,
                e.sigla_partido,
                e.is_empresario,
                e.is_eleito
            FROM eleicoes e
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_rotas_e}
        )
        SELECT
            uf_origem,
            uf_destino,
            SUM(valor_receita) as volume,
            COUNT(*) as transacoes,
            COUNT(DISTINCT cpf_cnpj_doador) as doadores,
            ARG_MAX(COALESCE(nome_doador, 'NÃO INFORMADO'), valor_receita) as principal_doador,
            ARG_MAX(COALESCE(nome_candidato, 'NÃO INFORMADO'), valor_receita) as principal_candidato,
            ARG_MAX(COALESCE(cargo, '-'), valor_receita) as principal_cargo,
            ARG_MAX(COALESCE(sigla_partido, '-'), valor_receita) as principal_partido,
            SUM(CASE WHEN is_empresario = TRUE THEN valor_receita ELSE 0.0 END) as volume_empresarios,
            SUM(CASE WHEN is_eleito = TRUE THEN valor_receita ELSE 0.0 END) as volume_para_eleitos
        FROM DoacoesComOrigem
        WHERE uf_origem IS NOT NULL AND TRIM(uf_origem) != '' AND uf_origem != 'BR'
        AND uf_destino IS NOT NULL AND TRIM(uf_destino) != ''
        AND uf_origem != uf_destino
        GROUP BY uf_origem, uf_destino
        ORDER BY volume DESC
        LIMIT 15
        """,
        params_rotas,
    )
    rotas = rotas_df.to_dict(orient="records") if not rotas_df.empty else []

    # Enriquecimento com Detalhes Consolidados (Montante Acumulado por Par Doador -> Candidato na Rota)
    if rotas:
        rotas_tuples = [(r["uf_origem"], r["uf_destino"]) for r in rotas]
        ph_rotas = ", ".join([f"('{orig}', '{dest}')" for orig, dest in rotas_tuples])
        detalhes_rotas_df = query_df(
            f"""
            WITH DoacoesAgrupadas AS (
                SELECT
                    COALESCE(NULLIF(e.uf_empresa, 'BR'), NULLIF(e.sigla_uf_doador, 'BR'), s.uf_origem) as uf_origem,
                    COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR') as uf_destino,
                    COALESCE(e.nome_doador, 'NÃO INFORMADO') as doador,
                    COALESCE(NULLIF(e.razao_social, ''), '-') as empresa,
                    COALESCE(e.nome_candidato, 'NÃO INFORMADO') as candidato,
                    COALESCE(e.cargo, '-') as cargo,
                    COALESCE(e.sigla_partido, '-') as partido,
                    SUM(e.valor_receita) as valor_receita,
                    COUNT(*) as qtd_aportes,
                    BOOL_OR(e.is_eleito) as is_eleito,
                    ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(NULLIF(e.uf_empresa, 'BR'), NULLIF(e.sigla_uf_doador, 'BR'), s.uf_origem), COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR')
                        ORDER BY SUM(e.valor_receita) DESC
                    ) as rn
                FROM eleicoes e
                LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
                {where_rotas_e}
                AND (COALESCE(NULLIF(e.uf_empresa, 'BR'), NULLIF(e.sigla_uf_doador, 'BR'), s.uf_origem), COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR')) IN ({ph_rotas})
                GROUP BY 1, 2, 3, 4, 5, 6, 7
            )
            SELECT * FROM DoacoesAgrupadas WHERE rn <= 25 ORDER BY uf_origem, uf_destino, valor_receita DESC
            """,
            params_rotas,
        )
        for r in rotas:
            sub = detalhes_rotas_df[
                (detalhes_rotas_df["uf_origem"] == r["uf_origem"]) & 
                (detalhes_rotas_df["uf_destino"] == r["uf_destino"])
            ]
            r["detalhes"] = sub.to_dict(orient="records") if not sub.empty else []

    # 3. KPIs Territoriais
    where_e, params_e = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo, alias="e"
    )
    row_kpis = query_fetchone(
        f"""
        WITH DoacoesComOrigem AS (
            SELECT
                e.valor_receita,
                e.uf_candidato,
                COALESCE(NULLIF(e.uf_empresa, 'BR'), NULLIF(e.sigla_uf_doador, 'BR'), s.uf_origem) as uf_origem,
                COALESCE(NULLIF(TRIM(e.uf_candidato), ''), 'BR') as uf_destino
            FROM eleicoes e
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_e}
        )
        SELECT
            COALESCE(SUM(valor_receita), 0.0) as volume_total,
            COUNT(DISTINCT uf_candidato) as ufs_ativas,
            COUNT(DISTINCT CASE WHEN uf_origem IS NOT NULL AND uf_origem != 'BR' AND uf_origem != uf_destino THEN (uf_origem || '->' || uf_destino) END) as total_rotas,
            COALESCE(SUM(CASE WHEN uf_origem IS NOT NULL AND uf_origem != 'BR' AND uf_origem != uf_destino THEN valor_receita ELSE 0.0 END), 0.0) as volume_interestadual
        FROM DoacoesComOrigem
        """,
        params_e,
    )

    resultado_final = {
        "kpis": {
            "volume_total": float(row_kpis[0] or 0.0),
            "ufs_ativas": int(row_kpis[1] or 0),
            "total_rotas_interestaduais": int(row_kpis[2] or 0),
            "volume_interestadual": float(row_kpis[3] or 0.0),
        },
        "is_estado_unico": is_estado_unico,
        "uf_selecionada": ufs_limpas[0] if is_estado_unico else None,
        "distribuicao_partidos_uf": distribuicao_partidos_uf,
        "distribuicao_cargos_uf": distribuicao_cargos_uf,
        "panorama_uf": panorama_uf,
        "ranking_estados": ranking_estados,
        "rotas_influencia": rotas,
    }

    if len(cache_geografia) >= 100:
        del cache_geografia[next(iter(cache_geografia))]
    cache_geografia[chave_cache] = resultado_final
    return resultado_final


# ==============================================================================
# ENDPOINT: CUSTO DO VOTO (PROMPT 2 / AGENTS.MD - SCATTER ONLY 1 ANO + 1 CARGO)
# ==============================================================================
cache_custo_voto: Dict[str, Any] = {}


@app.get("/api/custo-do-voto")
def get_custo_do_voto(
    ano: int | str = Query(..., description="Ano eleitoral obrigatório ou anos agregados por ciclo"),
    cargo: str = Query(..., description="Cargo obrigatório específico"),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    apenas_privado: bool = Query(False),
    modo_recurso: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna dados de Custo do Voto (Scatter Plot). Exige obrigatoriamente 1 Ano E 1 Cargo."""
    if not isinstance(cargo, str) or not cargo.strip():
        raise HTTPException(
            status_code=400,
            detail="O módulo Custo do Voto exige a seleção obrigatória de 1 Cargo específico.",
        )

    modo = str(modo_recurso).lower() if modo_recurso else ("privado" if apenas_privado else "todos")
    chave_cache = f"{ano}_{cargo}_{uf}_{partido}_{modo}"
    if chave_cache in cache_custo_voto:
        return cache_custo_voto[chave_cache]

    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo
    )

    # Calcula total_receita, total_votos e custo_voto diretamente no DuckDB por candidatura canônica (ano, cpf_candidato, cargo)
    df_cand = query_df(
        f"""
        SELECT
            ano,
            cpf_candidato,
            COALESCE(MAX(nome_candidato), 'NÃO INFORMADO') as nome_candidato,
            COALESCE(MAX(sigla_partido), 'S/P') as partido,
            COALESCE(cargo, '-') as cargo,
            COALESCE(MAX(total_votos), 0) as total_votos,
            COALESCE(SUM(valor_receita), 0.0) as total_receita,
            CASE
                WHEN COALESCE(MAX(total_votos), 0) > 0
                THEN COALESCE(SUM(valor_receita), 0.0) / MAX(total_votos)
                ELSE 0.0
            END as custo_voto,
            MAX(CAST(is_eleito AS INT)) as eleito
        FROM eleicoes
        {where}
        GROUP BY ano, cpf_candidato, cargo
        """,
        params,
    )

    if df_cand.empty:
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

    df_cand["eleito"] = df_cand["eleito"].fillna(0).astype(int)
    df_cand["status_eleicao"] = np.where(df_cand["eleito"] == 1, "Eleito", "Não Eleito")

    # Piso de viabilidade = menor receita positiva entre eleitos
    eleitos = df_cand[df_cand["eleito"] == 1]
    if not eleitos.empty and (eleitos["total_receita"] > 0).any():
        piso_viabilidade = float(eleitos.loc[eleitos["total_receita"] > 0, "total_receita"].min())
    else:
        piso_viabilidade = 0.0

    mediana_custo = (
        float(df_cand.loc[df_cand["custo_voto"] > 0, "custo_voto"].median())
        if (df_cand["custo_voto"] > 0).any()
        else 0.0
    )

    # Pontos para o Scatter Plot (limita a 5.000 pontos mais relevantes em recortes nacionais gigantes para fluidez do navegador)
    df_positivos = df_cand[df_cand["total_votos"] > 0]
    if len(df_positivos) > 5000:
        df_positivos = df_positivos.nlargest(5000, "total_receita")

    pontos = df_positivos[
        ["ano", "cpf_candidato", "nome_candidato", "partido", "cargo", "total_votos", "total_receita", "custo_voto", "status_eleicao"]
    ].to_dict(orient="records")

    resultado_final = {
        "piso_viabilidade": piso_viabilidade,
        "pontos": pontos,
        "resumo": {
            "total_candidatos": len(df_cand),
            "total_eleitos": int(df_cand["eleito"].sum()),
            "total_nao_eleitos": int((df_cand["eleito"] == 0).sum()),
            "mediana_custo_voto": mediana_custo,
        },
    }

    if len(cache_custo_voto) >= 100:
        del cache_custo_voto[next(iter(cache_custo_voto))]
    cache_custo_voto[chave_cache] = resultado_final
    return resultado_final


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
    apenas_privado: bool = Query(False),
) -> Dict[str, Any]:
    """Retorna análise de Porta Giratória expurgando repasses institucionais e aliados via Regex."""
    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, apenas_privado=apenas_privado
    )

    where_pg = where + " AND valor_receita > 0 AND valor_recebido_como_fornecedor > 0"

    row_kpis = query_fetchone(
        f"""
        SELECT
            SUM(valor_recebido_como_fornecedor) as volume_total,
            COUNT(*) as transacoes,
            COUNT(DISTINCT cpf_candidato) as campanhas,
            MAX(valor_recebido_como_fornecedor / NULLIF(valor_receita, 0)) as maior_taxa
        FROM eleicoes
        {where_pg}
        """,
        params,
    )

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
                "maior_taxa_retorno": 0.0,
            },
            "ranking_porta_giratoria": [],
            "comparativo_bidirecional": [],
        }

    filtro_servicos = r"(PAGAMENTO|TECNOLOGIA|SERVICO|SERVIÇO|BANCO|FACEBOOK|GOOGLE|CORREIOS|TELECOM|INTERNET|MIDIA|MÍDIA)"
    termos_excluir = r"DIRETORIO|PARTIDO|ELEICAO|ELEIÇÃO|ELAICAO|ELAIÇÃO|CAMPANHA|COMITE|COMITÊ|FEDERACAO|FEDERAÇÃO|DIREÇÃO|ÓRGÃO|FUNDO ESPECIAL|PROVISORIA|PROVISÓRIA|MUNICIPAL|ESTADUAL|NACIONAL"
    where_limpo = where_pg + f"""
        AND NOT regexp_matches(UPPER(COALESCE(nome_doador, '')), '{filtro_servicos}')
        AND NOT regexp_matches(UPPER(COALESCE(nome_doador, '')), '{termos_excluir}')
        AND NOT regexp_matches(UPPER(COALESCE(nome_candidato, '')), '{termos_excluir}')
    """

    ranking = query_df(
        f"""
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
        """,
        params,
    ).to_dict(orient="records")

    comparativo = query_df(
        f"""
        SELECT
            COALESCE(nome_doador, 'NÃO INFORMADO') as nome_doador,
            SUM(valor_receita) as total_doado,
            SUM(valor_recebido_como_fornecedor) as total_fornecedor
        FROM eleicoes
        {where_limpo}
        GROUP BY nome_doador
        ORDER BY total_fornecedor DESC
        LIMIT 10
        """,
        params,
    ).to_dict(orient="records")

    return {
        "kpis": {
            "volume_total_retorno": volume_retorno,
            "transacoes_identificadas": transacoes,
            "campanhas_com_ocorrencia": campanhas,
            "maior_taxa_retorno": maior_taxa,
        },
        "ranking_porta_giratoria": ranking,
        "comparativo_bidirecional": comparativo,
    }


# ==============================================================================
# ENDPOINT: TEIA EMPRESARIAL & SETORES ECONÔMICOS (NOVA INTELIGÊNCIA CNAE)
# ==============================================================================
cache_teia: Dict[str, Any] = {}


@app.get("/api/teia-empresarial")
def get_teia_empresarial(
    ano: Optional[int | str] = Query(None),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
    apenas_privado: bool = Query(False),
    modo_recurso: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna análise aprofundada dos setores econômicos (CNAE), grupos empresariais e taxa de sucesso."""
    modo = str(modo_recurso).lower() if modo_recurso else ("privado" if apenas_privado else "todos")
    chave_cache = f"{ano}_{cargo}_{uf}_{partido}_{modo}"
    if chave_cache in cache_teia:
        return cache_teia[chave_cache]

    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo
    )

    # 1. KPIs da Elite Empresarial no recorte
    row_elite = query_fetchone(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN is_empresario = TRUE THEN valor_receita ELSE 0.0 END), 0.0) as volume_elite,
            COUNT(DISTINCT CASE WHEN is_empresario = TRUE THEN cpf_cnpj_doador END) as doadores_elite,
            COUNT(DISTINCT CASE WHEN is_empresario = TRUE THEN cnpj_basico END) as empresas_conectadas,
            COALESCE(SUM(CASE WHEN is_empresario = TRUE AND is_eleito = TRUE THEN valor_receita ELSE 0.0 END), 0.0) as volume_para_eleitos
        FROM eleicoes
        {where}
        """,
        params,
    )

    row_sucesso = query_fetchone(
        f"""
        WITH Patrocinio AS (
            SELECT
                ano,
                cpf_candidato,
                cargo,
                MAX(CAST(is_empresario AS INT)) as teve_empresario,
                MAX(CAST(is_eleito AS INT)) as eleito
            FROM eleicoes
            {where}
            GROUP BY ano, cpf_candidato, cargo
        )
        SELECT
            COALESCE(AVG(CASE WHEN teve_empresario = 1 THEN eleito * 100.0 END), 0.0) as sucesso_com_empresario,
            COALESCE(AVG(CASE WHEN teve_empresario = 0 THEN eleito * 100.0 END), 0.0) as sucesso_sem_empresario,
            COALESCE(SUM(eleito), 0) as total_eleitos_recorte,
            COUNT(*) as total_candidaturas_recorte
        FROM Patrocinio
        """,
        params,
    )

    # 2. Top Setores Econômicos (CNAE) com Detalhamento Rico de Doadores e Empresas
    where_e, params_e = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo, alias="e"
    )
    top_setores_raw = query_df(
        f"""
        SELECT
            COALESCE(e.setor_economico, 'NÃO INFORMADO') as setor,
            SUM(e.valor_receita) as total,
            COUNT(*) as transacoes,
            COUNT(DISTINCT e.cpf_cnpj_doador) as doadores,
            COUNT(DISTINCT NULLIF(UPPER(TRIM(e.razao_social)), 'NÃO APLICÁVEL')) as empresas_unicas,
            ARG_MAX(
                CASE 
                    WHEN e.razao_social IS NULL OR TRIM(e.razao_social) = '' OR UPPER(e.razao_social) = 'NÃO APLICÁVEL' 
                    THEN 'Sem Razão Social Mapeada' 
                    ELSE e.razao_social 
                END, 
                e.valor_receita
            ) as principal_empresa,
            ARG_MAX(COALESCE(NULLIF(e.uf_empresa, 'BR'), s.uf_origem, NULLIF(e.sigla_uf_doador, 'BR'), '-'), e.valor_receita) as uf_principal_empresa,
            ARG_MAX(COALESCE(e.nome_doador, 'NÃO INFORMADO'), e.valor_receita) as principal_socio,
            ARG_MAX(COALESCE(e.nome_candidato, 'NÃO INFORMADO'), e.valor_receita) as principal_candidato,
            ARG_MAX(COALESCE(e.sigla_partido, '-'), e.valor_receita) as partido_destaque,
            ARG_MAX(COALESCE(e.cargo, '-'), e.valor_receita) as cargo_destaque,
            ARG_MAX(COALESCE(e.uf_candidato, '-'), e.valor_receita) as uf_campanha_destaque,
            SUM(CASE WHEN e.is_eleito = TRUE THEN e.valor_receita ELSE 0.0 END) as volume_para_eleitos
        FROM eleicoes e
        LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
        {where_e}
        AND e.is_empresario = TRUE
        AND e.setor_economico IS NOT NULL AND TRIM(e.setor_economico) != ''
        GROUP BY e.setor_economico
        ORDER BY total DESC
        LIMIT 10
        """,
        params_e,
    )

    top_setores = []
    if not top_setores_raw.empty:
        setores_nomes = top_setores_raw["setor"].tolist()
        placeholders_s = ", ".join(["?"] * len(setores_nomes))
        detalhes_setores_df = query_df(
            f"""
            SELECT
                COALESCE(e.setor_economico, 'NÃO INFORMADO') as setor,
                CASE 
                    WHEN e.razao_social IS NULL OR TRIM(e.razao_social) = '' OR UPPER(e.razao_social) = 'NÃO APLICÁVEL' 
                    THEN 'Sem Razão Social Mapeada (QSA Residual)' 
                    ELSE e.razao_social 
                END as empresa,
                COALESCE(MAX(NULLIF(e.uf_empresa, 'BR')), MAX(s.uf_origem), MAX(NULLIF(e.sigla_uf_doador, 'BR')), '-') as uf_empresa,
                COALESCE(e.nome_doador, 'NÃO INFORMADO') as socio,
                COALESCE(e.nome_candidato, 'NÃO INFORMADO') as candidato,
                COALESCE(e.sigla_partido, '-') as partido,
                COALESCE(e.cargo, '-') as cargo,
                COALESCE(e.uf_candidato, '-') as uf,
                COUNT(*) as qtd_aportes,
                BOOL_OR(e.is_eleito) as is_eleito,
                SUM(e.valor_receita) as total_doado
            FROM eleicoes e
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_e}
            AND e.is_empresario = TRUE
            AND COALESCE(e.setor_economico, 'NÃO INFORMADO') IN ({placeholders_s})
            GROUP BY 1, 2, 4, 5, 6, 7, 8
            ORDER BY total_doado DESC
            """,
            params_e + setores_nomes,
        )
        for _, s_row in top_setores_raw.iterrows():
            s_nome = s_row["setor"]
            sub_df = detalhes_setores_df[detalhes_setores_df["setor"] == s_nome].head(25)
            detalhes = sub_df.to_dict(orient="records")
            top_setores.append({
                "setor": s_nome,
                "total": float(s_row["total"]),
                "transacoes": int(s_row["transacoes"] or 0),
                "doadores": int(s_row["doadores"]),
                "empresas_unicas": int(s_row["empresas_unicas"] or 0),
                "principal_empresa": str(s_row["principal_empresa"] or "-"),
                "uf_principal_empresa": str(s_row["uf_principal_empresa"] or "-"),
                "principal_socio": str(s_row["principal_socio"] or "-"),
                "principal_candidato": str(s_row["principal_candidato"] or "-"),
                "partido_destaque": str(s_row["partido_destaque"] or "-"),
                "cargo_destaque": str(s_row["cargo_destaque"] or "-"),
                "uf_campanha_destaque": str(s_row["uf_campanha_destaque"] or "-"),
                "volume_para_eleitos": float(s_row["volume_para_eleitos"]),
                "detalhes": detalhes,
            })

    # 3. Top Grupos Empresariais / Razões Sociais
    top_empresas_raw = query_df(
        f"""
        SELECT
            COALESCE(e.razao_social, 'NÃO IDENTIFICADO') as empresa,
            COALESCE(MAX(e.cnpj_basico), '-') as cnpj_basico,
            COALESCE(MAX(NULLIF(e.uf_empresa, 'BR')), MAX(s.uf_origem), MAX(NULLIF(e.sigla_uf_doador, 'BR')), '-') as uf_empresa,
            COALESCE(MAX(e.setor_economico), '-') as setor,
            SUM(e.valor_receita) as total,
            COUNT(*) as transacoes,
            COUNT(DISTINCT e.cpf_cnpj_doador) as socios_doadores,
            COUNT(DISTINCT e.nome_candidato) as candidatos_apoiados,
            COUNT(DISTINCT e.sigla_partido) as partidos_apoiados,
            ARG_MAX(COALESCE(e.nome_candidato, 'NÃO INFORMADO'), e.valor_receita) as principal_candidato,
            ARG_MAX(COALESCE(e.cargo, '-'), e.valor_receita) as cargo_destaque,
            ARG_MAX(COALESCE(e.sigla_partido, '-'), e.valor_receita) as partido_destaque,
            ARG_MAX(COALESCE(e.uf_candidato, '-'), e.valor_receita) as uf_campanha_destaque,
            ARG_MAX(COALESCE(e.nome_doador, '-'), e.valor_receita) as principal_socio,
            SUM(CASE WHEN e.is_eleito = TRUE THEN e.valor_receita ELSE 0.0 END) as volume_para_eleitos
        FROM eleicoes e
        LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
        {where_e}
        AND e.is_empresario = TRUE
        AND e.razao_social IS NOT NULL AND TRIM(e.razao_social) != '' AND UPPER(e.razao_social) != 'NÃO APLICÁVEL'
        GROUP BY e.razao_social
        ORDER BY total DESC
        LIMIT 10
        """,
        params_e,
    )
    top_empresas = top_empresas_raw.to_dict(orient="records") if not top_empresas_raw.empty else []
    if top_empresas:
        empresas_nomes = [e["empresa"] for e in top_empresas if e.get("empresa")]
        if empresas_nomes:
            ph_emp = ", ".join(["?"] * len(empresas_nomes))
            detalhes_emp_df = query_df(
                f"""
                WITH DoacoesEmpresaAgrupadas AS (
                    SELECT
                        COALESCE(e.razao_social, 'NÃO IDENTIFICADO') as empresa,
                        COALESCE(e.nome_doador, 'NÃO INFORMADO') as socio,
                        COALESCE(MAX(NULLIF(e.uf_empresa, 'BR')), MAX(s.uf_origem), MAX(NULLIF(e.sigla_uf_doador, 'BR')), '-') as uf_socio,
                        COALESCE(e.nome_candidato, 'NÃO INFORMADO') as candidato,
                        COALESCE(e.cargo, '-') as cargo,
                        COALESCE(e.sigla_partido, '-') as partido,
                        COALESCE(e.uf_candidato, '-') as uf_candidato,
                        SUM(e.valor_receita) as valor_receita,
                        COUNT(*) as qtd_aportes,
                        BOOL_OR(e.is_eleito) as is_eleito,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(e.razao_social, 'NÃO IDENTIFICADO')
                            ORDER BY SUM(e.valor_receita) DESC
                        ) as rn
                    FROM eleicoes e
                    LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
                    {where_e}
                    AND e.is_empresario = TRUE
                    AND e.razao_social IN ({ph_emp})
                    GROUP BY 1, 2, 4, 5, 6, 7
                )
                SELECT * FROM DoacoesEmpresaAgrupadas WHERE rn <= 25 ORDER BY empresa, valor_receita DESC
                """,
                params_e + empresas_nomes,
            )
            for emp in top_empresas:
                sub = detalhes_emp_df[detalhes_emp_df["empresa"] == emp["empresa"]]
                emp["detalhes"] = sub.to_dict(orient="records") if not sub.empty else []

    # 4. Maiores Sócios e Líderes Empresariais com Campanha Principal e Empresa Detalhada
    maiores_socios_raw = query_df(
        f"""
        WITH DoadoresAportes AS (
            SELECT
                COALESCE(e.nome_doador, 'NÃO INFORMADO') as socio,
                COALESCE(NULLIF(e.uf_empresa, 'BR'), s.uf_origem, NULLIF(e.sigla_uf_doador, 'BR'), NULLIF(e.uf_candidato, 'BR'), '-') as uf,
                COALESCE(NULLIF(e.uf_empresa, 'BR'), '-') as uf_empresa,
                COALESCE(NULLIF(TRIM(e.cnpj_basico), ''), '-') as cnpj_basico,
                CASE 
                    WHEN e.razao_social IS NULL OR TRIM(e.razao_social) = '' OR UPPER(e.razao_social) = 'NÃO APLICÁVEL' 
                    THEN 'Sem Razão Social Mapeada (QSA Residual)' 
                    ELSE e.razao_social 
                END as empresa,
                COALESCE(e.setor_economico, '-') as setor,
                COALESCE(e.nome_candidato, 'NÃO INFORMADO') as nome_candidato,
                COALESCE(e.cargo, '-') as cargo,
                COALESCE(e.sigla_partido, '-') as sigla_partido,
                COALESCE(e.uf_candidato, '-') as uf_candidato,
                e.valor_receita,
                e.is_eleito,
                ROW_NUMBER() OVER (PARTITION BY e.nome_doador ORDER BY e.valor_receita DESC) as rn
            FROM eleicoes e
            LEFT JOIN sede_doadores s ON e.nome_doador = s.nome_doador
            {where_e}
            AND e.is_empresario = TRUE
            AND NOT regexp_matches(UPPER(COALESCE(e.nome_doador, '')), '{REGEX_CROWD}')
        )
        SELECT
            socio,
            MAX(uf) as uf,
            MAX(uf_empresa) as uf_empresa,
            MAX(CASE WHEN rn = 1 THEN empresa END) as empresa,
            MAX(CASE WHEN rn = 1 THEN setor END) as setor,
            COUNT(DISTINCT NULLIF(empresa, 'Sem Razão Social Mapeada (QSA Residual)')) as qtd_empresas,
            COUNT(DISTINCT NULLIF(cnpj_basico, '-')) as qtd_cnpjs,
            LIST(DISTINCT empresa) FILTER (WHERE empresa != 'Sem Razão Social Mapeada (QSA Residual)') as lista_empresas,
            SUM(valor_receita) as total,
            COUNT(*) as transacoes,
            COUNT(DISTINCT nome_candidato) as candidatos_apoiados,
            COUNT(DISTINCT sigla_partido) as partidos_apoiados,
            SUM(CASE WHEN is_eleito = TRUE THEN valor_receita ELSE 0.0 END) as volume_para_eleitos,
            MAX(CASE WHEN rn = 1 THEN nome_candidato END) as principal_candidato,
            MAX(CASE WHEN rn = 1 THEN cargo END) as cargo_destaque,
            MAX(CASE WHEN rn = 1 THEN sigla_partido END) as partido_destaque,
            MAX(CASE WHEN rn = 1 THEN uf_candidato END) as uf_campanha_destaque
        FROM DoadoresAportes
        GROUP BY socio
        ORDER BY total DESC
        LIMIT 10
        """,
        params_e,
    )
    maiores_socios = maiores_socios_raw.to_dict(orient="records") if not maiores_socios_raw.empty else []
    for sc in maiores_socios:
        raw_lista = sc.get("lista_empresas")
        if raw_lista is None or (isinstance(raw_lista, float) and np.isnan(raw_lista)):
            sc["lista_empresas"] = []
        else:
            sc["lista_empresas"] = [str(x) for x in list(raw_lista) if x is not None and pd.notna(x)]
        sc["qtd_cnpjs"] = int(sc.get("qtd_cnpjs") or 0)
    if maiores_socios:
        socios_nomes = [s["socio"] for s in maiores_socios if s.get("socio")]
        if socios_nomes:
            ph_soc = ", ".join(["?"] * len(socios_nomes))
            detalhes_soc_df = query_df(
                f"""
                WITH DoacoesSocioAgrupadas AS (
                    SELECT
                        COALESCE(e.nome_doador, 'NÃO INFORMADO') as socio,
                        COALESCE(e.nome_candidato, 'NÃO INFORMADO') as candidato,
                        COALESCE(e.cargo, '-') as cargo,
                        COALESCE(e.sigla_partido, '-') as partido,
                        COALESCE(e.uf_candidato, '-') as uf_candidato,
                        CASE 
                            WHEN e.razao_social IS NULL OR TRIM(e.razao_social) = '' OR UPPER(e.razao_social) = 'NÃO APLICÁVEL' 
                            THEN 'Sem Razão Social Mapeada (QSA Residual)' 
                            ELSE e.razao_social 
                        END as empresa,
                        COALESCE(MAX(e.setor_economico), '-') as setor,
                        SUM(e.valor_receita) as valor_receita,
                        COUNT(*) as qtd_aportes,
                        BOOL_OR(e.is_eleito) as is_eleito,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(e.nome_doador, 'NÃO INFORMADO')
                            ORDER BY SUM(e.valor_receita) DESC
                        ) as rn
                    FROM eleicoes e
                    {where_e}
                    AND e.is_empresario = TRUE
                    AND e.nome_doador IN ({ph_soc})
                    GROUP BY 1, 2, 3, 4, 5, 6
                )
                SELECT * FROM DoacoesSocioAgrupadas WHERE rn <= 25 ORDER BY socio, valor_receita DESC
                """,
                params_e + socios_nomes,
            )
            for sc in maiores_socios:
                sub = detalhes_soc_df[detalhes_soc_df["socio"] == sc["socio"]]
                sc["detalhes"] = sub.to_dict(orient="records") if not sub.empty else []

    resultado_final = {
        "kpis": {
            "volume_elite": float(row_elite[0] or 0.0),
            "doadores_elite": int(row_elite[1] or 0),
            "empresas_conectadas": int(row_elite[2] or 0),
            "volume_para_eleitos": float(row_elite[3] or 0.0),
            "sucesso_com_empresario": float(row_sucesso[0] or 0.0),
            "sucesso_sem_empresario": float(row_sucesso[1] or 0.0),
            "total_eleitos_recorte": int(row_sucesso[2] or 0) if row_sucesso else 0,
            "total_candidaturas_recorte": int(row_sucesso[3] or 0) if row_sucesso else 0,
        },
        "top_setores": top_setores,
        "top_empresas": top_empresas,
        "maiores_socios": maiores_socios,
    }

    if len(cache_teia) >= 100:
        del cache_teia[next(iter(cache_teia))]
    cache_teia[chave_cache] = resultado_final
    return resultado_final


# ==============================================================================
# ENDPOINT: ORIGEM DOS RECURSOS & AUTOFINANCIAMENTO (PROMPT 3 / AGENTS.MD)
# ==============================================================================
cache_autofinanciamento: Dict[str, Any] = {}


@app.get("/api/origem-autofinanciamento")
def get_origem_autofinanciamento(
    ano: Optional[int | str] = Query(None),
    cargo: Optional[str] = Query(None),
    uf: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
    apenas_privado: bool = Query(False),
    modo_recurso: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Retorna análise de origem de recursos e autofinanciamento com taxas de sucesso corrigidas."""
    modo = str(modo_recurso).lower() if modo_recurso else ("privado" if apenas_privado else "todos")
    chave_cache = f"{ano}_{cargo}_{uf}_{partido}_{modo}"
    if chave_cache in cache_autofinanciamento:
        return cache_autofinanciamento[chave_cache]

    where, params = construir_clausula_where(
        ano=ano, cargo=cargo, uf=uf, partido=partido, modo_recurso=modo
    )

    # Calcula os KPIs de autofinanciamento diretamente no DuckDB (fidelidade 100% às transações e candidatos)
    row_auto = query_fetchone(
        f"""
        WITH Transacoes AS (
            SELECT
                COUNT(*) as total_tx,
                SUM(CASE WHEN autofinanciamento = 1 THEN 1 ELSE 0 END) as ops_auto,
                COALESCE(SUM(CASE WHEN autofinanciamento = 1 THEN valor_receita ELSE 0.0 END), 0.0) as vol_auto,
                COALESCE(SUM(CASE WHEN COALESCE(autofinanciamento, 0) != 1 THEN valor_receita ELSE 0.0 END), 0.0) as vol_terceiros
            FROM eleicoes
            {where}
        ),
        Candidatos AS (
            SELECT
                ano,
                cpf_candidato,
                cargo,
                MAX(COALESCE(autofinanciamento, 0)) as usou_auto,
                MAX(CAST(COALESCE(is_eleito, FALSE) AS INT)) as eleito
            FROM eleicoes
            {where}
            GROUP BY ano, cpf_candidato, cargo
        ),
        Taxas AS (
            SELECT
                AVG(CASE WHEN usou_auto = 1 THEN eleito * 100.0 END) as sucesso_auto,
                AVG(CASE WHEN usou_auto = 0 THEN eleito * 100.0 END) as sucesso_terceiros
            FROM Candidatos
        )
        SELECT
            t.total_tx,
            t.ops_auto,
            t.vol_auto,
            t.vol_terceiros,
            COALESCE(tx.sucesso_auto, 0.0),
            COALESCE(tx.sucesso_terceiros, 0.0)
        FROM Transacoes t
        CROSS JOIN Taxas tx
        """,
        params + params,
    )

    if not row_auto or int(row_auto[0] or 0) == 0:
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

    total_tx = int(row_auto[0] or 0)
    ops_auto = int(row_auto[1] or 0)
    kpis_auto = {
        "taxa_autofinanciamento": float(ops_auto / total_tx * 100.0) if total_tx > 0 else 0.0,
        "volume_autofinanciamento": float(row_auto[2] or 0.0),
        "volume_terceiros": float(row_auto[3] or 0.0),
        "total_operacoes_auto": ops_auto,
        "taxa_sucesso_auto": float(row_auto[4] or 0.0),
        "taxa_sucesso_terceiros": float(row_auto[5] or 0.0),
    }

    # Maiores Investidores da Própria Campanha no recorte (direto no DuckDB com Blindagem de Candidatura)
    top_investidores = query_df(
        f"""
        SELECT
            COALESCE(MAX(nome_candidato), 'Não informado') as nome,
            COALESCE(MAX(sigla_partido), 'S/P') as partido,
            COALESCE(cargo, '-') as cargo,
            SUM(valor_receita) as total
        FROM eleicoes
        {where} AND autofinanciamento = 1
        GROUP BY ano, cpf_candidato, cargo
        ORDER BY total DESC
        LIMIT 10
        """,
        params,
    ).to_dict(orient="records")

    # Evolução histórica do autofinanciamento ao longo dos anos (ignorando filtro de ano único)
    where_hist, params_hist = construir_clausula_where(
        ano=None, cargo=None, uf=uf, partido=partido, apenas_privado=apenas_privado
    )
    evolucao = query_df(
        f"""
        SELECT
            ano,
            CASE WHEN autofinanciamento = 1 THEN 'Recursos Próprios' ELSE 'Terceiros' END as tipo,
            SUM(valor_receita) as total
        FROM eleicoes
        {where_hist}
        GROUP BY ano, autofinanciamento
        ORDER BY ano, tipo
        """,
        params_hist,
    )
    evolucao_records = evolucao[["ano", "tipo", "total"]].to_dict(orient="records")

    resultado_final = {
        "kpis": kpis_auto,
        "top_investidores_proprios": top_investidores,
        "evolucao_historica": evolucao_records,
    }

    if len(cache_autofinanciamento) >= 100:
        del cache_autofinanciamento[next(iter(cache_autofinanciamento))]
    cache_autofinanciamento[chave_cache] = resultado_final
    return resultado_final


# ==============================================================================
# EVENTO DE STARTUP: PRÉ-AQUECIMENTO DE CACHE (WARMUP)
# ==============================================================================
@app.on_event("startup")
def preaquecer_cache():
    """Pré-aquece o cache dos 3 modos de recursos ('privado', 'todos', 'elite') no startup."""
    logger.info("Iniciando pré-aquecimento de cache das métricas globais...")
    for modo in ["privado", "todos", "elite"]:
        try:
            get_global_metrics(modo_recurso=modo)
            logger.info("Cache global pré-aquecido com sucesso para modo: '%s'", modo)
        except Exception as exc:
            logger.warning("Falha ao pré-aquecer cache para modo '%s': %s", modo, exc)

