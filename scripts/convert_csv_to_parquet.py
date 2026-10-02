"""Módulo CLI para ingestão e conversão de dados eleitorais.

Baixa o arquivo CSV bruto de doações eleitorais do Google Drive (ou lê localmente)
e realiza o tratamento tipado e canônico antes de exportar para Parquet otimizado.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

# Configuração de logging profissional
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Constantes padrão do projeto
DEFAULT_DRIVE_ID = "1yP5wI55YPkR_VAAJC5SYwRSf2GPjFlSK"
DEFAULT_CSV_PATH = "data/raw/1_tabela_doacoes_empresas.csv"
DEFAULT_PARQUET_PATH = "data/processed/base_consolidada_eleicoes.parquet"


def baixar_arquivo_google_drive(
    file_id: str,
    destino: Path,
    chunk_size: int = 32768,
) -> Path:
    """Baixa um arquivo público do Google Drive com suporte a streaming de chunks.

    Args:
        file_id: Identificador único do arquivo no Google Drive.
        destino: Caminho local no sistema de arquivos para salvar o arquivo baixado.
        chunk_size: Tamanho do chunk em bytes para download em streaming.

    Returns:
        Path: Caminho do arquivo baixado.

    Raises:
        requests.RequestException: Se houver falha de rede ou HTTP no download.
        IOError: Se houver erro de gravação em disco.
    """
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    logger.info("Iniciando download do Google Drive (ID: %s)...", file_id)

    destino.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    try:
        response = session.get(url, stream=True, timeout=60)
        response.raise_for_status()

        # Verifica se o Google Drive retornou página de aviso de vírus para arquivos grandes
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                url = f"{url}&confirm={value}"
                response = session.get(url, stream=True, timeout=60)
                response.raise_for_status()
                break

        with open(destino, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)

        logger.info("Download concluído com sucesso: %s", destino)
        return destino

    except requests.RequestException as e:
        logger.error("Erro durante o download do Google Drive: %s", e)
        if destino.exists():
            destino.unlink(missing_ok=True)
        raise


def converter_csv_para_parquet(
    caminho_csv: str | Path = DEFAULT_CSV_PATH,
    caminho_parquet: str | Path = DEFAULT_PARQUET_PATH,
    file_id_drive: Optional[str] = DEFAULT_DRIVE_ID,
    forcar_download: bool = False,
) -> Path:
    """Lê o arquivo CSV bruto, padroniza tipagens e salva em formato Parquet comprimido.

    Garante que identificadores cadastrais (CPF, CNPJ) sejam persistidos como strings
    para manter zeros à esquerda e que os valores monetários sejam convertidos para float64.

    Args:
        caminho_csv: Caminho para o CSV de entrada (local).
        caminho_parquet: Caminho onde o arquivo Parquet gerado será salvo.
        file_id_drive: ID opcional do arquivo no Google Drive caso o CSV local não exista.
        forcar_download: Se True, baixa novamente do Google Drive mesmo se o CSV existir.

    Returns:
        Path: Caminho do arquivo Parquet gerado.

    Raises:
        FileNotFoundError: Se o CSV não existir e nenhum ID de drive for informado.
        Exception: Em caso de falha durante leitura, conversão ou escrita.
    """
    csv_path = Path(caminho_csv)
    parquet_path = Path(caminho_parquet)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Obtenção do arquivo de origem (local ou download)
    if (forcar_download or not csv_path.exists()) and file_id_drive:
        logger.info("Arquivo CSV não encontrado localmente ou download forçado.")
        baixar_arquivo_google_drive(file_id=file_id_drive, destino=csv_path)
    elif not csv_path.exists():
        raise FileNotFoundError(
            f"Arquivo CSV não encontrado em '{csv_path}' e nenhum ID de Drive fornecido."
        )

    logger.info("Lendo arquivo CSV: %s", csv_path)

    # 2. Definição explícita de Dtypes para preservar zeros à esquerda
    dtypes = {
        "ano": "int16",
        "cpf_candidato": "string",
        "nome_candidato": "string",
        "cargo": "string",
        "sigla_partido": "string",
        "situacao": "string",
        "total_votos": "int32",
        "cpf_cnpj_doador": "string",
        "nome_doador": "string",
        "sigla_uf_doador": "string",
        "cnpj_basico": "string",
    }

    try:
        df = pd.read_csv(
            csv_path,
            sep=";",
            decimal=",",
            thousands=".",
            dtype=dtypes,
            encoding="utf-8",
            low_memory=False,
        )
    except Exception as e:
        logger.error("Falha ao ler CSV com formatação brasileira: %s", e)
        raise

    # 3. Forçar tipos de string para preservação estrita de zeros à esquerda
    colunas_string = ["cpf_candidato", "cpf_cnpj_doador", "cnpj_basico"]
    for col in colunas_string:
        if col in df.columns:
            df[col] = df[col].astype("string")

    # 4. Tratamento robusto de campos monetários (preservação estrita de centavos)
    def _limpar_monetario(serie: pd.Series) -> pd.Series:
        if pd.api.types.is_numeric_dtype(serie):
            return pd.to_numeric(serie, errors="coerce").fillna(0.0).astype("float64")

        s = serie.astype(str).str.strip()
        # Se contiver vírgula, trata como padrão brasileiro (1.500,50 -> 1500.50)
        tem_virgula = s.str.contains(",", regex=False)
        s_br = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        # Se não contiver vírgula, já está em formato ponto decimal (não remove pontos!)
        s_limpo = s.where(~tem_virgula, s_br)
        return pd.to_numeric(s_limpo, errors="coerce").fillna(0.0).astype("float64")

    colunas_monetarias = ["valor_receita", "valor_recebido_como_fornecedor"]
    for col in colunas_monetarias:
        if col in df.columns:
            df[col] = _limpar_monetario(df[col])

    # 5. Higienização de campos textuais
    text_cols = [
        "nome_candidato",
        "cargo",
        "sigla_partido",
        "situacao",
        "nome_doador",
        "sigla_uf_doador",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].str.strip()

    logger.info(
        "Dataset tratado com sucesso: %s registros e %s atributos.",
        f"{len(df):,}",
        len(df.columns),
    )

    # 6. Gravação atômica em Parquet com PyArrow e Snappy (evita colisão de I/O concorrente)
    temp_parquet = parquet_path.with_suffix(f".tmp.{parquet_path.name}")
    try:
        df.to_parquet(
            temp_parquet,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )
        temp_parquet.replace(parquet_path)
        logger.info("Arquivo Parquet gravado com sucesso (atômico) em: %s", parquet_path)
    except Exception as e:
        if temp_parquet.exists():
            temp_parquet.unlink(missing_ok=True)
        logger.error("Falha ao salvar arquivo Parquet em '%s': %s", parquet_path, e)
        raise

    return parquet_path


def main() -> None:
    """Ponto de entrada CLI para execução do pipeline de conversão."""
    parser = argparse.ArgumentParser(
        description="Converte base de doações de campanha eleitoral de CSV para Parquet otimizado."
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        default=DEFAULT_CSV_PATH,
        help=f"Caminho do arquivo CSV de entrada (padrão: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--parquet-path",
        type=str,
        default=DEFAULT_PARQUET_PATH,
        help=f"Caminho do arquivo Parquet de saída (padrão: {DEFAULT_PARQUET_PATH})",
    )
    parser.add_argument(
        "--drive-id",
        type=str,
        default=DEFAULT_DRIVE_ID,
        help=f"ID do arquivo no Google Drive (padrão: {DEFAULT_DRIVE_ID})",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Força novo download do Google Drive mesmo se o CSV existir localmente.",
    )

    args = parser.parse_args()

    try:
        converter_csv_para_parquet(
            caminho_csv=args.csv_path,
            caminho_parquet=args.parquet_path,
            file_id_drive=args.drive_id,
            forcar_download=args.force_download,
        )
    except Exception as exc:
        logger.exception("Falha crítica na execução da conversão: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
