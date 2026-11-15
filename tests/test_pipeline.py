"""Testes unitários e de integração para a plataforma PACD (DuckDB, Parquet, API e métricas)."""

from __future__ import annotations

import glob
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.main import (
    get_analise_geografica,
    get_custo_do_voto,
    get_global_metrics,
    get_metadata_filtros,
    get_origem_autofinanciamento,
    get_teia_empresarial,
    get_visao_geral,
    health_check,
)
from src.data_loader import (
    DEFAULT_PARQUET_PATH,
    carregar_dados,
    garantir_parquet_local,
    listar_anos,
    listar_cargos,
    listar_partidos,
    listar_ufs,
    obter_dimensao_candidatos,
    parquet_integridade_valida,
)
from src.metrics import (
    analise_autofinanciamento,
    analise_origem_recursos,
    calcular_custo_voto,
    calcular_sucesso_decil,
    correlacao_sucesso_financeiro,
)

_DF_CACHE: pd.DataFrame | None = None


def _obter_df_base() -> pd.DataFrame:
    """Carrega a base consolidada uma única vez para agilizar os testes."""
    global _DF_CACHE
    if _DF_CACHE is None:
        _DF_CACHE = carregar_dados()
    return _DF_CACHE


class TestIntegridadeParquetDrive(unittest.TestCase):
    """Testes para detecção de ponteiro LFS / arquivo corrompido e garantia local do Parquet."""

    def test_rejeita_arquivo_inexistente(self) -> None:
        caminho_fake = PROJECT_ROOT / "data/processed/__inexistente__.parquet"
        self.assertFalse(parquet_integridade_valida(caminho_fake))

    def test_rejeita_ponteiro_git_lfs(self) -> None:
        ponteiro_lfs = (
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:4f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a\n"
            "size 235485013\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            arquivo_lfs = Path(tmpdir) / "base_consolidada_eleicoes.parquet"
            arquivo_lfs.write_text(ponteiro_lfs, encoding="utf-8")
            self.assertLess(arquivo_lfs.stat().st_size, 1024)
            self.assertFalse(
                parquet_integridade_valida(arquivo_lfs),
                "Ponteiros de texto do Git LFS devem ser rejeitados pela checagem PAR1.",
            )

    def test_aceita_parquet_real_e_retorna_imediato(self) -> None:
        self.assertTrue(
            parquet_integridade_valida(DEFAULT_PARQUET_PATH),
            "O arquivo base_consolidada_eleicoes.parquet local deve conter magic bytes PAR1 válidos.",
        )
        caminho_retornado = garantir_parquet_local(DEFAULT_PARQUET_PATH)
        self.assertEqual(caminho_retornado, DEFAULT_PARQUET_PATH)


class TestDataLoader(unittest.TestCase):
    """Testes para o módulo de carregamento de dados e seletores."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.df = _obter_df_base()

    def test_carregar_dados_parquet(self) -> None:
        self.assertIsInstance(self.df, pd.DataFrame)
        self.assertFalse(self.df.empty)
        for col in [
            "ano",
            "sequencial_candidato",
            "cpf_candidato",
            "cpf_cnpj_doador",
            "valor_receita",
            "is_empresario",
            "is_eleito",
            "uf_empresa",
        ]:
            self.assertIn(col, self.df.columns)

    def test_seletores(self) -> None:
        anos = listar_anos(self.df)
        self.assertEqual(anos, [2018, 2020, 2022, 2024])

        cargos = listar_cargos(self.df)
        self.assertTrue(any(c.upper() == "PREFEITO" for c in cargos))
        self.assertEqual(cargos, sorted(cargos))

        partidos = listar_partidos(self.df)
        self.assertTrue(len(partidos) > 0)
        self.assertEqual(partidos, sorted(partidos))

        ufs = listar_ufs(self.df)
        self.assertIn("PB", ufs)
        self.assertNotIn("BR", ufs)
        self.assertEqual(ufs, sorted(ufs))


class TestDataAuditorCriteria(unittest.TestCase):
    """Testes de integridade cadastral e prevenção de duplicação de votos."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.df = _obter_df_base()

    def test_criterio_1_zeros_a_esquerda_preservados(self) -> None:
        for col in ["cpf_candidato", "cpf_cnpj_doador", "cnpj_basico"]:
            self.assertIn(col, self.df.columns)
            self.assertTrue(
                isinstance(self.df[col].dtype, pd.StringDtype) or self.df[col].dtype == object,
                f"Coluna {col} deve ser tratada como tipo textual",
            )
            amostra_zeros = self.df[self.df[col].astype(str).str.startswith("0")][col].dropna()
            if not amostra_zeros.empty:
                self.assertTrue(str(amostra_zeros.iloc[0]).startswith("0"))

    def test_criterio_2_nulos_cnpj_basico_sem_string_nan(self) -> None:
        self.assertFalse((self.df["cnpj_basico"] == "nan").any())
        self.assertFalse((self.df["cnpj_basico"] == "None").any())

    def test_criterio_3_prevencao_duplicacao_votos(self) -> None:
        dados_multiplas_doacoes = pd.DataFrame({
            "cpf_candidato": ["999", "999", "999"],
            "nome_candidato": ["Candidato Multi", "Candidato Multi", "Candidato Multi"],
            "cargo": ["vereador", "vereador", "vereador"],
            "sigla_partido": ["P1", "P1", "P1"],
            "situacao": ["deferido", "deferido", "deferido"],
            "total_votos": [100, 100, 95],
            "valor_receita": [1000.0, 2000.0, 3000.0],
        })

        custo = calcular_custo_voto(dados_multiplas_doacoes)
        self.assertEqual(len(custo), 1)
        self.assertEqual(custo["total_votos"].iloc[0], 100)
        self.assertEqual(custo["total_receita"].iloc[0], 6000.0)
        self.assertAlmostEqual(custo["custo_voto"].iloc[0], 60.0)

        dim_cand = obter_dimensao_candidatos(dados_multiplas_doacoes)
        self.assertEqual(len(dim_cand), 1)
        self.assertEqual(dim_cand["total_votos"].iloc[0], 100)


class TestMetrics(unittest.TestCase):
    """Testes para o módulo de cálculos métricos e conformidade visual."""

    def test_calcular_custo_voto_e_divisao_segura(self) -> None:
        dados = pd.DataFrame({
            "cpf_candidato": ["111", "111", "222", "333"],
            "nome_candidato": ["Cand 1", "Cand 1", "Cand 2", "Cand 3"],
            "cargo": ["prefeito", "prefeito", "vereador", "vereador"],
            "sigla_partido": ["P1", "P1", "P2", "P3"],
            "situacao": ["eleito", "eleito", "deferido", "indeferido"],
            "total_votos": [100, 100, 0, None],
            "valor_receita": [500.0, 500.0, 2000.0, 1000.0],
        })
        resultado = calcular_custo_voto(dados)

        cand1 = resultado[resultado["cpf_candidato"] == "111"].iloc[0]
        self.assertEqual(cand1["total_receita"], 1000.0)
        self.assertAlmostEqual(cand1["custo_voto"], 10.0)

        cand2 = resultado[resultado["cpf_candidato"] == "222"].iloc[0]
        self.assertEqual(cand2["custo_voto"], 0.0)

        cand3 = resultado[resultado["cpf_candidato"] == "333"].iloc[0]
        self.assertEqual(cand3["custo_voto"], 0.0)

    def test_calcular_sucesso_decil(self) -> None:
        dados = pd.DataFrame({
            "cpf_candidato": [f"C{i}" for i in range(10)],
            "valor_receita": [100.0 * (i + 1) for i in range(10)],
            "is_eleito": [False] * 8 + [True, True],
        })
        res = calcular_sucesso_decil(dados)
        self.assertAlmostEqual(res["taxa_top10"], 100.0)
        self.assertAlmostEqual(res["taxa_bottom50"], 0.0)
        self.assertAlmostEqual(res["diferenca_sucesso"], 100.0)

    def test_origem_autofinanciamento_e_correlacao(self) -> None:
        df_exemplo = pd.DataFrame({
            "tipo_receita": ["Dinheiro Público", "Financiamento Privado", "Dinheiro Público"],
            "valor_receita": [1000.0, 500.0, 3000.0],
            "autofinanciamento": [0, 1, 0],
            "situacao": ["Não Eleito", "Eleito", "Eleito"],
            "is_eleito": [False, True, True],
            "cpf_candidato": ["111", "222", "333"],
            "nome_candidato": ["A", "B", "C"],
            "uf_candidato": ["SP", "RJ", "SP"],
            "cargo": ["PREFEITO", "PREFEITO", "PREFEITO"],
            "sigla_partido": ["P1", "P2", "P1"],
            "total_votos": [100, 200, 300],
        })

        res_origem = analise_origem_recursos(df_exemplo)
        self.assertEqual(len(res_origem), 2)
        self.assertAlmostEqual(res_origem["percentual"].sum(), 100.0)

        res_auto = analise_autofinanciamento(df_exemplo)
        self.assertAlmostEqual(res_auto["volume_autofinanciamento"], 500.0)
        self.assertAlmostEqual(res_auto["volume_terceiros"], 4000.0)

        corr_log = correlacao_sucesso_financeiro(df_exemplo, usar_log=True)
        self.assertIsInstance(corr_log, float)
        self.assertFalse(np.isnan(corr_log))

    def test_garantia_sem_graficos_circulares(self) -> None:
        arquivos = [
            p
            for p in (
                glob.glob(str(PROJECT_ROOT / "src/*.py"))
                + glob.glob(str(PROJECT_ROOT / "api/*.py"))
                + [str(PROJECT_ROOT / "frontend/index.html")]
            )
            if Path(p).exists()
        ]
        for arq in arquivos:
            conteudo = Path(arq).read_text(encoding="utf-8")
            self.assertNotIn("px.pie", conteudo, f"Encontrado px.pie em {arq}")
            self.assertNotIn("go.Pie", conteudo, f"Encontrado go.Pie em {arq}")
            self.assertNotIn("hole=", conteudo, f"Encontrado hole= em {arq}")


class TestApiEndpoints(unittest.TestCase):
    """Testes de integração direta nos endpoints FastAPI + DuckDB."""

    def test_health_e_filtros(self) -> None:
        status = health_check()
        self.assertEqual(status.get("status"), "ok")

        filtros = get_metadata_filtros()
        self.assertEqual(filtros["anos"], [2018, 2020, 2022, 2024])
        self.assertIn("PRESIDENTE", filtros["cargos_por_ano"][2022])
        self.assertIn("PREFEITO", filtros["cargos_por_ano"][2024])
        self.assertEqual(len(filtros["ufs"]), 27)

    def test_global_metrics(self) -> None:
        res_todos = get_global_metrics(apenas_privado=False, modo_recurso="todos")
        self.assertEqual(res_todos["kpis"]["transacoes_registradas"], 5310738)
        self.assertGreater(res_todos["kpis"]["volume_financeiro_ativo"], 20_000_000_000.0)

        res_elite = get_global_metrics(apenas_privado=False, modo_recurso="elite")
        self.assertLess(
            res_elite["kpis"]["volume_financeiro_ativo"],
            res_todos["kpis"]["volume_financeiro_ativo"],
        )

    def test_visao_geral_e_modos_grafico_partidos(self) -> None:
        vg_geral = get_visao_geral(
            ano=2022, cargo="DEPUTADO FEDERAL", uf=None, partido=None,
            municipio=None, apenas_privado=False, modo_recurso="todos",
        )
        self.assertEqual(vg_geral["modo_grafico_partidos"], "partidos")
        self.assertGreater(len(vg_geral["top_10_partidos"]), 0)

        vg_estado = get_visao_geral(
            ano=2022, cargo="SENADOR", uf=None, partido="PL",
            municipio=None, apenas_privado=False, modo_recurso="todos",
        )
        self.assertEqual(vg_estado["modo_grafico_partidos"], "ufs_do_partido_cargo")
        self.assertTrue(vg_estado["is_partido_unico"])

        vg_oculto = get_visao_geral(
            ano=2022, cargo="SENADOR", uf="PB", partido="PL",
            municipio=None, apenas_privado=False, modo_recurso="todos",
        )
        self.assertEqual(vg_oculto["modo_grafico_partidos"], "oculto")

    def test_demais_abas_analiticas(self) -> None:
        geo = get_analise_geografica(
            ano=2022, cargo="PRESIDENTE", uf=None, partido=None,
            municipio=None, apenas_privado=False, modo_recurso="privado",
        )
        self.assertIn("panorama_uf", geo)
        self.assertIn("rotas_influencia", geo)

        custo = get_custo_do_voto(
            ano=2022, cargo="DEPUTADO FEDERAL", uf="SP", partido=None,
            apenas_privado=False, modo_recurso="privado",
        )
        self.assertIn("piso_viabilidade", custo)
        self.assertIn("pontos", custo)
        self.assertGreater(custo["resumo"]["total_candidatos"], 0)

        teia = get_teia_empresarial(
            ano=2022, cargo="SENADOR", uf=None, partido=None,
            municipio=None, apenas_privado=False, modo_recurso="elite",
        )
        self.assertIn("kpis", teia)
        self.assertIn("top_setores", teia)
        self.assertIn("top_empresas", teia)
        self.assertIn("maiores_socios", teia)

        origem = get_origem_autofinanciamento(
            ano=2022, cargo="SENADOR", uf=None, partido=None,
            municipio=None, apenas_privado=False, modo_recurso="todos",
        )
        self.assertIn("kpis", origem)
        self.assertIn("evolucao_historica", origem)


if __name__ == "__main__":
    unittest.main()
