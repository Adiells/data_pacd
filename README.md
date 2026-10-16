# 🗳️ Painel Eleitoral (PACD) — Single-Page Application (SPA)

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18.x-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![TailwindCSS](https://img.shields.io/badge/TailwindCSS-3.x-38B2AC.svg?logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![Chart.js](https://img.shields.io/badge/Chart.js-4.x-FF6384.svg?logo=chartdotjs&logoColor=white)](https://www.chartjs.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-0.10%2B-FFF000.svg)](https://duckdb.org/)
[![Apache Arrow](https://img.shields.io/badge/Apache%20Arrow-Parquet-orange.svg)](https://arrow.apache.org/)
[![Cobertura Territorial](https://img.shields.io/badge/Cobertura-27%20UFs%20(Brasil)-success.svg)](#-abrangência-nacional-e-dados)
[![Volume Rastreado](https://img.shields.io/badge/Volume-R%24%2012%2C11%20Bi-brightgreen.svg)](#-abrangência-nacional-e-dados)

> 🌐 **Painel SPA em Execução Local:** [http://localhost:8000/](http://localhost:8000/)  
> 📑 **Documentação da API (Swagger / OpenAPI):** [http://localhost:8000/docs](http://localhost:8000/docs)  
> 🩺 **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

Plataforma de alta performance para investigação quantitativa sobre o poder do capital nas eleições brasileiras. O sistema opera como uma **Single-Page Application (SPA)** de padrão visual premium (React 18 + TailwindCSS + Chart.js) alimentada por uma **API analítica FastAPI com DuckDB**. Integra microdados oficiais do **Tribunal Superior Eleitoral (TSE)** e cruzamentos societários da **Receita Federal (QSA)** para todas as **27 Unidades Federativas** nos pleitos de **2018, 2020, 2022 e 2024**.

---

## 📌 Sumário

- [Diretrizes Rigorosas de UI/UX (Zero Textos e Zero Conclusões)](#-diretrizes-rigorosas-de-uiux-zero-textos-e-zero-conclusões)
- [Arquitetura e Stack Tecnológica](#-arquitetura-e-stack-tecnológica)
- [Regras Eleitorais de Negócio e Travas de Filtros](#-regras-eleitorais-de-negócio-e-travas-de-filtros)
- [Malha Fina Textual (Regex da Porta Giratória)](#-malha-fina-textual-regex-da-porta-giratória)
- [Abrangência Nacional e Dados](#-abrangência-nacional-e-dados)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Como Executar](#-como-executar)
- [Suíte de Testes Automatizados](#-suíte-de-testes-automatizados)

---

## 🎯 Diretrizes Rigorosas de UI/UX (Zero Textos e Zero Conclusões)

Em estrito alinhamento com as regras de negócio do projeto:
1. **Apenas Gráficos, KPIs e Títulos:** A interface contém **exclusivamente** indicadores numéricos (KPIs), controles de filtro e gráficos com seus respectivos títulos.
2. **Proibido Textos Explicativos e Conclusões:** Não há parágrafos introdutórios, textos explicativos, subtítulos descritivos, caixas de "insights", resumos ou seções de "Conclusão". O painel é puramente visual e analítico.
3. **Bloco Fixo Global ("Tudo e Todos"):** O topo da página exibe métricas e rankings consolidados de toda a base histórica, **imunes à ação dos filtros**:
   - 4 KPIs Estratégicos: *Volume Financeiro Ativo*, *Candidaturas no Recorte*, *Doadores no Recorte* e *Transações Registradas*.
   - 4 Gráficos Globais: *Top 10 Doadores*, *Top 10 Candidatos Mais Financiados*, *Distribuição do Volume Arrecadado (Escala Logarítmica)* e *Autofinanciamento: Os Maiores Investidores da Própria Campanha*.
4. **Visualização Dinâmica ("1 por vez"):** Abaixo do topo global e da barra de filtros de alto contraste, o usuário alterna entre os módulos analíticos exibindo **apenas uma seção por vez** na tela via Segmented Control / Tabs modernas:
   - **Visão Geral:** KPIs dinâmicos, Top 10 Doadores, Top 10 Candidatos, Distribuição Log, Composição por Origem do Recurso, Ranking Federativo (Top Estados) e Mapa de Calor do Brasil (Heatmap).
   - **Custo do Voto:** Resumo do recorte e Scatter Plot (Votos vs. Receita com Piso de Viabilidade).
   - **Porta Giratória:** KPIs de retorno, Comparativo Bidirecional e Ranking dos Maiores Casos.
   - **Origem dos Recursos & Autofinanciamento:** KPIs comparativos de sucesso, Maiores Investidores Próprios e Evolução Histórica por Origem.

---

## 🛠️ Arquitetura e Stack Tecnológica

O projeto abandonou integralmente o Streamlit para adotar uma arquitetura desacoplada e reativa:

- **Frontend (SPA):** Single-Page Application moderna em HTML5/ES6 com React 18, TailwindCSS (Dark Mode nativo) e Chart.js com renderização vetorial interativa em Canvas.
- **Backend API:** [FastAPI](https://fastapi.tiangolo.com/) com rotas RESTful assíncronas, esquemas parametrizados e processamento de dados via **DuckDB** e **PyArrow**.
- **Concorrência e Thread-Safety:** Consultas ao DuckDB canalizadas através de cursores isolados e controle de concorrência (`threading.Lock`), garantindo estabilidade absoluta sob múltiplas requisições simultâneas.
- **Armazenamento:** [Apache Arrow / Parquet](https://arrow.apache.org/) colunar comprimido em Snappy.

---

## ⚖️ Regras Eleitorais de Negócio e Travas de Filtros

- **Eleições Gerais (2018 e 2022):** Permite selecionar apenas os cargos de *Presidente*, *Governador*, *Senador*, *Deputado Federal*, *Deputado Estadual* e *Deputado Distrital*. O seletor de Município é **desativado** na interface e forçado para `"TODOS"`.
- **Eleições Municipais (2020 e 2024):** Permite selecionar apenas os cargos de *Prefeito* e *Vereador*.
- **Visão Geral sem Acúmulo de Anos:** Os gráficos da Visão Geral não acumulam eleições de anos diferentes; a consulta exige obrigatoriamente um ano eleitoral específico.
- **Trava de Custo do Voto:** O gráfico de dispersão (*Scatter Plot*) só é renderizado quando houver **1 Ano específico E 1 Cargo específico** selecionados nos filtros. Sem seleção específica, a renderização é suspensa com aviso visual. **Boxplots foram completamente banidos**.

---

## 🧹 Malha Fina Textual (Regex da Porta Giratória)

Para isolar transações estritamente particulares e expurgar repasses partidários ou entre aliados:
- **Padrão Institucional/Público:** `(?i)(dire[cç][aãõo]es|dire[cç][aã]o|[oó]rg[aã]os?|comiss[aãõo]es|comiss[aã]o|comit[eê]s?|partidos?)`
- **Padrão de Aliados (Repasse):** `(?i)(elei[cç][aãõo]es|elei[cç][aã]o|campanhas?)`
- **Higienização:** Ambas as expressões são aplicadas após a normalização de acentos e diacríticos (`unicodedata.normalize`), garantindo 0 registros espúrios nos rankings e comparativos.

---

## 📊 Abrangência Nacional e Dados

- **Arquivo Canônico:** `data/processed/base_consolidada_eleicoes.parquet` (Snappy — **42.13 MB**)
- **Volume Consolidado:** **959.770 registros de transações de receita**
- **Montante Financeiro Auditado:** **R$ 12.112.959.243,11 (R$ 12,11 Bilhões)**
- **Candidaturas no Recorte:** **472.276 candidatos**
- **Doadores Únicos:** **293.478 doadores**
- **Cobertura Territorial:** **100% das 27 UFs brasileiras** (26 Estados + Distrito Federal)
- **Distribuição Temporal:** 2018 (52k registros), 2020 (625k registros), 2022 (39k registros) e 2024 (241k registros).

---

## 📂 Estrutura do Projeto

```text
pacd/
├── api/
│   └── main.py                       # API FastAPI analítica (DuckDB thread-safe + endpoints REST)
├── frontend/
│   └── index.html                    # SPA completa (React 18 + TailwindCSS + Chart.js)
├── data/
│   ├── geo/                          # Malhas cartográficas locais
│   │   └── brazil-states.geojson     # Delimitações vetoriais das 27 UFs do Brasil
│   ├── processed/                    # Data Lake local otimizado
│   │   └── base_consolidada_eleicoes.parquet # Base canônica (959k linhas, 42 MB)
│   └── raw/                          # Microdados brutos do TSE/CGU
├── docs/                             # Documentação técnica e científica em Markdown
│   ├── arquitetura.md                # Arquitetura de software e engenharia de dados
│   ├── dicionario_de_dados.md        # Dicionário do dataset consolidado Parquet
│   ├── guia_de_execucao.md           # Guia de instalação, ingestão e execução
│   └── metodologia_e_regras_de_negocio.md # Hipóteses científicas e regras TSE/CGU
├── scripts/
│   ├── convert_csv_to_parquet.py     # Pipeline DuckDB de consolidação Parquet
│   └── download_all_states.py        # Download multithreaded das 27 UFs
├── src/
│   ├── data_loader.py                # Leitura de alta performance com DuckDB/PyArrow
│   ├── geo.py                        # Georreferenciamento e agregação espacial das 27 UFs
│   └── metrics.py                    # Biblioteca de cálculos estatísticos e malha fina Regex
├── tests/
│   └── test_pipeline.py              # Suíte com 18 testes automatizados (unittest)
├── requirements.txt                  # Dependências Python (FastAPI, DuckDB, Pandas, etc.)
├── AGENTS.md                         # Diretrizes e regras de negócio do painel
├── PROMPTS.md                        # Histórico de especificações das sprints
└── README.md                         # Documentação principal do projeto
```

---

## 🚀 Como Executar

### 1. Iniciar o Servidor FastAPI / SPA

No diretório raiz do projeto com o ambiente virtual ativado:

```bash
.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Acesse no navegador:
* 🖥️ **Painel SPA:** **`http://localhost:8000/`**
* 📑 **Documentação Interativa (Swagger):** **`http://localhost:8000/docs`**
* 🩺 **Health Check:** **`http://localhost:8000/health`**

---

## 🧪 Suíte de Testes Automatizados

Para executar os testes de integridade, cálculos eleitorais e conformidade:

```bash
.venv/bin/python -m unittest discover tests
```

Saída esperada:
```text
Ran 18 tests in ~8.0s
OK
```
