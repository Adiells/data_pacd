"""Script CLI para download automatizado e concorrente dos CSVs dos 27 estados.

Baixa os arquivos de doações eleitorais estaduais (AC a TO) da pasta oficial do Google Drive
para a pasta local data/raw/estados/ utilizando multi-threading.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys
from pathlib import Path
from typing import Dict

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Mapeamento oficial dos 27 estados para seus respectivos IDs no Google Drive
STATE_DRIVE_IDS: Dict[str, str] = {
    "AC": "1oSotNkHUzo-oEdg3NrycEC7ZmAfMa_Xb",
    "AL": "1hD0ZjiT2P-00cYvm5ZLGQrNEWacOVZBz",
    "AM": "1aTvf68pJKwVh76jFKCC6t18z3Y-BX1qo",
    "AP": "1a10aAykghPdtCIbt2WDs2-7nMFcJ0jkr",
    "BA": "16QHvt0Ow3E4jHvwWYttZpM6TRjJVV3wy",
    "CE": "1A_6xs6S-mY6f2wguqoo0LynioUXy7dCu",
    "DF": "1iHKrKZYJQja80WkQcLsrK_jSRR-dwBxJ",
    "ES": "1_PKaErQIDIt_pVKuJwBm01_9erPKKIbn",
    "GO": "1nq8IBErQfrbhhEefkZNgwwJKL2GiBtRA",
    "MA": "1XVR76z0NxwIrbOtrUW-jqlVypowYwbop",
    "MG": "1G077XvVLoWhxek54bSeVpSEJo8eXD-Sg",
    "MS": "1GVX-LcppQ_oxppsQPpkuCajaK3KYDJGH",
    "MT": "1Z8h-kaVO9Wrnl3bkk6e9OTPYDHqMZAVr",
    "PA": "1GV3kl_uY-6md8P4l6nxjaUVujxzFw3B2",
    "PB": "1sL-0d4d-a9ntEC6vhqMDPezTE7qUAgvm",
    "PE": "1u9xRzkIbxD0khO2-kyEx4IET6qnDauhg",
    "PI": "1ZcBOTpqgLmKiWxZRiacUk9gPVMe-upWM",
    "PR": "18P2b_0ezH15hHEiY6CZXhfRrOoyNtVW6",
    "RJ": "1BSvBu_OAQfCRaEyK68N2nt3mmcuGQyv5",
    "RN": "1Xbi3S2LrgYRNxHoTpRfc-Ohy9niGyMaI",
    "RO": "1rhVFqE1xybPbCoU2WH4FPp43cbDitRCU",
    "RR": "1V1wuK96qNMH1Pr7U61Wwd4Tk_9SO2top",
    "RS": "1VYR4EhzGnvvieCVqwOFwsiuzGkbXrnmI",
    "SC": "1xHgGU0HEiI2M036u8Ir1yS-3h2WQS0c_",
    "SE": "1QEyXTHbc67ZS4VvJlOfH4E6XU46Qb5rl",
    "SP": "1vcBqMO6Ny7u_JlbeqFjg_MFnzNYt_9z3",
    "TO": "1p6Eb7oVt3OQWcNxFNTFL9hCxns5T84Ip",
}

# Estrutura oficial atualizada de pastas no Google Drive
DRIVE_ROOT_FOLDER_ID = "1Zsmq6SOyHK7ZXvUFvYOiNGMZ0bmmKPLz"       # Raiz
DRIVE_RAW_FOLDER_ID = "12oRUYQRDujlOiz6yW6P_yP5ZCsi1XuNP"        # Pasta 'raw/' contendo as 27 pastas de UFs
DRIVE_DOCS_FOLDER_ID = "145he04R7oiK-8ITxbuSfbSnq9kJkMWab"       # Pasta 'docs/'
DRIVE_PROCESSED_FOLDER_ID = "1_S9S2sB8oSO1cRW8grJpQvst-_0ANt4z"  # Pasta 'processed/'

DEFAULT_OUTPUT_DIR = Path("data/raw")


def baixar_arquivo_estado(
    uf: str,
    file_id: str,
    output_dir: Path,
    force: bool = False,
    max_retries: int = 3,
    estruturar_por_estado: bool = True,
) -> Path:
    """Baixa o CSV de um estado específico, suportando a estrutura raw/{UF}/ do Drive ou plana.

    Verifica se o arquivo já existe em qualquer um dos formatos (aninhado ou plano)
    antes de realizar a requisição de download.
    """
    if estruturar_por_estado:
        destino = output_dir / uf / f"1_doacoes_empresas_{uf}.csv"
    else:
        destino = output_dir / f"1_doacoes_empresas_{uf}.csv"

    # Checa existência em todas as estruturas conhecidas
    locais_existentes = [
        destino,
        output_dir / f"1_doacoes_empresas_{uf}.csv",
        output_dir / "estados" / f"1_doacoes_empresas_{uf}.csv",
        Path("data/raw") / uf / f"1_doacoes_empresas_{uf}.csv",
        Path("data/raw/estados") / f"1_doacoes_empresas_{uf}.csv",
    ]

    for local in locais_existentes:
        if local.exists() and local.stat().st_size > 1024 and not force:
            logger.info("[%s] Arquivo já existe em %s (%d bytes). Pulando download.", uf, local, local.stat().st_size)
            return local

    destino.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    logger.info("[%s] Baixando para %s (ID: %s)...", uf, destino, file_id)

    session = requests.Session()
    for tentativa in range(1, max_retries + 1):
        try:
            response = session.get(url, stream=True, timeout=60)
            response.raise_for_status()

            for key, value in response.cookies.items():
                if key.startswith("download_warning"):
                    url_confirm = f"{url}&confirm={value}"
                    response = session.get(url_confirm, stream=True, timeout=60)
                    response.raise_for_status()
                    break

            with open(destino, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            logger.info("[%s] Download finalizado: %d bytes em %s.", uf, destino.stat().st_size, destino)
            return destino

        except Exception as exc:
            logger.warning("[%s] Tentativa %d falhou: %s", uf, tentativa, exc)
            if tentativa == max_retries:
                if destino.exists():
                    destino.unlink(missing_ok=True)
                raise


def baixar_todos_os_estados(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_workers: int = 5,
    force: bool = False,
    estruturar_por_estado: bool = True,
) -> list[Path]:
    """Orquestra o download concorrente de todos os 27 estados."""
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Verificando/baixando 27 estados em %s (estruturado por UF: %s)...",
        output_dir,
        estruturar_por_estado,
    )

    arquivos_baixados: list[Path] = []
    falhas: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futuros = {
            executor.submit(
                baixar_arquivo_estado,
                uf,
                fid,
                output_dir,
                force,
                3,
                estruturar_por_estado,
            ): uf
            for uf, fid in sorted(STATE_DRIVE_IDS.items())
        }

        for futuro in concurrent.futures.as_completed(futuros):
            uf = futuros[futuro]
            try:
                caminho = futuro.result()
                arquivos_baixados.append(caminho)
            except Exception as e:
                logger.error("[%s] Falha crítica no download: %s", uf, e)
                falhas.append(uf)

    if falhas:
        logger.error("Download finalizado com falhas nos seguintes estados: %s", falhas)
        raise RuntimeError(f"Falha ao baixar os estados: {falhas}")

    logger.info("Todos os 27 estados foram baixados com sucesso! Total: %d arquivos.", len(arquivos_baixados))
    return arquivos_baixados


def main() -> None:
    parser = argparse.ArgumentParser(description="Baixa os CSVs eleitorais dos 27 estados do Google Drive.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Diretório de destino (padrão: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help="Número de threads simultâneas para download (padrão: 5)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Força re-download de arquivos existentes",
    )
    args = parser.parse_args()

    try:
        baixar_todos_os_estados(
            output_dir=Path(args.output_dir),
            max_workers=args.max_workers,
            force=args.force,
        )
    except Exception as err:
        logger.exception("Falha na execução: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
