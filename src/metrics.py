"""Módulo de métricas e análises financeiras de campanhas eleitorais.

Fornece funções analíticas de alta precisão para cálculo de custo por voto,
identificação de efeito porta giratória (doador-fornecedor), análise de fluxo
geográfico de receitas e correlação com sucesso eleitoral.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Padrões Regex canônicos de higienização da malha fina (AGENTS.md & PROMPTS.md)
PADRAO_INSTITUCIONAL = r"(dire[cç][aãõo]es|dire[cç][aã]o|[oó]rg[aã]os?|comiss[aãõo]es|comiss[aã]o|comit[eê]s?|partidos?)"
PADRAO_ALIADOS = r"(elei[cç][aãõo]es|elei[cç][aã]o|campanhas?)"
REGEX_INSTITUCIONAL_ALIADOS = re.compile(
    rf"(?:{PADRAO_INSTITUCIONAL}|{PADRAO_ALIADOS})",
    re.IGNORECASE
)


def remover_acentos(texto: Any) -> str:
    """Remove diacríticos e acentos de uma string."""
    if not isinstance(texto, str):
        return str(texto) if pd.notna(texto) else ""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def filtrar_entidades_particulares(df: pd.DataFrame, coluna_nome: str = "nome_doador") -> pd.DataFrame:
    """Filtra e exclui repasses partidários/institucionais e de campanha/aliados via regex case-insensitive e sem acentos."""
    if df.empty or coluna_nome not in df.columns:
        return df

    nomes_sem_acento = df[coluna_nome].fillna("").astype(str).apply(remover_acentos)
    # Padrão sem acentos para garantir correspondência exata
    padrao_unaccented = re.compile(
        r"(?:direcoes|direcao|orgaos?|comissoes|comissao|comites?|partidos?|eleicoes|eleicao|campanhas?)",
        re.IGNORECASE,
    )
    mascara_remover = nomes_sem_acento.str.contains(padrao_unaccented, regex=True)
    return df[~mascara_remover].copy()


def atribuir_status_eleitoral(df_candidatos: pd.DataFrame) -> pd.DataFrame:
    """Normaliza e atribui a situação eleitoral (1 = eleito, 0 = não eleito/suplente).

    Suporta marcação textual de 'ELEITO', 'ELEITO POR QP', 'ELEITO POR MÉDIA'.
    Caso o dataset traga apenas situação cadastral ('deferido'), infere o resultado
    pelo ranking de votos e bancadas institucionais do pleito.
    """
    if df_candidatos.empty:
        df_res = df_candidatos.copy()
        df_res["eleito"] = pd.Series(dtype="int64")
        return df_res

    df_res = df_candidatos.copy()
    sit = df_res["situacao"].fillna("").astype(str).str.upper() if "situacao" in df_res.columns else pd.Series([""] * len(df_res), index=df_res.index)
    
    tem_eleito_textual = sit.str.contains(r"\bELEITO\b|ELEITO POR QP|ELEITO POR M[ÉE]DIA|2[º°] TURNO", regex=True).any()
    
    if tem_eleito_textual:
        df_res["eleito"] = (
            sit.str.contains(r"\bELEITO\b|ELEITO POR QP|ELEITO POR M[ÉE]DIA|2[º°] TURNO", regex=True)
            & ~sit.str.contains(r"N[ÃA]O\s*ELEITO", regex=True)
        ).astype(int)
        return df_res

    # Fallback institucional por ranking de votos quando o dataset contém apenas situação cadastral
    df_res["eleito"] = 0
    if "total_votos" not in df_res.columns:
        return df_res

    vagas_fed = {
        "SP": 70, "MG": 53, "RJ": 46, "BA": 39, "RS": 31, "PR": 30, "PE": 25, "CE": 22,
        "MA": 18, "GO": 17, "PA": 17, "PB": 12, "ES": 10, "PI": 10, "AL": 9, "AC": 8,
        "AM": 8, "AP": 8, "DF": 8, "MS": 8, "MT": 8, "RN": 8, "RO": 8, "RR": 8, "SC": 16,
        "SE": 8, "TO": 8,
    }

    campos_agrup = [c for c in ["ano", "cargo", "uf_candidato"] if c in df_res.columns]
    if not campos_agrup:
        # Se não houver campos de agrupamento, toma os top 15% mais votados
        n = len(df_res)
        v = max(1, int(n * 0.15))
        top_idx = df_res.sort_values(by="total_votos", ascending=False).head(v).index
        df_res.loc[top_idx, "eleito"] = 1
        return df_res

    for _, grp in df_res.groupby(campos_agrup):
        cargo = str(grp["cargo"].iloc[0]).lower() if "cargo" in grp.columns else ""
        ano = int(grp["ano"].iloc[0]) if "ano" in grp.columns else 2022
        uf = str(grp["uf_candidato"].iloc[0]).upper() if "uf_candidato" in grp.columns else "PB"
        n = len(grp)

        if "governador" in cargo or "presidente" in cargo:
            vagas = 1
        elif "prefeito" in cargo:
            # Em média 40-45% de eleitos se agrupado por estado, ou 1 por município
            if "municipio_candidato" in grp.columns and grp["municipio_candidato"].nunique() > 1:
                vagas = max(1, grp["municipio_candidato"].nunique())
            else:
                vagas = max(1, int(np.ceil(n * 0.44)))
        elif "senador" in cargo:
            vagas = 2 if ano == 2018 else 1
        elif "deputado federal" in cargo:
            vagas = vagas_fed.get(uf, 12)
        elif "deputado estadual" in cargo or "deputado distrital" in cargo:
            vagas = min(n, vagas_fed.get(uf, 12) * 3)
        elif "vereador" in cargo:
            vagas = max(1, int(n * 0.12))
        else:
            vagas = max(1, int(n * 0.12))

        top_idx = grp.sort_values(by="total_votos", ascending=False).head(vagas).index
        df_res.loc[top_idx, "eleito"] = 1

    return df_res



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

    # Higienização via Regex: Remove institucional (partido/órgão) e repasse de aliados (eleição/campanha)
    df_limpo = filtrar_entidades_particulares(df, "nome_doador")
    if "nome_fornecedor" in df_limpo.columns:
        df_limpo = filtrar_entidades_particulares(df_limpo, "nome_fornecedor")

    # Conversão segura para numérico antes do filtro
    fornecedor_num = pd.to_numeric(
        df_limpo["valor_recebido_como_fornecedor"], errors="coerce"
    ).fillna(0.0)
    mascara_fornecedor = fornecedor_num > 0

    df_filtrado = df_limpo[mascara_fornecedor].copy()

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

    # Taxa de sucesso comparada (normalizada via atribuir_status_eleitoral)
    taxa_sucesso_auto = 0.0
    taxa_sucesso_terceiros = 0.0
    df_calc = atribuir_status_eleitoral(df_calc)
    if "eleito" in df_calc.columns:
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


def calcular_sucesso_decil(df: pd.DataFrame) -> Dict[str, float]:
    """Calcula a taxa de sucesso eleitoral do decil mais financiado (Top 10%) vs metade menos financiada (Bottom 50%).

    Retorna:
        dict: {'taxa_top10': float, 'taxa_bottom50': float, 'diferenca_sucesso': float}
    """
    if df.empty:
        return {"taxa_top10": 0.0, "taxa_bottom50": 0.0, "diferenca_sucesso": 0.0}

    coluna_receita = "total_receita" if "total_receita" in df.columns else ("valor_receita" if "valor_receita" in df.columns else None)
    if not coluna_receita:
        return {"taxa_top10": 0.0, "taxa_bottom50": 0.0, "diferenca_sucesso": 0.0}

    # Agrupa por candidato
    agrup_cols = [c for c in ["cpf_candidato", "nome_candidato", "cargo", "sigla_partido", "situacao", "uf_candidato", "ano"] if c in df.columns]
    if "total_votos" in df.columns:
        agrup_cols.append("total_votos")

    cand = (
        df.groupby(agrup_cols, as_index=False)[coluna_receita]
        .sum()
        .rename(columns={coluna_receita: "total_receita"})
        .sort_values(by="total_receita", ascending=False)
        .reset_index(drop=True)
    )

    cand_class = atribuir_status_eleitoral(cand)
    n = len(cand_class)
    if n == 0 or "eleito" not in cand_class.columns:
        return {"taxa_top10": 0.0, "taxa_bottom50": 0.0, "diferenca_sucesso": 0.0}

    tamanho_top10 = max(1, int(np.ceil(n * 0.10)))
    tamanho_bottom50 = max(1, int(np.floor(n * 0.50)))

    taxa_top10 = float(cand_class.iloc[:tamanho_top10]["eleito"].mean() * 100.0)
    taxa_bottom50 = float(cand_class.iloc[-tamanho_bottom50:]["eleito"].mean() * 100.0)
    diferenca = taxa_top10 - taxa_bottom50

    return {
        "taxa_top10": taxa_top10,
        "taxa_bottom50": taxa_bottom50,
        "diferenca_sucesso": diferenca,
    }

