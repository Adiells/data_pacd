# 🗳️ Observatório do Financiamento Eleitoral (PACD)

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Streamlit App](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B.svg)](https://streamlit.io/)
[![DuckDB](https://img.shields.io/badge/DuckDB-0.10%2B-FFF000.svg)](https://duckdb.org/)
[![Apache Arrow](https://img.shields.io/badge/Apache%20Arrow-Parquet-orange.svg)](https://arrow.apache.org/)
[![Cobertura Territorial](https://img.shields.io/badge/Cobertura-27%20UFs%20(Brasil)-success.svg)](#-abrangência-nacional-e-dados)
[![Base de Dados](https://img.shields.io/badge/Transa%C3%A7%C3%B5es-959.770-informational.svg)](#-abrangência-nacional-e-dados)
[![Volume Rastreado](https://img.shields.io/badge/Volume-R%24%2012%2C11%20Bi-brightgreen.svg)](#-abrangência-nacional-e-dados)

Plataforma analítica e de ciência de dados para investigação quantitativa sobre o poder do dinheiro nas eleições brasileiras. A ferramenta integra microdados oficiais do **Tribunal Superior Eleitoral (TSE)** e cruzamentos com o **Quadro de Sócios e Administradores (QSA/Receita Federal)** para todas as **27 Unidades Federativas** (26 Estados + Distrito Federal) nos pleitos de **2018, 2020, 2022 e 2024**.

---

## 📌 Sumário

- [Visão Geral & Objetivos](#-visão-geral--objetivos)
- [Abrangência Nacional e Dados](#-abrangência-nacional-e-dados)
- [Hipóteses Científicas Investigadas](#-hipóteses-científicas-investigadas)
- [Módulos da Aplicação](#-módulos-da-aplicação)
- [Documentação Técnica (Pasta `docs/`)](#-documentação-técnica-pasta-docs)
- [Padrões de Visualização de Dados](#-padrões-de-visualização-de-dados)
- [Arquitetura & Tecnologias](#-arquitetura--tecnologias)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Como Executar](#-como-executar)
- [Suíte de Testes Automatizados](#-suíte-de-testes-automatizados)

---

## 🔍 Visão Geral & Objetivos

O financiamento político é o principal vetor de desigualdade competitiva nas democracias contemporâneas. Esta plataforma foi concebida para permitir diagnósticos empíricos e auditorias cívicas sobre:

1. **Assimetria e Concentração de Capital:** Como uma fração ínfima de candidaturas capta a imensa maioria dos fundos públicos e privados.
2. **Custo do Voto e Teto de Vidro (H1):** Qual o investimento financeiro mínimo necessário para tornar uma candidatura eleitoralmente viável em cada cargo e estado.
3. **O Circuito da Porta Giratória (H2):** Como doadores pessoas físicas são contratados como fornecedores da mesma campanha através de suas empresas (QSA/CNPJ básico), contornando o veto a doações empresariais.
4. **Hegemonia do Fundo Eleitoral:** A evolução histórica da transição de doações privadas para o domínio absoluto dos fundos públicos (FEFC e Fundo Partidário).
5. **Autofinanciamento:** O impacto das candidaturas autossustentadas pelo patrimônio pessoal dos próprios concorrentes.

---

## 📊 Abrangência Nacional e Dados

A base canônica foi compilada a partir de todos os arquivos estaduais oficiais do TSE/CGU:

- **Arquivo Canônico:** `data/processed/base_consolidada_eleicoes.parquet` (Compressão Snappy - **42.13 MB**)
- **Volume Consolidado:** **959.770 registros de transações de receita**
- **Montante Financeiro Auditado:** **R$ 12.110.155.337,17 (R$ 12,11 Bilhões)**
- **Cobertura Territorial:** **100% dos estados brasileiros (26 Estados + DF)**
- **Distribuição por Eleição:**
  - **2018 (Geral):** 52.287 registros
  - **2020 (Municipal):** 625.328 registros
  - **2022 (Geral):** 39.421 registros
  - **2024 (Municipal):** 242.734 registros

A aplicação inicia por padrão na **Visão Nacional ("Todas as UFs / Brasil")**, permitindo filtragem granular por estado na barra lateral a qualquer momento.

---

## 💡 Hipóteses Científicas Investigadas

| Hipótese | Denominação | Descrição | Validação Empírica |
| :--- | :--- | :--- | :--- |
| **H1** | **Teto de Vidro Financeiro** | Existe um custo por voto mínimo (barreira financeira) abaixo do qual a chance de êxito eleitoral é nula. | Dispersão Log-Log, Linha de Piso e Teste de Mann-Whitney U. |
| **H2** | **Circuito da Porta Giratória** | Doadores pessoas físicas contornam a proibição de doações de PJ recebendo pagamentos como fornecedores de campanha via QSA. | Chave `cnpj_basico`, taxa de retorno (%) e Diagrama Sankey. |
| **H3** | **Assimetria de Pareto** | A arrecadação eleitoral segue uma lei de potência extrema, com o Top 10% concentrando a quase totalidade dos recursos. | Histogramas em escala log e taxas comparadas Top 10% vs Bottom 50%. |

---

## 🧭 Módulos da Aplicação

### 1. Hub Central e Metodologia (`app.py`)
- Apresentação do projeto, contextualização científica e objetivos da auditoria.
- Badges dinâmicos com contadores da cobertura nacional (27 UFs, 4 pleitos, 959k transações).
- Cards interativos de navegação direta para os módulos especializados.

### 2. Visão Geral & Concentração (`pages/1_visao_geral.py`)
- **KPIs Estratégicos:** Total arrecadado, candidatos, doadores únicos e taxa de sucesso Top 10% vs Bottom 50%.
- **🗺️ Mapa de Calor do Brasil (Heatmap Federativo):** Mapa coroplético interativo cobrindo as 27 UFs com seletor de métricas:
  - 💰 *Volume Arrecadado (R$)*
  - 👥 *Quantidade de Candidatos*
  - 🤝 *Doadores Únicos (CPFs)*
  - 🗳️ *Custo Mediano do Voto (R$/voto)*
- **Rankings Top 10:** Maiores doadores (com CPF anonimizado LGPD) e candidatos mais financiados coloridos por resultado.
- **Histograma Logarítmico:** Visualização clara da assimetria extrema do capital político.

### 3. Custo do Voto & Teste H1 (`pages/2_custo_do_voto.py`)
- **Piso Empírico de Viabilidade:** Menor receita observada entre candidaturas eleitas no recorte ativo.
- **Gráfico de Dispersão Log-Log:** Total de Votos vs. Receita Total com linha horizontal de referência e cores por resultado eleitoral.
- **Avaliação Estatística:** Aplicação do teste de **Mann-Whitney U** com p-valor para verificar se eleitos têm receita estatisticamente superior aos não eleitos.
- **Boxplots Comparativos:** Distribuição de custo por voto entre partidos e resultados.

### 4. Porta Giratória & Cruzamento QSA (`pages/3_porta_giratoria.py`)
- **Auditoria de Conflitos de Interesse:** Rastreamento onde o doador pessoa física possui vínculos societários com empresas contratadas como fornecedoras.
- **Diagrama Sankey Interativo:** Mapeamento visual do fluxo de capitais: *Doador (PF) $\rightarrow$ Campanha $\rightarrow$ Fornecedor (PJ vinculada)*.
- **Tabela com Margem de Retorno:** Filtro por taxa de retorno mínima (%) e identificação da UF de ocorrência.

### 5. Origem dos Recursos & Autofinanciamento (`pages/4_origem_e_autofinanciamento.py`)
- **Evolução Histórica (2018 a 2024):** Acompanhamento da dominância do Fundo Eleitoral Público frente a doações privadas.
- **Termômetro do Autofinanciamento:** Volume total injetado com recursos próprios, média por candidatura e taxa de vitória comparada (*Candidatos com autofinanciamento vs sem autofinanciamento*).
- **Ranking Top 15:** Maiores investidores de capital pessoal do país ou do estado selecionado.

---

## 📖 Documentação Técnica (Pasta `docs/`)

Para detalhes arquiteturais, de engenharia e regras de negócio aprofundadas, consulte os documentos na pasta [`docs/`](file:///home/adiel/Projects/pacd/docs/):

- 📚 [**Dicionário de Dados**](file:///home/adiel/Projects/pacd/docs/dicionario_de_dados.md): Especificação de todas as colunas, tipos DuckDB/Pandas e regras de preenchimento.
- 🔬 [**Metodologia Científica e Regras de Negócio**](file:///home/adiel/Projects/pacd/docs/metodologia_e_regras_de_negocio.md): Formalização matemática de H1, formulação de H2, regras oficiais do PDF do TSE/CGU e normas LGPD.
- 🏗️ [**Arquitetura do Sistema**](file:///home/adiel/Projects/pacd/docs/arquitetura.md): Estrutura técnica em camadas, DuckDB + Parquet, sistema geoespacial offline e gestão de estado global.
- 🚀 [**Guia de Execução e Reproducibilidade**](file:///home/adiel/Projects/pacd/docs/guia_de_execucao.md): Passo a passo para baixar CSVs, consolidar a base, executar a aplicação e rodar a suíte de testes.

---

## 🎨 Padrões de Visualização de Dados

Em conformidade com as melhores práticas de visualização científica:
- ❌ **Sem Gráficos de Pizza (`pie plot`) ou Rosca (`donut plot`):** Substituídos integralmente por **gráficos de barras horizontais ordenadas** (`px.bar` horizontal) com indicação direta dos montantes em R$ e proporções percentuais (%).
- 📈 **Escalas Logarítmicas:** Utilizadas em distribuições de cauda longa para permitir análise simultânea de candidatos com R$ 1.000 e R$ 10.000.000.
- 🗺️ **Coropletos com Geometrias Locais:** Mapas de calor sem requisições HTTP externas no cliente, com paletas perceptualmente uniformes (`YlOrRd`, `Blues`, `Purples`).

---

## 🛠️ Arquitetura & Tecnologias

- **Interface:** [Streamlit 1.35+](https://streamlit.io/) com navegação multi-páginas e layout wide.
- **Engine Analítica:** [DuckDB](https://duckdb.org/) executando consultas vetoriais ultra-rápidas diretamente no Parquet.
- **Armazenamento:** [Apache Arrow / Parquet](https://arrow.apache.org/) colunar comprimido em Snappy.
- **Visualização:** [Plotly Express & Graph Objects](https://plotly.com/python/).
- **Estatística:** [NumPy](https://numpy.org/), [Pandas](https://pandas.pydata.org/), [SciPy](https://scipy.org/).

---

## 📂 Estrutura do Projeto

```text
pacd/
├── app.py                            # Página inicial, metodologia e badges nacionais
├── requirements.txt                  # Dependências do projeto
├── README.md                         # Documentação principal
├── docs/                             # Documentação técnica e científica em Markdown
│   ├── arquitetura.md                # Arquitetura de software e engenharia de dados
│   ├── dicionario_de_dados.md        # Dicionário do dataset consolidado Parquet
│   ├── guia_de_execucao.md           # Guia de instalação, ingestão e execução
│   └── metodologia_e_regras_de_negocio.md # Hipóteses científicas e regras TSE/CGU
├── data/
│   ├── geo/                          # Malhas cartográficas locais
│   │   └── brazil-states.geojson     # Delimitações vetoriais das 27 UFs do Brasil
│   ├── processed/                    # Data Lake local otimizado
│   │   └── base_consolidada_eleicoes.parquet # Base canônica (959k linhas, 42 MB)
│   └── raw/                          # Microdados brutos (CSVs estaduais)
├── pages/                            # Módulos analíticos multi-páginas do Streamlit
│   ├── 1_visao_geral.py              # KPIs, Heatmap Brasil, Top 10 e Distribuição
│   ├── 2_custo_do_voto.py            # Teste H1, Custo do Voto e Mann-Whitney U
│   ├── 3_porta_giratoria.py          # Auditoria QSA, Diagrama Sankey e Retorno (%)
│   └── 4_origem_e_autofinanciamento.py # Evolução temporal e patrimônio pessoal
├── scripts/
│   ├── convert_csv_to_parquet.py     # Pipeline DuckDB de consolidação Parquet
│   └── download_all_states.py        # Download multithreaded das 27 UFs do Google Drive
├── src/
│   ├── data_loader.py                # Leitura e cache com DuckDB/PyArrow
│   ├── geo.py                        # Motor geoespacial e gerador do Heatmap do Brasil
│   ├── metrics.py                    # Biblioteca de cálculos estatísticos e eleitorais
│   └── ui_components.py              # Filtros globais (st.session_state) e formatação
└── tests/
    └── test_pipeline.py              # Suíte com 18 testes automatizados (unittest)
```

---

## 🚀 Como Executar

### 1. Iniciar o Dashboard Web

```bash
.venv/bin/streamlit run app.py
```
Acesse no navegador: **`http://localhost:8501`**.

### 2. Consolidar os Dados (Caso queira reprocessar)

```bash
.venv/bin/python scripts/convert_csv_to_parquet.py
```

---

## 🧪 Suíte de Testes Automatizados

Para rodar todos os 18 testes de regressão, integridade e regras de negócio:

```bash
.venv/bin/python -m unittest discover tests
```

Saída esperada:
```text
Ran 18 tests in ~3.0s
OK
```
