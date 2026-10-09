# 🚀 Guia de Execução e Reproducibilidade

Este guia passo a passo explica como configurar o ambiente, executar os scripts de ingestão de dados, rodar a suíte de testes e iniciar a aplicação web.

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

## 🌐 4. Iniciar a Aplicação Web Streamlit

Para iniciar o dashboard analítico:

```bash
.venv/bin/streamlit run app.py
```

A aplicação abrirá automaticamente no navegador no endereço:  
**`http://localhost:8501`**

### Dicas de Navegação:
- A aplicação inicia por padrão na **Visão Nacional ("Todas as UFs / Brasil")**.
- Utilize a barra lateral à esquerda para filtrar por **Ano**, **Cargo**, **Partido** ou isolar uma **UF específica**.
- Alterne entre as 4 páginas de análise no menu lateral do Streamlit:
  1. `1_visao_geral`: KPIs nacionais, Mapa de Calor (Heatmap do Brasil), rankings e histograma de assimetria.
  2. `2_custo_do_voto`: Análise do custo por voto, dispersão log-log e validação estatística da Hipótese H1 (Mann-Whitney U).
  3. `3_porta_giratoria`: Auditoria de doadores que figuram como fornecedores via QSA (Hipótese H2) e diagrama Sankey.
  4. `4_origem_e_autofinanciamento`: Evolução das fontes (público vs privado) e impacto do autofinanciamento.

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
