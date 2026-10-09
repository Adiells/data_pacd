"""Módulo de métricas e análises financeiras de campanhas eleitorais.

Fornece funções analíticas de alta precisão para cálculo de custo por voto,
identificação de efeito porta giratória (doador-fornecedor), análise de fluxo
geográfico de receitas e correlação com sucesso eleitoral.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calcular_custo_voto(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa a receita total por candidato e calcula o custo por voto obtido.

    Agrupa pelos atributos canônicos do candidato ('cpf_candidato', 'nome_candidato',
    'cargo', 'sigla_partido', 'situacao', 'total_votos') e calcula:
    custo_voto = total_receita / total_votos.

    Votos zerados, negativos ou nulos são tratados com segurança, resultando em 0.0
    para evitar divisão por zero (ZeroDivisionError / infinito).

    Args:
        df: DataFrame de doações contendo informações de candidatos e receitas.

    Returns:
        pd.DataFrame: DataFrame agregado por candidato com as colunas:
                      ['cpf_candidato', 'nome_candidato', 'cargo', 'sigla_partido',
                       'situacao', 'total_votos', 'total_receita', 'custo_voto'].

    Raises:
        TypeError: Se df não for uma instância de pandas DataFrame.
        KeyError: Se alguma coluna obrigatória estiver ausente no DataFrame.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Esperado pd.DataFrame, recebido {type(df).__name__}")

    colunas_chave = [
        "cpf_candidato",
        "nome_candidato",
        "cargo",
        "sigla_partido",
        "situacao",
    ]
    if "uf_candidato" in df.columns:
        colunas_chave.append("uf_candidato")

    colunas_obrigatorias = [c for c in colunas_chave if c != "uf_candidato"] + ["total_votos"]
    colunas_saida = colunas_chave + ["total_votos", "total_receita", "custo_voto"]

    if df.empty:
        return pd.DataFrame(columns=colunas_saida)

    # Identificação da coluna de receita ('valor_receita' ou 'total_receita')
    if "valor_receita" in df.columns:
        coluna_receita = "valor_receita"
    elif "total_receita" in df.columns:
        coluna_receita = "total_receita"
    else:
        raise KeyError(
            "Coluna de receita ('valor_receita' ou 'total_receita') não encontrada no DataFrame."
        )

    # Validação da presença das colunas obrigatórias
    colunas_faltantes = [col for col in colunas_obrigatorias if col not in df.columns]
    if colunas_faltantes:
        raise KeyError(
            f"Colunas obrigatórias ausentes para cálculo do custo do voto: {colunas_faltantes}"
        )

    # Agregação da receita por candidato e resolução de divergências de votos (max)
    df_calc = df.copy()
    df_calc[coluna_receita] = pd.to_numeric(df_calc[coluna_receita], errors="coerce").fillna(0.0)
    df_calc["total_votos"] = pd.to_numeric(df_calc["total_votos"], errors="coerce").fillna(0)

    agrupado = (
        df_calc.groupby(colunas_chave, as_index=False, dropna=False)
        .agg({coluna_receita: "sum", "total_votos": "max"})
        .rename(columns={coluna_receita: "total_receita"})
    )

    # Tratamento seguro de divisão por zero ou votos nulos
    votos_numericos = pd.to_numeric(agrupado["total_votos"], errors="coerce").fillna(0.0)
    mascara_votos_validos = votos_numericos > 0

    agrupado["custo_voto"] = np.where(
        mascara_votos_validos,
        agrupado["total_receita"] / votos_numericos,
        0.0,
    ).astype("float64")

    agrupado["total_receita"] = agrupado["total_receita"].astype("float64")

    return agrupado.reset_index(drop=True)


def identificar_porta_giratoria(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra registros de porta giratória onde um doador também atuou como fornecedor.

    Filtra registros onde `valor_recebido_como_fornecedor > 0` e calcula a taxa de retorno:
    taxa_retorno = (valor_recebido_como_fornecedor / valor_receita) * 100.

    Trata casos onde `valor_receita <= 0` atribuindo taxa de retorno igual a 0.0.

    Args:
        df: DataFrame contendo dados de doações e repasses a fornecedores.

    Returns:
        pd.DataFrame: Subconjunto de registros com a coluna adicional 'taxa_retorno',
                      ordenado decrescentemente pela taxa calculada.

    Raises:
        TypeError: Se df não for uma instância de pandas DataFrame.
        KeyError: Se as colunas 'valor_recebido_como_fornecedor' ou 'valor_receita'
                  não existirem no DataFrame.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Esperado pd.DataFrame, recebido {type(df).__name__}")

    colunas_obrigatorias = ["valor_recebido_como_fornecedor", "valor_receita"]
    colunas_faltantes = [col for col in colunas_obrigatorias if col not in df.columns]
    if colunas_faltantes:
        raise KeyError(
            f"Colunas obrigatórias ausentes para análise de porta giratória: {colunas_faltantes}"
        )

    if df.empty:
        df_vazio = df.copy()
        df_vazio["taxa_retorno"] = pd.Series(dtype="float64")
        return df_vazio

    # Conversão segura para numérico antes do filtro
    fornecedor_num = pd.to_numeric(
        df["valor_recebido_como_fornecedor"], errors="coerce"
    ).fillna(0.0)
    mascara_fornecedor = fornecedor_num > 0

    df_filtrado = df[mascara_fornecedor].copy()

    if df_filtrado.empty:
        df_filtrado["taxa_retorno"] = pd.Series(dtype="float64")
        return df_filtrado

    receita_num = pd.to_numeric(
        df_filtrado["valor_receita"], errors="coerce"
    ).fillna(0.0)
    fornecedor_filtrado = pd.to_numeric(
        df_filtrado["valor_recebido_como_fornecedor"], errors="coerce"
    ).fillna(0.0)

    # Tratamento seguro para divisão por receita nula ou zerada
    mascara_receita_valida = receita_num > 0
    df_filtrado["taxa_retorno"] = np.where(
        mascara_receita_valida,
        (fornecedor_filtrado / receita_num) * 100.0,
        0.0,
    ).astype("float64")

    return df_filtrado.sort_values(by="taxa_retorno", ascending=False).reset_index(drop=True)


def analise_fluxo_geografico(df: pd.DataFrame, uf_candidato: str = "PB") -> Dict[str, Any]:
    """Calcula o montante e percentual captado de doadores da própria UF vs. outras UFs.

    Identifica se os doadores pertencem à UF do candidato ('propria_uf') ou a outras
    unidades da federação ('outras_ufs'), computando volume financeiro e representatividade.

    Args:
        df: DataFrame de doações contendo informações geográficas de doadores.
        uf_candidato: Sigla de duas letras da UF de referência do candidato (padrão: 'PB').

    Returns:
        dict: Dicionário contendo os indicadores:
              - 'uf_referencia': Sigla em maiúsculas da UF alvo.
              - 'montante_propria_uf': Valor total arrecadado de doadores do mesmo estado.
              - 'percentual_propria_uf': Participação percentual de recursos locais.
              - 'montante_outras_ufs': Valor total arrecadado de doadores de outros estados.
              - 'percentual_outras_ufs': Participação percentual de recursos externos.
              - 'total_captado': Soma consolidada de todos os recursos captados.

    Raises:
        TypeError: Se df não for pd.DataFrame ou uf_candidato não for string.
        KeyError: Se a coluna de UF ou de receita não for encontrada.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Esperado pd.DataFrame, recebido {type(df).__name__}")
    if not isinstance(uf_candidato, str):
        raise TypeError(f"Esperado str para uf_candidato, recebido {type(uf_candidato).__name__}")

    uf_alvo = uf_candidato.strip().upper()

    coluna_uf = None
    for candidata in ["sigla_uf_doador", "uf_doador", "sigla_uf"]:
        if candidata in df.columns:
            coluna_uf = candidata
            break

    if coluna_uf is None:
        raise KeyError(
            "Coluna de UF ('sigla_uf_doador', 'uf_doador' ou 'sigla_uf') não encontrada."
        )

    if "valor_receita" in df.columns:
        coluna_receita = "valor_receita"
    elif "total_receita" in df.columns:
        coluna_receita = "total_receita"
    else:
        raise KeyError(
            "Coluna de receita ('valor_receita' ou 'total_receita') não encontrada no DataFrame."
        )

    if df.empty:
        return {
            "uf_referencia": uf_alvo,
            "montante_propria_uf": 0.0,
            "percentual_propria_uf": 0.0,
            "montante_outras_ufs": 0.0,
            "percentual_outras_ufs": 0.0,
            "total_captado": 0.0,
        }

    receitas = pd.to_numeric(df[coluna_receita], errors="coerce").fillna(0.0)
    ufs_limpas = df[coluna_uf].fillna("").astype(str).str.strip().str.upper()

    mascara_propria = ufs_limpas == uf_alvo

    montante_propria = float(receitas[mascara_propria].sum())
    montante_outras = float(receitas[~mascara_propria].sum())
    total_captado = montante_propria + montante_outras

    if total_captado > 0:
        percentual_propria = (montante_propria / total_captado) * 100.0
        percentual_outras = (montante_outras / total_captado) * 100.0
    else:
        percentual_propria = 0.0
        percentual_outras = 0.0

    return {
        "uf_referencia": uf_alvo,
        "montante_propria_uf": montante_propria,
        "percentual_propria_uf": percentual_propria,
        "montante_outras_ufs": montante_outras,
        "percentual_outras_ufs": percentual_outras,
        "total_captado": total_captado,
    }


def correlacao_sucesso_financeiro(
    df: pd.DataFrame,
    metodo: str = "pearson",
    usar_log: bool = False,
) -> float:
    """Mede a correlação entre a receita arrecadada e o sucesso eleitoral.

    Codifica a situação do candidato: atribuindo 1 se 'situacao' contiver 'eleito'
    sem ser negada por 'não eleito' (ex.: 'eleito', 'eleito por qp', 'eleito por média'),
    e 0 para 'não eleito', 'indeferido', 'suplente' ou demais situações.

    Trata a forte assimetria à direita (cauda longa / lei de potência) dos recursos de campanha
    permitindo o uso de escala logarítmica (np.log1p) ou correlação de postos de Spearman.
    Em casos de variância zero ou dados insuficientes, retorna 0.0 de forma segura.

    Args:
        df: DataFrame contendo a coluna 'situacao' e coluna de receita ('total_receita'
            ou 'valor_receita').
        metodo: Método de correlação ('pearson' ou 'spearman'). Padrão: 'pearson'.
        usar_log: Se True, aplica transformação logarítmica (log1p) na receita para
                  atenuar a assimetria positiva extrema dos dados. Padrão: False.

    Returns:
        float: Coeficiente de correlação entre -1.0 e 1.0 (ou 0.0 se indefinido).

    Raises:
        TypeError: Se df não for uma instância de pandas DataFrame.
        KeyError: Se as colunas 'situacao' ou a coluna de receita não forem encontradas.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Esperado pd.DataFrame, recebido {type(df).__name__}")

    if "situacao" not in df.columns:
        raise KeyError("Coluna 'situacao' não encontrada no DataFrame.")

    if "total_receita" in df.columns:
        coluna_receita = "total_receita"
    elif "valor_receita" in df.columns:
        coluna_receita = "valor_receita"
    else:
        raise KeyError(
            "Coluna de receita ('total_receita' ou 'valor_receita') não encontrada no DataFrame."
        )

    if len(df) < 2:
        return 0.0

    # Codificação alinhada: eleito=1, não eleito/indeferido/suplente=0
    situacao_limpa = df["situacao"].fillna("").astype(str).str.lower()
    sucesso = (
        situacao_limpa.str.contains("eleito")
        & ~situacao_limpa.str.contains(r"n[aã]o[\s\-_]*eleito")
    ).astype(int)

    receitas = pd.to_numeric(df[coluna_receita], errors="coerce").fillna(0.0)

    # Tratamento para assimetria à direita extrema do capital eleitoral
    if usar_log:
        valores_receita = np.log1p(np.maximum(0.0, receitas))
    else:
        valores_receita = receitas

    # Variância zero em qualquer uma das séries impede o cálculo
    if sucesso.nunique() <= 1 or valores_receita.nunique() <= 1:
        return 0.0

    corr = valores_receita.astype("float64").corr(
        sucesso.astype("float64"), method=metodo
    )

    if pd.isna(corr) or np.isnan(corr):
        return 0.0

    return float(corr)


def analise_origem_recursos(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula a distribuição percentual e total de recursos por origem.

    Categorias: 'Dinheiro Público' (Fundo Partidário/FEFC), 'Financiamento Privado'
    e 'Repasse entre Aliados'.

    Args:
        df: DataFrame com coluna 'tipo_receita' e 'valor_receita' (ou 'total_receita').

    Returns:
        pd.DataFrame: DataFrame contendo colunas ['tipo_receita', 'total_arrecadado',
                      'total_doacoes', 'percentual'], ordenado pelo total.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Esperado pd.DataFrame, recebido {type(df).__name__}")

    coluna_receita = "valor_receita" if "valor_receita" in df.columns else "total_receita"
    if coluna_receita not in df.columns:
        raise KeyError("Coluna de receita não encontrada.")

    if df.empty or "tipo_receita" not in df.columns:
        return pd.DataFrame(columns=["tipo_receita", "total_arrecadado", "total_doacoes", "percentual"])

    df_calc = df.copy()
    df_calc[coluna_receita] = pd.to_numeric(df_calc[coluna_receita], errors="coerce").fillna(0.0)

    agrupado = (
        df_calc.groupby("tipo_receita", as_index=False)
        .agg(total_arrecadado=(coluna_receita, "sum"), total_doacoes=(coluna_receita, "count"))
    )

    total_geral = agrupado["total_arrecadado"].sum()
    agrupado["percentual"] = np.where(
        total_geral > 0,
        (agrupado["total_arrecadado"] / total_geral) * 100.0,
        0.0,
    )

    return agrupado.sort_values(by="total_arrecadado", ascending=False).reset_index(drop=True)


def analise_autofinanciamento(df: pd.DataFrame) -> Dict[str, Any]:
    """Calcula indicadores de autofinanciamento e aporte do próprio candidato.

    Regra de negócio: 'autofinanciamento' == 1 indica que o candidato aportou
    recursos próprios na campanha.

    Args:
        df: DataFrame com colunas 'autofinanciamento', 'valor_receita' e 'situacao'.

    Returns:
        dict: Indicadores consolidados de autofinanciamento.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Esperado pd.DataFrame, recebido {type(df).__name__}")

    if df.empty or "autofinanciamento" not in df.columns:
        return {
            "taxa_autofinanciamento": 0.0,
            "volume_autofinanciamento": 0.0,
            "volume_terceiros": 0.0,
            "total_operacoes_auto": 0,
            "taxa_sucesso_auto": 0.0,
            "taxa_sucesso_terceiros": 0.0,
        }

    coluna_receita = "valor_receita" if "valor_receita" in df.columns else "total_receita"
    df_calc = df.copy()
    df_calc[coluna_receita] = pd.to_numeric(df_calc[coluna_receita], errors="coerce").fillna(0.0)
    df_calc["autofinanciamento"] = pd.to_numeric(df_calc["autofinanciamento"], errors="coerce").fillna(0).astype(int)

    total_registros = len(df_calc)
    taxa_auto = float(df_calc["autofinanciamento"].mean() * 100.0) if total_registros > 0 else 0.0

    mask_auto = df_calc["autofinanciamento"] == 1
    vol_auto = float(df_calc.loc[mask_auto, coluna_receita].sum())
    vol_terceiros = float(df_calc.loc[~mask_auto, coluna_receita].sum())
    total_ops = int(mask_auto.sum())

    # Taxa de sucesso comparada
    taxa_sucesso_auto = 0.0
    taxa_sucesso_terceiros = 0.0
    if "situacao" in df_calc.columns:
        sit = df_calc["situacao"].fillna("").astype(str).str.lower()
        eleito = (sit.str.contains("eleito") & ~sit.str.contains(r"n[aã]o[\s\-_]*eleito")).astype(int)
        df_calc["eleito"] = eleito

        if mask_auto.sum() > 0:
            taxa_sucesso_auto = float(df_calc.loc[mask_auto, "eleito"].mean() * 100.0)
        if (~mask_auto).sum() > 0:
            taxa_sucesso_terceiros = float(df_calc.loc[~mask_auto, "eleito"].mean() * 100.0)

    return {
        "taxa_autofinanciamento": taxa_auto,
        "volume_autofinanciamento": vol_auto,
        "volume_terceiros": vol_terceiros,
        "total_operacoes_auto": total_ops,
        "taxa_sucesso_auto": taxa_sucesso_auto,
        "taxa_sucesso_terceiros": taxa_sucesso_terceiros,
    }


def analise_custo_voto_por_uf(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula a mediana do custo por voto agrupada por Unidade Federativa (UF).

    Args:
        df: DataFrame contendo informações de candidatos, receitas e votos.

    Returns:
        pd.DataFrame: DataFrame ordenado com ['uf_candidato', 'mediana_custo_voto',
                      'total_candidatos', 'total_votos', 'total_receita'].
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Esperado pd.DataFrame, recebido {type(df).__name__}")

    if df.empty or "uf_candidato" not in df.columns:
        return pd.DataFrame(
            columns=["uf_candidato", "mediana_custo_voto", "total_candidatos", "total_votos", "total_receita"]
        )

    cand = calcular_custo_voto(df) if "custo_voto" not in df.columns else df.copy()

    # Filtra apenas quem teve votos para cálculo fidedigno da mediana
    cand_positivos = cand[cand["custo_voto"] > 0]
    if cand_positivos.empty:
        cand_positivos = cand

    agrupado = (
        cand_positivos.groupby("uf_candidato", as_index=False)
        .agg(
            mediana_custo_voto=("custo_voto", "median"),
            total_candidatos=("cpf_candidato", "nunique"),
            total_votos=("total_votos", "sum"),
            total_receita=("total_receita", "sum") if "total_receita" in cand_positivos.columns else ("valor_receita", "sum"),
        )
    )

    return agrupado.sort_values(by="mediana_custo_voto", ascending=False).reset_index(drop=True)

