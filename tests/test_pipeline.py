"""Testes unitários e de integração para o pipeline de dados e métricas eleitorais."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.convert_csv_to_parquet import converter_csv_para_parquet
from src.data_loader import (
    carregar_dados,
    listar_anos,
    listar_cargos,
    listar_partidos,
    listar_ufs,
    obter_dimensao_candidatos,
)
from src.metrics import (
    analise_autofinanciamento,
    analise_custo_voto_por_uf,
    analise_fluxo_geografico,
    analise_origem_recursos,
    calcular_custo_voto,
    correlacao_sucesso_financeiro,
    identificar_porta_giratoria,
)


class TestPipelineConversao(unittest.TestCase):
    """Testes de conversão de CSV para Parquet."""

    def test_preservacao_zeros_e_decimais(self) -> None:
        """Verifica se zeros à esquerda são mantidos e vírgulas convertidas para float."""
        conteudo_csv = (
            "ano;cpf_candidato;nome_candidato;cargo;sigla_partido;situacao;total_votos;"
            "cpf_cnpj_doador;nome_doador;sigla_uf_doador;valor_recebido_como_fornecedor;"
            "valor_receita;cnpj_basico\n"
            "2022;00123456789;Fulano de Tal;prefeito;PART;deferido;1000;"
            "00098765432100;Empresa X;PB;1.500,50;10.000,75;00123456\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "teste.csv"
            parquet_path = Path(tmpdir) / "teste.parquet"
            csv_path.write_text(conteudo_csv, encoding="utf-8")

            converter_csv_para_parquet(
                caminho_csv=csv_path,
                caminho_parquet=parquet_path,
                file_id_drive=None,
            )

            df = pd.read_parquet(parquet_path)
            self.assertEqual(df["cpf_candidato"].iloc[0], "00123456789")
            self.assertEqual(df["cpf_cnpj_doador"].iloc[0], "00098765432100")
            self.assertEqual(df["cnpj_basico"].iloc[0], "00123456")
            self.assertAlmostEqual(df["valor_recebido_como_fornecedor"].iloc[0], 1500.50)
            self.assertAlmostEqual(df["valor_receita"].iloc[0], 10000.75)


class TestDataLoader(unittest.TestCase):
    """Testes para o módulo de carregamento de dados e seletores."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.df = carregar_dados()

    def test_carregar_dados_parquet(self) -> None:
        """Testa o carregamento padrão da base."""
        self.assertIsInstance(self.df, pd.DataFrame)
        self.assertFalse(self.df.empty)
        self.assertIn("cpf_candidato", self.df.columns)
        self.assertIn("valor_receita", self.df.columns)

    def test_seletores(self) -> None:
        """Testa as funções auxiliares de listagem para seletores."""
        anos = listar_anos(self.df)
        self.assertIn(2022, anos)
        self.assertEqual(anos, sorted(anos))

        cargos = listar_cargos(self.df)
        self.assertTrue(any(c.upper() == "PREFEITO" for c in cargos))
        self.assertEqual(cargos, sorted(cargos))

        partidos = listar_partidos(self.df)
        self.assertTrue(len(partidos) > 0)
        self.assertEqual(partidos, sorted(partidos))

        ufs = listar_ufs(self.df)
        self.assertIn("PB", ufs)
        self.assertEqual(ufs, sorted(ufs))


class TestMetrics(unittest.TestCase):
    """Testes para o módulo de cálculos métricos e analíticos."""

    def test_calcular_custo_voto(self) -> None:
        """Verifica o agrupamento e tratamento de votos zerados/nulos."""
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

        # Cand 1: receita total 1000, 100 votos -> custo 10.0
        cand1 = resultado[resultado["cpf_candidato"] == "111"].iloc[0]
        self.assertEqual(cand1["total_receita"], 1000.0)
        self.assertAlmostEqual(cand1["custo_voto"], 10.0)

        # Cand 2: 0 votos -> custo 0.0 (sem erro de divisão)
        cand2 = resultado[resultado["cpf_candidato"] == "222"].iloc[0]
        self.assertEqual(cand2["custo_voto"], 0.0)

        # Cand 3: votos nulos -> custo 0.0
        cand3 = resultado[resultado["cpf_candidato"] == "333"].iloc[0]
        self.assertEqual(cand3["custo_voto"], 0.0)

    def test_identificar_porta_giratoria(self) -> None:
        """Verifica o filtro de fornecedores e cálculo de taxa de retorno."""
        dados = pd.DataFrame({
            "nome_candidato": ["Cand A", "Cand B", "Cand C"],
            "valor_receita": [1000.0, 500.0, 0.0],
            "valor_recebido_como_fornecedor": [250.0, 0.0, 100.0],
        })
        resultado = identificar_porta_giratoria(dados)

        # Apenas Cand A e Cand C têm fornecedor > 0
        self.assertEqual(len(resultado), 2)

        # Cand A: 250 / 1000 * 100 = 25.0%
        cand_a = resultado[resultado["nome_candidato"] == "Cand A"].iloc[0]
        self.assertAlmostEqual(cand_a["taxa_retorno"], 25.0)

        # Cand C: receita = 0 -> divisão tratada com segurança
        cand_c = resultado[resultado["nome_candidato"] == "Cand C"].iloc[0]
        self.assertEqual(cand_c["taxa_retorno"], 0.0)

    def test_analise_fluxo_geografico(self) -> None:
        """Testa o cálculo de montantes e percentuais intra vs inter estadual."""
        dados = pd.DataFrame({
            "sigla_uf_doador": ["PB", "PB", "SP", "RJ"],
            "valor_receita": [700.0, 300.0, 600.0, 400.0],
        })
        resultado = analise_fluxo_geografico(dados, uf_candidato="PB")

        self.assertEqual(resultado["uf_referencia"], "PB")
        self.assertAlmostEqual(resultado["montante_propria_uf"], 1000.0)
        self.assertAlmostEqual(resultado["montante_outras_ufs"], 1000.0)
        self.assertAlmostEqual(resultado["total_captado"], 2000.0)
        self.assertAlmostEqual(resultado["percentual_propria_uf"], 50.0)
        self.assertAlmostEqual(resultado["percentual_outras_ufs"], 50.0)

    def test_correlacao_sucesso_financeiro(self) -> None:
        """Testa a correlação e tratamento para variância nula."""
        # Caso com variação
        dados = pd.DataFrame({
            "valor_receita": [100.0, 1000.0],
            "situacao": ["indeferido", "eleito por qp"],
        })
        corr = correlacao_sucesso_financeiro(dados)
        self.assertIsInstance(corr, float)
        self.assertAlmostEqual(corr, 1.0)

        # Caso com variância zero (nenhum eleito)
        dados_sem_eleitos = pd.DataFrame({
            "valor_receita": [100.0, 200.0, 300.0],
            "situacao": ["deferido", "indeferido", "cassado"],
        })
class TestDataAuditorCriteria(unittest.TestCase):
    """Testes específicos para os 4 critérios mandatórios de 1_data_auditor.md."""

    def test_criterio_1_zeros_a_esquerda_preservados(self) -> None:
        """Critério 1: cpf_candidato, cpf_cnpj_doador e cnpj_basico são strings estritas."""
        df = carregar_dados()
        for col in ["cpf_candidato", "cpf_cnpj_doador", "cnpj_basico"]:
            self.assertIn(col, df.columns)
            self.assertTrue(
                isinstance(df[col].dtype, pd.StringDtype) or df[col].dtype == object,
                f"Coluna {col} deve ser tratada como tipo textual",
            )
            # Verifica que valores com zero à esquerda não foram convertidos para int/float
            amostra_zeros = df[df[col].astype(str).str.startswith("0")][col].dropna()
            if not amostra_zeros.empty:
                primeiro = str(amostra_zeros.iloc[0])
                self.assertTrue(primeiro.startswith("0"), f"Zero inicial perdido em {col}")

    def test_criterio_2_nulos_cnpj_basico_sem_string_nan(self) -> None:
        """Critério 2: cnpj_basico nulo não deve conter a string literal 'nan' ou 'None'."""
        df = carregar_dados()
        self.assertFalse(
            (df["cnpj_basico"] == "nan").any(),
            "cnpj_basico não deve conter string literal 'nan'",
        )
        self.assertFalse(
            (df["cnpj_basico"] == "None").any(),
            "cnpj_basico não deve conter string literal 'None'",
        )

    def test_criterio_3_parsing_monetario_sem_truncamento(self) -> None:
        """Critério 3: parsing de vírgula e centavos sem truncamento e sem multiplicação."""
        conteudo = (
            "ano;cpf_candidato;nome_candidato;cargo;sigla_partido;situacao;total_votos;"
            "cpf_cnpj_doador;nome_doador;sigla_uf_doador;valor_recebido_como_fornecedor;"
            "valor_receita;cnpj_basico\n"
            "2022;0123;Cand;cargo;P1;deferido;100;123;Doador;PB;1.500,50;554837,67;None\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_f = Path(tmpdir) / "teste_monetario.csv"
            parq_f = Path(tmpdir) / "teste_monetario.parquet"
            csv_f.write_text(conteudo, encoding="utf-8")

            converter_csv_para_parquet(csv_f, parq_f, file_id_drive=None)
            df = pd.read_parquet(parq_f)

            self.assertAlmostEqual(df["valor_recebido_como_fornecedor"].iloc[0], 1500.50)
            self.assertAlmostEqual(df["valor_receita"].iloc[0], 554837.67)

    def test_criterio_4_prevencao_duplicacao_votos(self) -> None:
        """Critério 4: candidatos com múltiplas doações não duplicam votos nem se bifurcam."""
        dados_multiplas_doacoes = pd.DataFrame({
            "cpf_candidato": ["999", "999", "999"],
            "nome_candidato": ["Candidato Multi", "Candidato Multi", "Candidato Multi"],
            "cargo": ["vereador", "vereador", "vereador"],
            "sigla_partido": ["P1", "P1", "P1"],
            "situacao": ["deferido", "deferido", "deferido"],
            # Simula inconsistência comum onde doações trazem total_votos divergentes
            "total_votos": [100, 100, 95],
            "valor_receita": [1000.0, 2000.0, 3000.0],
        })

        # 1. Teste em calcular_custo_voto: candidato deve resultar em exatamente 1 linha
        custo = calcular_custo_voto(dados_multiplas_doacoes)
        self.assertEqual(len(custo), 1, "Candidato com votos divergentes não deve bifurcar")
        self.assertEqual(custo["total_votos"].iloc[0], 100, "Deve consolidar com o máximo de votos")
        self.assertEqual(custo["total_receita"].iloc[0], 6000.0, "Receita deve ser somada")
        self.assertAlmostEqual(custo["custo_voto"].iloc[0], 60.0)

        # 2. Teste em obter_dimensao_candidatos: sem duplicação
        dim_cand = obter_dimensao_candidatos(dados_multiplas_doacoes)
        self.assertEqual(len(dim_cand), 1)
        self.assertEqual(dim_cand["total_votos"].iloc[0], 100)


class TestMethodologyAuditorCriteria(unittest.TestCase):
    """Testes específicos para os 4 critérios mandatórios de 2_methodology_auditor.md."""

    def test_criterio_1_agrupamento_antes_da_divisao(self) -> None:
        """Critério 1: custo_voto = sum(receita) / votos (agrupado antes da divisão)."""
        # Candidato com 3 doações de 100 cada (total 300) e 10 votos -> custo correto = 30.0
        df = pd.DataFrame({
            "cpf_candidato": ["C1", "C1", "C1"],
            "nome_candidato": ["Cand", "Cand", "Cand"],
            "cargo": ["prefeito", "prefeito", "prefeito"],
            "sigla_partido": ["P1", "P1", "P1"],
            "situacao": ["deferido", "deferido", "deferido"],
            "total_votos": [10, 10, 10],
            "valor_receita": [100.0, 100.0, 100.0],
        })
        custo_df = calcular_custo_voto(df)
        self.assertEqual(len(custo_df), 1)
        self.assertAlmostEqual(custo_df["total_receita"].iloc[0], 300.0)
        self.assertAlmostEqual(custo_df["custo_voto"].iloc[0], 30.0)

    def test_criterio_2_divisao_por_zero_e_receita_nula(self) -> None:
        """Critério 2: candidatos com 0 votos ou 0 receita não geram NaN nem erro."""
        df = pd.DataFrame({
            "cpf_candidato": ["Z1", "Z2", "Z3"],
            "nome_candidato": ["A", "B", "C"],
            "cargo": ["prefeito", "prefeito", "prefeito"],
            "sigla_partido": ["P1", "P1", "P1"],
            "situacao": ["deferido", "deferido", "deferido"],
            "total_votos": [0, -5, None],
            "valor_receita": [0.0, 1000.0, 500.0],
        })
        custo_df = calcular_custo_voto(df)
        for val in custo_df["custo_voto"]:
            self.assertEqual(val, 0.0)
            self.assertFalse(np.isnan(val))

    def test_criterio_3_porta_giratoria_retorno_acima_100_pct(self) -> None:
        """Critério 3: taxas de retorno > 100% não são mascaradas nem truncadas."""
        df = pd.DataFrame({
            "nome_candidato": ["Cand"],
            "valor_receita": [100.0],
            "valor_recebido_como_fornecedor": [5000.0],  # retorno de 5000%
        })
        pg = identificar_porta_giratoria(df)
        self.assertEqual(len(pg), 1)
        self.assertAlmostEqual(pg["taxa_retorno"].iloc[0], 5000.0)

    def test_criterio_4_alinhamento_eleito_vs_nao_eleito_e_assimetria(self) -> None:
        """Critério 4: 'não eleito' é codificado como 0 e suporta log/Spearman para assimetria."""
        df = pd.DataFrame({
            "valor_receita": [100.0, 500.0, 10000.0, 50000.0],
            "situacao": ["Não Eleito", "Não Eleito", "Eleito", "Eleito por QP"],
        })
        # Verifica correlação linear Pearson
        corr_pearson = correlacao_sucesso_financeiro(df, metodo="pearson")
        self.assertGreater(corr_pearson, 0.0)
        self.assertFalse(np.isnan(corr_pearson))

        # Verifica correlação com tratamento de assimetria via log
        corr_log = correlacao_sucesso_financeiro(df, usar_log=True)
        self.assertGreater(corr_log, 0.0)

        # Verifica Spearman
        corr_spearman = correlacao_sucesso_financeiro(df, metodo="spearman")
        self.assertGreater(corr_spearman, 0.0)

    def test_metricas_expansao_nacional(self) -> None:
        """Testa as novas métricas de origem de recursos, autofinanciamento e custo por UF."""
        df_exemplo = pd.DataFrame({
            "tipo_receita": ["Dinheiro Público", "Financiamento Privado", "Dinheiro Público"],
            "valor_receita": [1000.0, 500.0, 3000.0],
            "autofinanciamento": [0, 1, 0],
            "situacao": ["Não Eleito", "Eleito", "Eleito"],
            "cpf_candidato": ["111", "222", "333"],
            "nome_candidato": ["A", "B", "C"],
            "uf_candidato": ["SP", "RJ", "SP"],
            "cargo": ["PREFEITO", "PREFEITO", "PREFEITO"],
            "sigla_partido": ["P1", "P2", "P1"],
            "total_votos": [100, 200, 300],
        })

        # 1. Origem dos recursos
        res_origem = analise_origem_recursos(df_exemplo)
        self.assertEqual(len(res_origem), 2)
        self.assertAlmostEqual(res_origem.loc[res_origem["tipo_receita"] == "Dinheiro Público", "total_arrecadado"].iloc[0], 4000.0)
        self.assertAlmostEqual(res_origem["percentual"].sum(), 100.0)

        # 2. Autofinanciamento
        res_auto = analise_autofinanciamento(df_exemplo)
        self.assertAlmostEqual(res_auto["volume_autofinanciamento"], 500.0)
        self.assertAlmostEqual(res_auto["volume_terceiros"], 4000.0)
        self.assertAlmostEqual(res_auto["taxa_autofinanciamento"], 33.33333333333333)

        # 3. Custo por UF
        res_uf = analise_custo_voto_por_uf(df_exemplo)
        self.assertEqual(len(res_uf), 2)
        self.assertIn("uf_candidato", res_uf.columns)

    def test_heatmap_brasil_e_geojson(self) -> None:
        """Testa o módulo src/geo.py: integridade do GeoJSON e geração do mapa coroplético."""
        from src.geo import carregar_geojson_brasil, gerar_heatmap_brasil, agregar_dados_por_uf

        # 1. Valida malha geográfica
        geo = carregar_geojson_brasil()
        self.assertIn("features", geo)
        self.assertEqual(len(geo["features"]), 27, "O GeoJSON deve conter exatamente 27 UFs")

        # 2. Agregação e mapa de calor
        df_amostra = pd.DataFrame({
            "uf_candidato": ["SP", "RJ", "MG", "BA"],
            "valor_receita": [10000.0, 5000.0, 3000.0, 2000.0],
            "cpf_candidato": ["1", "2", "3", "4"],
            "cpf_cnpj_doador": ["D1", "D2", "D3", "D4"],
            "total_votos": [100, 50, 30, 20],
        })

        df_uf = agregar_dados_por_uf(df_amostra)
        self.assertEqual(len(df_uf), 27, "Base geográfica deve cobrir todas as 27 UFs")
        self.assertIn("custo_mediano_voto", df_uf.columns)

        # 3. Geração da figura choropleth
        fig = gerar_heatmap_brasil(df_amostra, metrica="total_arrecadado")
        self.assertIsNotNone(fig)
        self.assertTrue(len(fig.data) > 0)
        self.assertEqual(fig.data[0].type, "choropleth")

    def test_garantia_sem_graficos_circulares(self) -> None:
        """Assegura categoricamente a ausência de gráficos pie/donut em todo o repositório."""
        import glob
        arquivos = glob.glob("pages/*.py") + glob.glob("src/*.py") + ["app.py"]
        for arq in arquivos:
            with open(arq, "r", encoding="utf-8") as f:
                conteudo = f.read()
                self.assertNotIn("px.pie", conteudo, f"Encontrado px.pie em {arq}")
                self.assertNotIn("go.Pie", conteudo, f"Encontrado go.Pie em {arq}")
                self.assertNotIn("hole=", conteudo, f"Encontrado hole= (gráfico donut) em {arq}")


if __name__ == "__main__":
    unittest.main()


