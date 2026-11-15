# 🗳️ PACD — Painel de Inteligência Política & Financiamento Eleitoral (2018–2024)

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18.x-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![TailwindCSS](https://img.shields.io/badge/TailwindCSS-3.x-38B2AC.svg?logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![Chart.js](https://img.shields.io/badge/Chart.js-4.x-FF6384.svg?logo=chartdotjs&logoColor=white)](https://www.chartjs.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-0.10%2B-FFF000.svg)](https://duckdb.org/)
[![Apache Arrow](https://img.shields.io/badge/Apache%20Arrow-Parquet-orange.svg)](https://arrow.apache.org/)
[![Base Consolidada](https://img.shields.io/badge/Registros-5%2C31M%20Transa%C3%A7%C3%B5es-brightgreen.svg)](#-abrangência-nacional-e-dados)

> 🌐 **Painel SPA Local:** [http://localhost:8000/](http://localhost:8000/)  
> 📑 **Documentação da API (Swagger / OpenAPI):** [http://localhost:8000/docs](http://localhost:8000/docs)  
> 🩺 **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

O **PACD (Pesquisa Aplicada em Ciência de Dados)** é uma plataforma de inteligência política e jornalismo investigativo voltada a rastrear o fluxo de capital e a influência econômica entre a **Elite Empresarial** e os candidatos nas eleições brasileiras de **2018, 2020, 2022 e 2024**, investigando como grupos corporativos atuam após a proibição das doações de Pessoas Jurídicas pelo STF (ADI 4650).

O sistema opera como uma **Single-Page Application (SPA)** em React 18 + Tailwind CSS + Chart.js 4, alimentada por uma **API analítica FastAPI + DuckDB In-Memory** executada diretamente sobre a base colunar `base_consolidada_eleicoes.parquet` (~224,6 MB), que é **baixada e validada automaticamente na primeira execução** via Google Drive.

---

## 📌 Sumário

- [Principais Recursos do Painel](#-principais-recursos-do-painel)
- [Arquitetura e Auto-Ingestão](#-arquitetura-e-auto-ingestão)
- [Abrangência Nacional e Dados](#-abrangência-nacional-e-dados)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [Como Executar](#-como-executar)
- [Documentação Técnica](#-documentação-técnica)
- [Suíte de Testes Automatizados](#-suíte-de-testes-automatizados)

---

## 🧭 Principais Recursos do Painel

1. **Interruptor Global de Origem em 3 Fases:**
   - **Todos os Recursos:** Fundos públicos (FEFC e Fundo Partidário), repasses entre aliados e capital privado.
   - **Somente Doações:** Isola estritamente o financiamento privado (pessoas físicas, autofinanciamento e financiamento coletivo).
   - **Elite Empresarial:** Filtra apenas recursos oriundos de doadores identificados como sócios, proprietários ou administradores de empresas ativas na Receita Federal (`is_empresario = TRUE`).
2. **Bloco Fixo Global ("Tudo e Todos"):**
   - Régua histórica nacional (2018–2024), imune aos filtros dinâmicos, exibindo os 4 KPIs globais, Top 10 Maiores Doadores Globais, Top 10 Candidatos Mais Financiados, Distribuição Logarítmica, Autofinanciamento Histórico, Ranking de Partidos e Ranking Federativo.
3. **Barra de Filtros Dinâmicos com Travas Constitucionais:**
   - **Ano:** Eleições individuais (`2018`, `2020`, `2022`, `2024`) ou ciclos consolidados (Eleições Gerais / Eleições Municipais).
   - **Cargo:** Isolamento automático entre pleitos gerais e municipais, incluindo bloqueio constitucional de *Prefeito* e *Vereador* no Distrito Federal (Art. 32 da CF/88).
   - **UF & Partido:** Seleção múltipla com agrupamento por região, busca rápida e blindagem de unicidade por candidatura `(ano, cpf_candidato, cargo)`.
4. **5 Abas Analíticas Dinâmicas:**
   - **Visão Geral:** KPIs do recorte, assertividade da elite corporativa, rankings expansíveis de candidatos e doadores, distribuição logarítmica, composição de recursos e gráfico adaptativo de partidos ou UFs.
   - **Análise Geográfica & Fluxo de Recursos:** Cartograma federativo Grid 8×8 com inspeção interativa por UF e mapeamento de **Rotas de Influência Interestadual** (`uf_empresa ➔ uf_candidato`).
   - **Custo do Voto:** Gráfico de dispersão (*Scatter Plot*) de Votos × Receita com mediana em R$/voto e cálculo do Piso de Viabilidade Financeira entre os eleitos.
   - **Teia Empresarial & Setores:** Indicadores da Elite Corporativa, Ranking de Setores Econômicos (CNAE/IBGE), Ranking de Grupos Empresariais (Razão Social/CNPJ básico) e Maiores Financiadores com **gavetas sanfona** consolidadas por relação `(Sócio ➔ Candidato)`.
   - **Origem dos Recursos & Autofinanciamento:** Evolução histórica por ciclo, comparativo entre capital próprio e recursos de terceiros e taxas de sucesso eleitoral.
5. **Rodapé Metodológico e Saneamento Contábil:**
   - Notas transparentes sobre os dois saneamentos cirúrgicos de erros de digitação do SPCE/TSE (Amazonas 2020 e Salvador/BA 2024), impacto da Lei nº 13.877/2019 no autofinanciamento e sigilo de domicílio PF pela LGPD.

---

## 🛠️ Arquitetura e Auto-Ingestão

- **Frontend (SPA):** [frontend/index.html](frontend/index.html) em React 18 Standalone, Tailwind CSS e Chart.js 4 via CDN (sem bundler nem etapa de build Node).
- **Backend (API):** [api/main.py](api/main.py) com FastAPI, consultas SQL parametrizadas em DuckDB In-Memory (`VIEW eleicoes` + tabela `sede_doadores`), cache em memória e controle de concorrência com `threading.Lock()`.
- **Auto-Ingestão & Proteção contra Ponteiro Git LFS:** [src/data_loader.py](src/data_loader.py) verifica se `data/processed/base_consolidada_eleicoes.parquet` existe localmente, possui tamanho mínimo (`>= 1 MB`) e assinatura binária válida (`PAR1` no cabeçalho e rodapé). Caso esteja ausente ou corrompido (por exemplo, um ponteiro de texto LFS), o download é feito automaticamente do Google Drive (`ID: 1CAUL7QTz587o0VpUkfhLBPn2EpMEHfwN`) na primeira execução.
- **Armazenamento:** [Apache Arrow / Parquet](https://arrow.apache.org/) colunar (~224,6 MB), mantido fora do versionamento Git (`.gitignore`).

---

## 📊 Abrangência Nacional e Dados

- **Arquivo Canônico:** `data/processed/base_consolidada_eleicoes.parquet` (`235.485.013 bytes` / ~224,6 MB)
- **Transações Registradas:** **5.310.738** registros enriquecidos (TSE + QSA/Receita Federal)
- **Volume Financeiro Ativo (Saneado):** **R$ 20.743.029.055,78** (**R$ 20,74 Bilhões**)
- **Candidaturas no Recorte Global:** **1.029.274** candidaturas distintas (`sequencial_candidato`)
- **Doadores Únicos:** **1.744.411** doadores efetivos (`valor_receita > 0`)
- **Cobertura Temporal e Territorial:** Pleitos de **2018, 2020, 2022 e 2024** em todas as **27 Unidades Federativas** além da disputa presidencial (`BR`).

---

## 📂 Estrutura do Projeto

```text
data_pacd/
├── api/
│   └── main.py                        # API FastAPI + DuckDB In-Memory + saneamento SQL
├── frontend/
│   └── index.html                     # SPA React 18 + Tailwind CSS + Chart.js 4
├── src/
│   ├── __init__.py
│   ├── data_loader.py                 # Auto-download Google Drive, validação PAR1 e seletores
│   └── metrics.py                     # Cálculo de custo por voto, decil e agregações
├── data/
│   └── processed/
│       ├── .gitkeep
│       └── base_consolidada_eleicoes.parquet  # Baixado automaticamente na 1ª execução
├── docs/
│   ├── arquitetura.md                 # Arquitetura de software e engenharia de dados
│   ├── dicionario_de_dados.md         # Esquema das 24 colunas do Parquet + view DuckDB
│   ├── guia_de_execucao.md            # Guia de instalação, bootstrap e execução
│   └── metodologia_e_regras_de_negocio.md # Hipóteses, blindagem contábil e saneamentos
├── tests/
│   └── test_pipeline.py               # Suíte de testes (integridade Parquet, métricas e API)
├── .devcontainer/
│   └── devcontainer.json
├── .gitignore
├── README.md
└── requirements.txt
```

---

## 🚀 Como Executar

### 1. Instalar dependências

No diretório raiz `data_pacd/`, crie e ative o ambiente virtual:

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Iniciar o Servidor (Download Automático no 1º Run)

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Na **primeira inicialização**, caso `data/processed/base_consolidada_eleicoes.parquet` ainda não exista na máquina, o backend fará o download automático (~224,6 MB) direto do Google Drive antes de inicializar o DuckDB. Nas execuções seguintes, a inicialização é instantânea.

Acesse no navegador:
* 🖥️ **Painel SPA:** `http://localhost:8000/`
* 📑 **Swagger UI:** `http://localhost:8000/docs`
* 🩺 **Health Check:** `http://localhost:8000/health`

---

## 📚 Documentação Técnica

- [Arquitetura do Sistema](docs/arquitetura.md)
- [Dicionário de Dados](docs/dicionario_de_dados.md)
- [Guia de Execução](docs/guia_de_execucao.md)
- [Metodologia e Regras de Negócio](docs/metodologia_e_regras_de_negocio.md)

---

## 🧪 Suíte de Testes Automatizados

Para validar a integridade binária do `.parquet`, as regras de negócio e os endpoints FastAPI + DuckDB:

```bash
python -m unittest discover -s tests -v
```
