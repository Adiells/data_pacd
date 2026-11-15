# 🚀 Guia de Execução e Reproducibilidade

Este guia descreve como configurar o ambiente, inicializar a base de dados automaticamente via Google Drive e executar o painel **PACD** localmente.

---

## 💻 1. Pré-requisitos

- **Python:** Versão `3.10` ou superior.
- **Gerenciador de Ambientes:** `venv` ou `uv`.
- **Espaço em Disco:** ~250 MB livres para o arquivo `base_consolidada_eleicoes.parquet`.
- **Acesso à Internet (apenas na 1ª execução):** Necessário para o download automático do arquivo `.parquet` consolidado a partir do Google Drive.

---

## 📦 2. Instalação do Ambiente

No diretório `data_pacd/`, crie e ative o ambiente virtual e instale as dependências enxutas da aplicação:

### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 📥 3. Ingestão Automática da Base Parquet

**Não é necessário baixar CSVs nem rodar scripts de conversão manual.**

Ao iniciar a API (ou chamar `carregar_dados()` / `garantir_parquet_local()` em [src/data_loader.py](../src/data_loader.py)):
1. O sistema verifica `data/processed/base_consolidada_eleicoes.parquet`.
2. Se o arquivo estiver ausente, tiver menos de `1 MB` (caso comum de ponteiro Git LFS corrompido) ou falhar na checagem binária dos *magic bytes* `PAR1`, o módulo executa o download automático direto do Google Drive (`ID: 1CAUL7QTz587o0VpUkfhLBPn2EpMEHfwN`, ~224,6 MB) com gravação atômica.
3. Caso queira apontar para outro espelho no Google Drive sem alterar o código, basta definir a variável de ambiente:
   ```bash
   export PACD_PARQUET_DRIVE_ID="SEU_FILE_ID_AQUI"
   ```
4. A partir da segunda execução, a validação leva menos de 1 ms e o carregamento inicia imediatamente.

---

## 🌐 4. Iniciar a Aplicação Web (FastAPI + SPA)

Com o ambiente virtual ativado dentro de `data_pacd/`:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Após o log indicando inicialização do servidor, acesse no navegador:
- **Painel SPA:** `http://localhost:8000/`
- **Documentação Interativa (Swagger/OpenAPI):** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/health`

### Navegação Principal na SPA
- **Interruptor Global (Cabeçalho):** Alterna todo o painel entre `Todos os Recursos`, `Somente Doações` e `Elite Empresarial`.
- **Bloco Fixo Global ("Tudo e Todos"):** Exibe os 4 KPIs históricos (2018–2024) e rankings globais imunes aos filtros.
- **Barra de Filtros Dinâmicos:** Controle por Ano/Ciclo, Cargo, UF (múltipla seleção / regiões) e Partido (múltipla seleção com busca).
- **5 Abas Analíticas:**
  1. `Visão Geral`
  2. `Análise Geográfica & Fluxo de Recursos`
  3. `Custo do Voto` *(exige selecionar 1 Cargo específico)*
  4. `Teia Empresarial & Setores`
  5. `Origem dos Recursos & Autofinanciamento`

---

## 🧪 5. Execução dos Testes Automatizados

Para rodar toda a suíte de testes de integridade do `.parquet`, métricas e endpoints da API:

```bash
python -m unittest discover -s tests -v
```
