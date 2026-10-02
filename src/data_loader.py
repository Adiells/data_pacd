"""Módulo de carregamento e acesso a dados eleitorais.

Fornece funções com cache inteligente (Streamlit) para leitura em alta performance
usando DuckDB/PyArrow e utilitários para popular seletores e filtros na interface.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import streamlit as st

# Garante que a raiz do projeto esteja no sys.path para importações relativas
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.convert_csv_to_parquet import (
    DEFAULT_PARQUET_PATH,
    converter_csv_para_parquet,
)

logger = logging.getLogger(__name__)


@st.cache_data(show_spinner="Carregando base de dados eleitorais...")
def carregar_dados(caminho_parquet: str | Path | None = None) -> pd.DataFrame:
    """Carrega o DataFrame consolidado de eleições a partir de arquivo Parquet.

    Se o arquivo Parquet não existir no caminho indicado, dispara automaticamente
    o processo de conversão e ingestão do CSV bruto. Lê os dados de forma ultra-rápida
    utilizando a engine vetorial do DuckDB com fallback para PyArrow.

    Args:
        caminho_parquet: Caminho opcional para o arquivo Parquet. Caso omitido,
                         utiliza o caminho padrão do projeto.

    Returns:
        pd.DataFrame: DataFrame contendo a base consolidada de doações e candidaturas.

    Raises:
        RuntimeError: Se o arquivo não existir e a conversão automática falhar.
    """
    if caminho_parquet is None:
        parquet_path = PROJECT_ROOT / DEFAULT_PARQUET_PATH
    else:
        parquet_path = Path(caminho_parquet)

    # Dispara conversão automática se o arquivo Parquet não existir
    if not parquet_path.exists():
        logger.info(
            "Parquet '%s' não encontrado. Disparando pipeline de conversão...",
            parquet_path,
        )
        try:
            converter_csv_para_parquet(caminho_parquet=parquet_path)
        except Exception as exc:
            logger.error("Erro ao converter CSV para Parquet automaticamente: %s", exc)
            raise RuntimeError(
                f"Arquivo Parquet não encontrado e falha ao gerar automaticamente: {exc}"
            ) from exc

    # Leitura otimizada via DuckDB (com fallback para PyArrow)
    try:
        con = duckdb.connect(database=":memory:")
        try:
            # Lê diretamente da tabela Parquet para DataFrame pandas
            df: pd.DataFrame = con.execute(
                f"SELECT * FROM '{parquet_path.as_posix()}'"
            ).df()
            logger.info("Dados carregados com sucesso via DuckDB: %d registros.", len(df))
        finally:
            con.close()
    except Exception as duck_err:
        logger.warning(
            "Falha ao carregar via DuckDB (%s). Tentando fallback com PyArrow...",
            duck_err,
        )
        try:
            table = pq.read_table(parquet_path)
            df = table.to_pandas()
            logger.info("Dados carregados com sucesso via PyArrow: %d registros.", len(df))
        except Exception as arrow_err:
            logger.error("Falha ao carregar via PyArrow: %s", arrow_err)
            raise IOError(
                f"Não foi possível ler o arquivo Parquet em '{parquet_path}': {arrow_err}"
            ) from arrow_err

    # Força rigorosamente as colunas identificadoras como StringDtype
    colunas_string = ["cpf_candidato", "cpf_cnpj_doador", "cnpj_basico"]
    for col in colunas_string:
        if col in df.columns:
            df[col] = df[col].astype("string")

    return df


@st.cache_data
def obter_dimensao_candidatos(df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Extrai a tabela canônica de candidatos (dimensão não-duplicada).

    Evita o erro crítico de duplicação de votos decorrente da repetição de
    candidatos em múltiplas transações de doadores. Agrega o volume de receita
    pela soma e consolida o total_votos utilizando o valor máximo canônico.

    Args:
        df: DataFrame opcional contendo os dados brutos de doações.

    Returns:
        pd.DataFrame: DataFrame único por candidato, ano e cargo com votos não duplicados.
    """
    if df is None:
        df = carregar_dados()

    if df.empty:
        return pd.DataFrame()

    chaves_candidato = [
        "cpf_candidato",
        "nome_candidato",
        "cargo",
        "sigla_partido",
        "situacao",
    ]
    if "ano" in df.columns:
        chaves_candidato.insert(0, "ano")

    chaves_presentes = [c for c in chaves_candidato if c in df.columns]

    agg_dict: dict[str, str] = {}
    if "valor_receita" in df.columns:
        agg_dict["valor_receita"] = "sum"
    elif "total_receita" in df.columns:
        agg_dict["total_receita"] = "sum"

    if "total_votos" in df.columns:
        agg_dict["total_votos"] = "max"

    cand_dim = (
        df.groupby(chaves_presentes, as_index=False, dropna=False)
        .agg(agg_dict)
        .reset_index(drop=True)
    )

    if "valor_receita" in cand_dim.columns:
        cand_dim.rename(columns={"valor_receita": "total_receita"}, inplace=True)

    return cand_dim


@st.cache_data
def listar_anos(df: Optional[pd.DataFrame] = None) -> list[int]:
    """Retorna a lista ordenada dos anos eleitorais presentes na base.

    Args:
        df: DataFrame opcional. Se omitido, carrega a base padrão via cache.

    Returns:
        list[int]: Lista de anos distintos ordenados crescentemente.
    """
    if df is None:
        df = carregar_dados()

    if "ano" not in df.columns or df["ano"].empty:
        return []

    anos_validos = (
        pd.to_numeric(df["ano"], errors="coerce")
        .dropna()
        .astype(int)
        .unique()
    )
    return sorted(anos_validos.tolist())


@st.cache_data
def listar_cargos(df: Optional[pd.DataFrame] = None) -> list[str]:
    """Retorna a lista ordenada e higienizada dos cargos disputados.

    Args:
        df: DataFrame opcional. Se omitido, carrega a base padrão via cache.

    Returns:
        list[str]: Lista de cargos distintos ordenados alfabeticamente.
    """
    if df is None:
        df = carregar_dados()

    if "cargo" not in df.columns or df["cargo"].empty:
        return []

    cargos = (
        df["cargo"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    cargos_unicos = [c for c in cargos.unique() if c]
    return sorted(cargos_unicos)


@st.cache_data
def listar_partidos(df: Optional[pd.DataFrame] = None) -> list[str]:
    """Retorna a lista ordenada das siglas partidárias presentes na base.

    Args:
        df: DataFrame opcional. Se omitido, carrega a base padrão via cache.

    Returns:
        list[str]: Lista de siglas partidárias em caixa alta e ordenadas.
    """
    if df is None:
        df = carregar_dados()

    if "sigla_partido" not in df.columns or df["sigla_partido"].empty:
        return []

    partidos = (
        df["sigla_partido"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
    )
    partidos_unicos = [p for p in partidos.unique() if p]
    return sorted(partidos_unicos)


@st.cache_data
def listar_ufs(df: Optional[pd.DataFrame] = None) -> list[str]:
    """Retorna a lista ordenada das Unidades Federativas de doadores na base.

    Args:
        df: DataFrame opcional. Se omitido, carrega a base padrão via cache.

    Returns:
        list[str]: Lista de siglas de UF ordenadas alfabeticamente.
    """
    if df is None:
        df = carregar_dados()

    coluna_uf = None
    for candidata in ["sigla_uf_doador", "uf_doador", "sigla_uf"]:
        if candidata in df.columns:
            coluna_uf = candidata
            break

    if coluna_uf is None or df[coluna_uf].empty:
        return []

    ufs = (
        df[coluna_uf]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
    )
    ufs_unicas = [uf for uf in ufs.unique() if uf]
    return sorted(ufs_unicas)
