"""Módulo CLI para ingestão e conversão de dados eleitorais nacionais.

Consolida os arquivos CSV dos 27 estados (AC a TO) ou um arquivo CSV individual,
aplicando rigorosamente as tipagens e regras de negócio de 'Resumo_Colunas_Tabela_FInal.pdf'
e gerando um arquivo Parquet consolidado e otimizado via DuckDB/PyArrow.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from typing import Optional

import duckdb

# Garante raiz do projeto no path de execução
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.download_all_states import baixar_todos_os_estados


# Configuração de logging profissional
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Caminhos padrão do projeto
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_ESTADOS_DIR = Path("data/raw/estados")
DEFAULT_CSV_PATH = Path("data/raw/1_tabela_doacoes_empresas.csv")
DEFAULT_PARQUET_PATH = Path("data/processed/base_consolidada_eleicoes.parquet")


def localizar_csvs_estaduais(origem_dir: Optional[Path | str] = None) -> list[Path]:
    """Localiza todos os CSVs dos 27 estados em estrutura aninhada (raw/{UF}/) ou plana (estados/).

    Args:
        origem_dir: Diretório opcional base de busca.

    Returns:
        list[Path]: Lista de arquivos CSV estaduais localizados e desduplicados.
    """
    pastas_busca: list[Path] = []
    if origem_dir:
        p_origem = Path(origem_dir)
        if p_origem.exists():
            pastas_busca.append(p_origem)

    for padrao in [DEFAULT_RAW_DIR, DEFAULT_ESTADOS_DIR]:
        if padrao.exists() and padrao not in pastas_busca:
            pastas_busca.append(padrao)

    candidatos: list[Path] = []
    for pasta in pastas_busca:
        # Busca recursiva cobrindo tanto subpastas (raw/{UF}/) quanto diretório plano
        candidatos.extend(list(pasta.rglob("1_doacoes_empresas_*.csv")))

    # Desduplica por nome de arquivo (ex: 1_doacoes_empresas_SP.csv)
    vistos = set()
    unicos: list[Path] = []
    for arq in sorted(candidatos, key=lambda x: x.name):
        if arq.name not in vistos and arq.stat().st_size > 0:
            vistos.add(arq.name)
            unicos.append(arq)

    return unicos


def converter_dados_para_parquet(
    origem_dir: Optional[Path | str] = None,
    arquivo_csv: Optional[Path | str] = None,
    destino_parquet: Path | str = DEFAULT_PARQUET_PATH,
    forcar_download: bool = False,
    caminho_csv: Optional[Path | str] = None,
    caminho_parquet: Optional[Path | str] = None,
    file_id_drive: Optional[str] = None,
) -> Path:
    """Consolida e trata dados eleitorais gravando em Parquet atômico de alta performance.

    Regras de Negócio aplicadas (conforme Resumo_Colunas_Tabela_FInal.pdf):
      - ano: string (evita cálculos indevidos em describe)
      - cpf_candidato: string com zfill(11)
      - nome_candidato, cargo, sigla_partido: maiúsculas e trim
      - situacao: minúsculas e trim (máscaras booleanas seguras)
      - total_votos: numérico int64 (default 0)
      - uf_candidato: sigla em maiúsculas (2 letras)
      - municipio_candidato: string preservando NaNs estruturais (2018 e 2022 não possuem)
      - cpf_cnpj_doador: string preservando zeros à esquerda
      - nome_doador: trim
      - valor_receita: float64
      - valor_recebido_como_fornecedor: float64 preservando NaNs de doadores puros
      - cnpj_basico: 8 dígitos limpos (sem .0 ou ,0)
      - autofinanciamento: int8 (1 se CPFs iguais, 0 se terceiros)
      - tipo_receita:
          * Contém 'DIREÇÃO' ou 'ÓRGÃO' -> 'Dinheiro Público'
          * Contém 'ELEIÇÃO' -> 'Repasse entre Aliados'
          * Demais -> 'Financiamento Privado'
    """
    if caminho_csv is not None:
        arquivo_csv = caminho_csv
    if caminho_parquet is not None:
        destino_parquet = caminho_parquet

    if origem_dir is not None:
        p_origem = Path(origem_dir)
        if p_origem.is_file() or str(p_origem).endswith(".csv"):
            arquivo_csv = p_origem
            origem_dir = None

    destino_parquet = Path(destino_parquet)
    destino_parquet.parent.mkdir(parents=True, exist_ok=True)

    # Identifica fonte de dados
    if arquivo_csv and Path(arquivo_csv).exists():
        fonte_sql = f"'{Path(arquivo_csv).resolve()}'"
        logger.info("Processando arquivo CSV único: %s", arquivo_csv)
    else:
        csvs_encontrados = localizar_csvs_estaduais(origem_dir)

        if forcar_download or len(csvs_encontrados) < 27:
            logger.info(
                "Base completa de 27 estados ausente ou incompleta (%d encontrados). Iniciando download...",
                len(csvs_encontrados),
            )
            dir_download = Path(origem_dir) if origem_dir else DEFAULT_RAW_DIR
            baixar_todos_os_estados(output_dir=dir_download, force=forcar_download)
            csvs_encontrados = localizar_csvs_estaduais(origem_dir)

        if not csvs_encontrados:
            if DEFAULT_CSV_PATH.exists():
                fonte_sql = f"'{DEFAULT_CSV_PATH.resolve()}'"
                logger.info("Utilizando arquivo CSV legado de fallback: %s", DEFAULT_CSV_PATH)
            else:
                raise FileNotFoundError(
                    f"Nenhum arquivo CSV encontrado em '{origem_dir}' nem em '{DEFAULT_RAW_DIR}'."
                )
        else:
            fonte_sql = str([str(p.resolve()) for p in csvs_encontrados])
            logger.info(
                "Consolidando %d arquivos estaduais (suporte a estrutura Drive raw/{UF}/ e estados/).",
                len(csvs_encontrados),
            )

    # Execução atômica via DuckDB
    temp_parquet = destino_parquet.with_suffix(f".tmp.{destino_parquet.name}")
    con = duckdb.connect()

    # Mapeamento dinâmico de colunas presentes para evitar Binder Errors em bases legadas
    colunas_existentes = set(
        con.execute(
            f"DESCRIBE SELECT * FROM read_csv({fonte_sql}, delim=';', header=True, all_varchar=True, ignore_errors=True) LIMIT 0"
        )
        .df()["column_name"]
        .str.lower()
        .tolist()
    )

    col_uf = "UPPER(TRIM(uf_candidato)) AS uf_candidato" if "uf_candidato" in colunas_existentes else "COALESCE(NULLIF(UPPER(TRIM(sigla_uf_doador)), 'N/A'), 'BR') AS uf_candidato"
    col_mun = "NULLIF(NULLIF(UPPER(TRIM(municipio_candidato)), 'N/A'), '') AS municipio_candidato" if "municipio_candidato" in colunas_existentes else "NULL::VARCHAR AS municipio_candidato"
    col_cnpj = "NULLIF(LPAD(REGEXP_REPLACE(SPLIT_PART(TRIM(cnpj_basico), ',', 1), '[^0-9]', '', 'g'), 8, '0'), '') AS cnpj_basico" if "cnpj_basico" in colunas_existentes else "NULL::VARCHAR AS cnpj_basico"
    col_forn = "TRY_CAST(REPLACE(REPLACE(TRIM(valor_recebido_como_fornecedor), '.', ''), ',', '.') AS DOUBLE) AS valor_recebido_como_fornecedor" if "valor_recebido_como_fornecedor" in colunas_existentes else "NULL::DOUBLE AS valor_recebido_como_fornecedor"
    col_id_mun_doador = "NULLIF(NULLIF(TRIM(id_municipio_tse_doador), 'N/A'), '') AS id_municipio_tse_doador" if "id_municipio_tse_doador" in colunas_existentes else "NULL::VARCHAR AS id_municipio_tse_doador"
    col_uf_forn = "NULLIF(NULLIF(UPPER(TRIM(sigla_uf_fornecedor)), 'N/A'), '') AS sigla_uf_fornecedor" if "sigla_uf_fornecedor" in colunas_existentes else "NULL::VARCHAR AS sigla_uf_fornecedor"
    col_id_mun_forn = "NULLIF(NULLIF(TRIM(id_municipio_tse_fornecedor), 'N/A'), '') AS id_municipio_tse_fornecedor" if "id_municipio_tse_fornecedor" in colunas_existentes else "NULL::VARCHAR AS id_municipio_tse_fornecedor"
    col_auto = (
        "CASE WHEN TRIM(cpf_candidato) = TRIM(cpf_cnpj_doador) OR TRIM(autofinanciamento) = '1' THEN 1::TINYINT ELSE 0::TINYINT END AS autofinanciamento"
        if "autofinanciamento" in colunas_existentes
        else "CASE WHEN TRIM(cpf_candidato) = TRIM(cpf_cnpj_doador) THEN 1::TINYINT ELSE 0::TINYINT END AS autofinanciamento"
    )

    transform_sql = f"""
    COPY (
        WITH raw_data AS (
            SELECT 
                TRIM(ano)::VARCHAR AS ano,
                LPAD(REGEXP_REPLACE(TRIM(cpf_candidato), '[^0-9]', '', 'g'), 11, '0') AS cpf_candidato,
                UPPER(TRIM(nome_candidato)) AS nome_candidato,
                UPPER(TRIM(cargo)) AS cargo,
                UPPER(TRIM(sigla_partido)) AS sigla_partido,
                LOWER(TRIM(situacao)) AS situacao,
                COALESCE(TRY_CAST(REGEXP_REPLACE(TRIM(total_votos), '[^0-9]', '', 'g') AS BIGINT), 0) AS total_votos,
                {col_uf},
                {col_mun},
                TRIM(cpf_cnpj_doador) AS cpf_cnpj_doador,
                TRIM(nome_doador) AS nome_doador,
                NULLIF(NULLIF(UPPER(TRIM(sigla_uf_doador)), 'N/A'), '') AS sigla_uf_doador,
                {col_id_mun_doador},
                {col_uf_forn},
                {col_id_mun_forn},
                {col_forn},
                COALESCE(TRY_CAST(REPLACE(REPLACE(TRIM(valor_receita), '.', ''), ',', '.') AS DOUBLE), 0.0) AS valor_receita,
                {col_cnpj},
                {col_auto},
                CASE
                    WHEN UPPER(nome_doador) LIKE '%DIREÇÃO%' 
                      OR UPPER(nome_doador) LIKE '%DIRECAO%' 
                      OR UPPER(nome_doador) LIKE '%ÓRGÃO%' 
                      OR UPPER(nome_doador) LIKE '%ORGAO%' THEN 'Dinheiro Público'
                    WHEN UPPER(nome_doador) LIKE '%ELEIÇÃO%' 
                      OR UPPER(nome_doador) LIKE '%ELEICAO%' THEN 'Repasse entre Aliados'
                    ELSE 'Financiamento Privado'
                END AS tipo_receita

            FROM read_csv(
                {fonte_sql},
                delim=';',
                header=True,
                all_varchar=True,
                ignore_errors=True
            )
        )
        SELECT * FROM raw_data
    ) TO '{temp_parquet}' (FORMAT PARQUET, COMPRESSION SNAPPY);
    """

    try:
        logger.info("Executando pipeline analítico de transformação...")
        con.execute(transform_sql)
        con.close()

        # Substituição atômica no sistema de arquivos
        temp_parquet.replace(destino_parquet)
        tamanho_mb = destino_parquet.stat().st_size / (1024 * 1024)
        logger.info(
            "Base consolidada gravada com sucesso em '%s' (Tamanho: %.2f MB)",
            destino_parquet,
            tamanho_mb,
        )
        return destino_parquet

    except Exception as exc:
        if temp_parquet.exists():
            temp_parquet.unlink(missing_ok=True)
        con.close()
        logger.error("Erro fatal na consolidação Parquet: %s", exc)
        raise


# Função de retrocompatibilidade com assinatura legada
def converter_csv_para_parquet(
    caminho_csv: str | Path = DEFAULT_CSV_PATH,
    caminho_parquet: str | Path = DEFAULT_PARQUET_PATH,
    file_id_drive: Optional[str] = None,
    forcar_download: bool = False,
) -> Path:
    """Função legada para conversão individual de CSV para Parquet."""
    return converter_dados_para_parquet(
        origem_dir=None,
        arquivo_csv=caminho_csv,
        destino_parquet=caminho_parquet,
        forcar_download=forcar_download,
    )




def main() -> None:
    parser = argparse.ArgumentParser(
        description="Converte e consolida os CSVs estaduais em base Parquet nacional única."
    )
    parser.add_argument(
        "--estados-dir",
        type=str,
        default=str(DEFAULT_ESTADOS_DIR),
        help=f"Diretório com os CSVs dos 27 estados (padrão: {DEFAULT_ESTADOS_DIR})",
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default=None,
        help="Caminho opcional para processar um CSV único em vez de todos os estados.",
    )
    parser.add_argument(
        "--parquet-path",
        type=str,
        default=str(DEFAULT_PARQUET_PATH),
        help=f"Caminho do arquivo Parquet de saída (padrão: {DEFAULT_PARQUET_PATH})",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Força re-download dos estados do Google Drive se necessário.",
    )
    args = parser.parse_args()

    try:
        converter_dados_para_parquet(
            origem_dir=Path(args.estados_dir) if args.estados_dir else None,
            arquivo_csv=Path(args.csv_path) if args.csv_path else None,
            destino_parquet=Path(args.parquet_path),
            forcar_download=args.force_download,
        )
    except Exception as err:
        logger.exception("Falha na consolidação: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
