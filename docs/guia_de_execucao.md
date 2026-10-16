# 🚀 Guia de Execução e Reproducibilidade

> 🌐 **Plataforma Online em Produção:** Acesse diretamente em [**https://observatorioeleitoral.streamlit.app/**](https://observatorioeleitoral.streamlit.app/)

Este guia passo a passo explica como acessar a versão em produção, configurar o ambiente local, executar os scripts de ingestão de dados, rodar a suíte de testes e iniciar a aplicação web.

---

## 💻 1. Pré-requisitos

- **Python:** Versão 3.10, 3.11, 3.12 ou superior
- **Gerenciador de Ambientes:** `venv` ou `uv`
- **Espaço em Disco:** ~250 MB livres (para os CSVs brutos e base Parquet)

---

## 📦 2. Instalação do Ambiente

Clone o repositório ou navegue até o diretório do projeto:

```bash
cd /home/adiel/Projects/pacd
```

Crie e ative um ambiente virtual:

```bash
# Utilizando venv padrão
python3 -m venv .venv
source .venv/bin/activate

# Ou utilizando uv (mais rápido)
uv venv
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

---

## 📥 3. Pipeline de Dados (Download e Consolidação)

### Passo 3.1: Download das 27 UFs do Google Drive (Opcional se já baixado)
Para baixar os CSVs brutos de todos os 27 estados da pasta oficial do Google Drive de forma paralela (multithreaded):

```bash
.venv/bin/python scripts/download_all_states.py
```
*Os arquivos são organizados na estrutura de subpastas por estado `data/raw/{UF}/1_doacoes_empresas_{UF}.csv` (espelhando a pasta `raw/` do Google Drive) ou no diretório `data/raw/estados/`.*

### Passo 3.2: Consolidação em Parquet Canônico via DuckDB
Para consolidar os 27 CSVs brutos na base analítica única `data/processed/base_consolidada_eleicoes.parquet` em ~2 segundos:

```bash
.venv/bin/python scripts/convert_csv_to_parquet.py
```

Você verá a saída indicando:
```text
[INFO] Processando 27 arquivos CSV estaduais...
[INFO] Base consolidada gravada com sucesso em 'data/processed/base_consolidada_eleicoes.parquet'
[INFO] Total de registros consolidados: 959.770 (Tamanho: 42.13 MB)
```

---

## 🌐 4. Iniciar a Aplicação Web (FastAPI + SPA)

Para iniciar o servidor backend e servir a Single-Page Application:

```bash
.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

A aplicação estará disponível no navegador no endereço:  
**`http://localhost:8000`**

- **Health Check da API:** `http://localhost:8000/health`
- **Documentação Interativa (Swagger/OpenAPI):** `http://localhost:8000/docs`

### Dicas de Navegação na SPA:
- **Bloco Global Fixo ("Tudo e Todos"):** O topo exibe os 4 KPIs macro e 4 gráficos analíticos consolidados de toda a base histórica (2018 a 2024), imunes aos filtros.
- **Barra de Filtros:** Container de alto contraste para seleção de Ano, Cargo, Partido, UF e Município com travas eleitorais estritas.
- **Visualização "1 por vez" (Tabs / Segmented Control):**
  1. `Visão Geral`: Indicadores anuais, Top Doadores, Maiores Candidatos, Distribuição de Receitas (Log) e Ranking Federativo (Top Estados).
  2. `Custo do Voto`: Dispersão Votos vs. Receita com Piso de Viabilidade (requer 1 Ano e 1 Cargo específico).
  3. `Porta Giratória`: Auditoria de empresas e sócios doadores que faturam como fornecedores, higienizados com malha fina textual via Regex.
  4. `Origem e Autofinanciamento`: Comparativo entre doações públicas/privadas, autofinanciamento e taxas reais de sucesso eleitoral.

---

## 🧪 5. Execução dos Testes Automatizados

A plataforma conta com uma suíte de 18 testes automatizados cobrindo pipeline, tipagem, integridade de votos, cálculos estatísticos, malha geográfica e conformidade de design.

Para executar todos os testes:

```bash
.venv/bin/python -m unittest discover tests
```

Saída esperada:
```text
Ran 18 tests in ~3.0s
OK
```
