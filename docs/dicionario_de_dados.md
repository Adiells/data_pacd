# 📚 Dicionário de Dados: Base Consolidada de Eleições (2018–2024)

Este documento descreve o esquema oficial das colunas presentes no arquivo colunar:  
**`data/processed/base_consolidada_eleicoes.parquet`**

---

## 🗂️ Metadados do Arquivo

- **Formato:** Apache Parquet
- **Tamanho em Disco:** `235.485.013 bytes` (~224,6 MB)
- **Total de Registros:** **5.310.738** transações de receitas eleitorais enriquecidas
- **Abrangência Temporal:** Eleições de **2018, 2020, 2022 e 2024**
- **Abrangência Geográfica:** 27 Unidades Federativas + `'BR'` (disputas presidenciais)
- **Fontes Integradas:** Prestação de Contas e Resultados do **TSE** cruzados com o Quadro de Sócios e Administradores (**QSA / Receita Federal**)
- **Origem de Download Automático:** Google Drive (`ID: 1CAUL7QTz587o0VpUkfhLBPn2EpMEHfwN`)

---

## 📋 Colunas Físicas do Parquet (24 Colunas)

| # | Nome da Coluna | Tipo DuckDB / Parquet | Descrição e Regra de Negócio |
| :-: | :--- | :--- | :--- |
| 1 | `ano` | `BIGINT` | Ano do pleito eleitoral (`2018`, `2020`, `2022` ou `2024`). |
| 2 | `sequencial_candidato` | `VARCHAR` | Identificador único da candidatura atribuído pelo TSE em cada eleição/cargo. |
| 3 | `cpf_candidato` | `VARCHAR` | CPF do candidato preservando zeros à esquerda (11 dígitos). Na `VIEW eleicoes`, recebe fallback para `sequencial_candidato` caso esteja vazio. |
| 4 | `nome_candidato` | `VARCHAR` | Nome de urna oficial do candidato no TSE. |
| 5 | `cargo` | `VARCHAR` | Cargo disputado, saneado e sem nulos (`PRESIDENTE`, `GOVERNADOR`, `SENADOR`, `DEPUTADO FEDERAL`, `DEPUTADO ESTADUAL`, `DEPUTADO DISTRITAL`, `PREFEITO`, `VEREADOR`). |
| 6 | `sigla_partido` | `VARCHAR` | Sigla do partido político da candidatura no pleito. |
| 7 | `situacao` | `VARCHAR` | Situação final da candidatura registrada pela Justiça Eleitoral. |
| 8 | `uf_candidato` | `VARCHAR` | Sigla da UF da disputa eleitoral (`AC` a `TO`, ou `'BR'` para Presidente). |
| 9 | `total_votos` | `BIGINT` | Total consolidado de votos nominais obtidos nas urnas pelo candidato na respectiva candidatura. Como a tabela está no grão transacional, agregações por candidato devem usar `MAX(total_votos)`. |
| 10 | `valor_receita` | `DOUBLE` | Montante nominal (em R$) transferido na transação de receita. |
| 11 | `origem_receita` | `VARCHAR` | Origem contábil da receita conforme prestação de contas no SPCE/TSE (ex.: Fundo Especial, Fundo Partidário, Recursos de Pessoas Físicas, Recursos Próprios, etc.). |
| 12 | `fonte_receita` | `VARCHAR` | Classificação de fonte informada no SPCE/TSE (ex.: Fundo Partidário, Outros Recursos). |
| 13 | `especie_receita` | `VARCHAR` | Modalidade/espécie do repasse (financeira, estimável em dinheiro, transferência eletrônica, etc.). |
| 14 | `nome_doador` | `VARCHAR` | Razão social (quando fundo/órgão/partido) ou nome civil do doador registrado no TSE. |
| 15 | `sigla_uf_doador` | `VARCHAR` | UF declarada pelo doador no TSE (frequentemente omissa para pessoas físicas devido a regras de privacidade/LGPD). |
| 16 | `cpf_cnpj_doador` | `VARCHAR` | Documento identificador do doador (CPF ou CNPJ). |
| 17 | `is_cpf` | `BOOLEAN` | `TRUE` se o doador é Pessoa Física (CPF); `FALSE` caso contrário. |
| 18 | `autofinanciamento` | `BIGINT` | Indicador binário (`1` = doação do próprio candidato à sua campanha; `0` = recursos de terceiros/fundos). |
| 19 | `cnpj_basico` | `VARCHAR` | Raiz cadastral de 8 dígitos do CNPJ da empresa vinculada ao doador na Receita Federal (`NULL` quando não há vínculo empresarial). |
| 20 | `is_empresario` | `BOOLEAN` | **Feature PACD:** `TRUE` quando o doador Pessoa Física foi identificado como sócio, proprietário ou administrador de empresa ativa no QSA da Receita Federal. |
| 21 | `is_eleito` | `BOOLEAN` | **Feature PACD:** `TRUE` se o candidato foi formalmente eleito no pleito segundo gabarito oficial do TSE. |
| 22 | `razao_social` | `VARCHAR` | Nome empresarial oficial da companhia vinculada na Receita Federal. |
| 23 | `setor_economico` | `VARCHAR` | Descrição da atividade econômica principal (CNAE / IBGE) da empresa vinculada. |
| 24 | `uf_empresa` | `VARCHAR` | UF oficial da sede/matriz da empresa na Receita Federal (chave central para rastreamento de **Rotas de Influência Interestadual**). |

---

## ⚙️ Colunas Derivadas na Camada DuckDB (`VIEW eleicoes`)

No startup do servidor em [api/main.py](../api/main.py), a view `eleicoes` expõe os dados aplicando:

- **`valor_receita` (saneado):** Corrige dois erros extremos de digitação autodeclarados no SPCE/TSE:
  - Transações do CNPJ `38121911000140` acima de R$ 200 milhões (AM/2020) ajustadas para `207.17`.
  - Transação do CNPJ `16068108000156` igual a R$ 1.250.125.000,00 (Salvador/2024) ajustada para `1250.00`.
- **`tipo_receita`:** Classificação em 3 categorias a partir de `origem_receita` e `autofinanciamento`:
  - `'Financiamento Privado'` (`recursos de pessoas fisicas`, `recursos proprios`, `recursos de financiamento coletivo`, `doacoes pela internet`, `comercializacao de bens ou realizacao de eventos` ou `autofinanciamento = 1`);
  - `'Repasse entre Aliados'` (`recursos de outros candidatos`);
  - `'Dinheiro Público'` (demais origens, incluindo FEFC e Fundo Partidário).

---

## 🔍 Regras de Integridade e Unicidade

1. **Blindagem de Candidatura:** Contagens e agregações por candidato utilizam a chave composta `(ano, cpf_candidato, cargo)` (ou `sequencial_candidato` no recorte global), evitando que o mesmo político disputando cargos ou eleições distintas tenha seus votos ou receitas mesclados.
2. **Consolidação de Votos:** Em bases no grão de transação, votos nunca devem ser somados diretamente; agrega-se primeiro por candidatura usando `MAX(total_votos)`.
3. **Resolução de Domicílio do Doador:** Na ausência de `sigla_uf_doador`, as consultas utilizam em cascata `uf_empresa`, a tabela materializada `sede_doadores` e regras de consistência federativa descritas na metodologia.
