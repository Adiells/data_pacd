"""Módulo de carregamento e acesso a dados eleitorais.

Fornece funções com cache inteligente em memória para leitura em alta performance
usando DuckDB/PyArrow e utilitários para popular seletores e filtros na interface.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import requests

# Garante que a raiz do projeto esteja no sys.path para importações relativas
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_PARQUET_PATH = PROJECT_ROOT / "data" / "processed" / "base_consolidada_eleicoes.parquet"
PARQUET_DRIVE_FILE_ID = os.environ.get("PACD_PARQUET_DRIVE_ID", "1CAUL7QTz587o0VpUkfhLBPn2EpMEHfwN")

logger = logging.getLogger(__name__)


def parquet_integridade_valida(caminho_parquet: Path, min_size_bytes: int = 1_000_000) -> bool:
    """Verifica se o arquivo Parquet existe, possui tamanho válido e assinatura binária PAR1.

    Rejeita automaticamente arquivos ausentes, downloads interrompidos e ponteiros de
    texto do Git LFS (~130 bytes) que quebrariam o DuckDB/PyArrow.
    """
    if not caminho_parquet.exists() or not caminho_parquet.is_file():
        return False

    tamanho = caminho_parquet.stat().st_size
    if tamanho < min_size_bytes:
        return False

    try:
        with open(caminho_parquet, "rb") as f:
            header = f.read(4)
            f.seek(-4, os.SEEK_END)
            footer = f.read(4)
        return header == b"PAR1" and footer == b"PAR1"
    except OSError:
        return False


def garantir_parquet_local(
    caminho_parquet: str | Path = DEFAULT_PARQUET_PATH,
    file_id_drive: str = PARQUET_DRIVE_FILE_ID,
    forcar_download: bool = False,
) -> Path:
    """Garante que o arquivo Parquet consolidado exista localmente e seja íntegro.

    Se o arquivo estiver ausente ou corrompido (ex.: ponteiro Git LFS), baixa
    automaticamente a base consolidada a partir do Google Drive na primeira execução.
    """
    parquet_path = Path(caminho_parquet)

    if not forcar_download and parquet_integridade_valida(parquet_path):
        return parquet_path

    if not file_id_drive:
        raise RuntimeError(
            f"Arquivo Parquet inválido ou ausente em '{parquet_path}' e nenhum ID do Google Drive foi informado."
        )

    if parquet_path.exists():
        logger.warning(
            "Arquivo '%s' encontrado com integridade inválida (%d bytes — possível ponteiro LFS ou download incompleto). Baixando novamente do Google Drive...",
            parquet_path,
            parquet_path.stat().st_size,
        )
    else:
        logger.info(
            "Base Parquet ausente em '%s'. Iniciando ingestão automática via Google Drive (ID: %s)...",
            parquet_path,
            file_id_drive,
        )

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = parquet_path.with_suffix(".parquet.part")
    url = f"https://drive.usercontent.google.com/download?id={file_id_drive}&export=download&confirm=t"

    try:
        with requests.Session() as session:
            response = session.get(url, stream=True, timeout=120)
            response.raise_for_status()

            baixado = 0
            proximo_log_mb = 25
            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        baixado += len(chunk)
                        baixado_mb = baixado / (1024 * 1024)
                        if baixado_mb >= proximo_log_mb:
                            logger.info("Download do Parquet em andamento: %.1f MB...", baixado_mb)
                            proximo_log_mb += 25

        if not parquet_integridade_valida(temp_path):
            raise RuntimeError(
                f"Arquivo baixado do Google Drive (ID: {file_id_drive}) falhou na validação binária PAR1/tamanho."
            )

        temp_path.replace(parquet_path)
        logger.info(
            "Base Parquet salva e validada em '%s' (%.2f MB).",
            parquet_path,
            parquet_path.stat().st_size / (1024 * 1024),
        )
        return parquet_path
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        logger.error("Falha ao baixar a base Parquet do Google Drive: %s", exc)
        raise RuntimeError(
            f"Não foi possível garantir o arquivo Parquet em '{parquet_path}': {exc}"
        ) from exc


def carregar_dados(caminho_parquet: str | Path | None = None) -> pd.DataFrame:
    """Carrega o DataFrame consolidado de eleições a partir de arquivo Parquet.

    Se o arquivo Parquet não existir ou estiver corrompido (ex.: ponteiro Git LFS),
    dispara automaticamente o download via Google Drive. Lê os dados de forma
    ultra-rápida utilizando a engine vetorial do DuckDB com fallback para PyArrow.

    Args:
        caminho_parquet: Caminho opcional para o arquivo Parquet. Caso omitido,
                         utiliza o caminho padrão do projeto.

    Returns:
        pd.DataFrame: DataFrame contendo a base consolidada de doações e candidaturas.

    Raises:
        RuntimeError: Se o arquivo não existir e o download automático falhar.
    """
    parquet_path = DEFAULT_PARQUET_PATH if caminho_parquet is None else Path(caminho_parquet)

    # Garante existência e integridade binária do arquivo Parquet antes da leitura
    parquet_path = garantir_parquet_local(parquet_path)

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
        "uf_candidato",
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
    if "is_eleito" in df.columns:
        agg_dict["is_eleito"] = "max"

    cand_dim = (
        df.groupby(chaves_presentes, as_index=False, dropna=False)
        .agg(agg_dict)
        .reset_index(drop=True)
    )

    if "valor_receita" in cand_dim.columns:
        cand_dim = cand_dim.rename(columns={"valor_receita": "total_receita"})

    return cand_dim


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


def listar_ufs(df: Optional[pd.DataFrame] = None, campo: str = "uf_candidato") -> list[str]:
    """Retorna a lista ordenada das Unidades Federativas presentes na base.

    Args:
        df: DataFrame opcional. Se omitido, carrega a base padrão via cache.
        campo: Coluna de UF a consultar ('uf_candidato' ou 'sigla_uf_doador').

    Returns:
        list[str]: Lista de siglas de UF ordenadas alfabeticamente.
    """
    if df is None:
        df = carregar_dados()

    coluna_uf = None
    candidatas = [campo, "uf_candidato", "sigla_uf_doador", "uf_doador", "sigla_uf"]
    for c in candidatas:
        if c in df.columns:
            coluna_uf = c
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
    ufs_unicas = [uf for uf in ufs.unique() if uf and uf not in ["NAN", "NONE", "N/A", "BR"]]
    return sorted(ufs_unicas)


def listar_tipos_receita(df: Optional[pd.DataFrame] = None) -> list[str]:
    """Retorna os tipos de receita mapeados (Dinheiro Público, Privado, Aliados).

    Args:
        df: DataFrame opcional. Se omitido, carrega a base padrão via cache.

    Returns:
        list[str]: Lista ordenada de categorias de receita.
    """
    if df is None:
        df = carregar_dados()

    if "tipo_receita" not in df.columns or df["tipo_receita"].empty:
        return ["Dinheiro Público", "Financiamento Privado", "Repasse entre Aliados"]

    tipos = (
        df["tipo_receita"]
        .dropna()
        .astype(str)
        .str.strip()
    )
    tipos_unicos = [t for t in tipos.unique() if t]
    return sorted(tipos_unicos)
