# 📚 Dicionário de Dados: Base Consolidada de Eleições

Este documento descreve detalhadamente o esquema e as regras de negócio de cada coluna presente no arquivo canônico de dados:  
**`data/processed/base_consolidada_eleicoes.parquet`**

---

## 🗂️ Metadados do Arquivo

- **Formato:** Apache Parquet (Compressão Snappy)
- **Tamanho:** ~42.13 MB
- **Total de Linhas:** 959.770 registros de transações de receitas
- **Abrangência Temporal:** Eleições 2018, 2020, 2022 e 2024
- **Abrangência Geográfica:** 27 Unidades Federativas (26 Estados + Distrito Federal)
- **Engine de Leitura Recomendada:** DuckDB (`read_parquet`) ou PyArrow

---

## 📋 Tabela de Colunas e Especificações

| Nome da Coluna | Tipo DuckDB / Arrow | Tipo Pandas | Descrição e Regra de Negócio | Exemplo |
| :--- | :--- | :--- | :--- | :--- |
| `ano` | `VARCHAR` | `str` / `object` | Ano da eleição tratado estritamente como string para preservar a natureza categórica do pleito (`'2018'`, `'2020'`, `'2022'`, `'2024'`). | `'2024'` |
| `cpf_candidato` | `VARCHAR` | `str` / `object` | CPF do candidato padronizado com exatamente 11 dígitos numéricos (`LPAD`/`zfill(11)`), preservando zeros iniciais. | `'01234567890'` |
| `nome_candidato` | `VARCHAR` | `str` / `object` | Nome de registro do candidato junto à Justiça Eleitoral, normalizado em letras maiúsculas e sem espaços sobressalentes. | `'MARIA SILVA SANTOS'` |
| `cargo` | `VARCHAR` | `str` / `object` | Cargo disputado no pleito, normalizado em maiúsculas (ex: `PREFEITO`, `VEREADOR`, `DEPUTADO ESTADUAL`, `DEPUTADO FEDERAL`, `GOVERNADOR`, `SENADOR`, `PRESIDENTE`). | `'PREFEITO'` |
| `sigla_partido` | `VARCHAR` | `str` / `object` | Sigla da agremiação partidária do candidato no pleito, em maiúsculas. | `'PL'`, `'PT'`, `'MDB'` |
| `situacao` | `VARCHAR` | `str` / `object` | Situação final da candidatura no pleito, normalizada em minúsculas (`'eleito'`, `'não eleito'`, `'suplente'`). | `'eleito'` |
| `uf_candidato` | `VARCHAR` | `str` / `object` | Sigla oficial da Unidade Federativa da candidatura (27 UFs). | `'SP'`, `'BA'`, `'RJ'` |
| `municipio_candidato` | `VARCHAR` | `str` / `object` | Nome do município onde a eleição ocorreu. **Regra:** Preenchido para eleições municipais (2020 e 2024); mantido como `NULL` para eleições gerais estaduais/federais (2018 e 2022). | `'CAMPINA GRANDE'` |
| `id_municipio_tse_candidato`| `VARCHAR` | `str` / `object` | Código oficial numérico do município atribuído pelo TSE. Preenchido apenas para eleições municipais. | `'05053'` |
| `total_votos` | `BIGINT` | `int64` | Total consolidado de votos nominais válidos obtidos pelo candidato no pleito. Se repetido em múltiplas linhas de doação do mesmo candidato, deve ser consolidado por agregação (`max`). | `45230` |
| `cpf_cnpj_doador` | `VARCHAR` | `str` / `object` | Número de identificação do doador (CPF de pessoa física, CNPJ de partido/candidato ou Fundo Eleitoral). | `'***.456.789-**'` |
| `nome_doador` | `VARCHAR` | `str` / `object` | Razão social ou nome civil do doador registrado na prestação de contas. | `'DIRETORIO NACIONAL'` |
| `sigla_uf_doador` | `VARCHAR` | `str` / `object` | Sigla do estado de origem do doador. | `'DF'`, `'SP'` |
| `id_municipio_tse_doador` | `VARCHAR` | `str` / `object` | Código TSE do município de residência/sede do doador. | `'05053'` |
| `valor_receita` | `DOUBLE` | `float64` | Valor financeiro nominal da doação/receita registrada na transação (em Reais - R$). Não pode conter truncamento de centavos. | `50000.00` |
| `tipo_receita` | `VARCHAR` | `str` / `object` | Classificação categórica analítica da receita: `'Dinheiro Público'` (FEFC/Fundo Partidário), `'Financiamento Privado'` (Pessoas Físicas/Recursos Próprios), ou `'Repasse entre Aliados'`. | `'Dinheiro Público'` |
| `autofinanciamento` | `TINYINT` | `int8` | Flag indicando se a doação é do próprio candidato (`1` se `cpf_candidato == cpf_cnpj_doador`, `0` caso contrário). | `1` |
| `cnpj_basico` | `VARCHAR` | `str` / `object` | Raiz de 8 dígitos do CNPJ da empresa doadora ou fornecedora vinculada ao Quadro de Sócios e Administradores (QSA). `NULL` se não houver correlação societária. | `'12345678'` |
| `valor_recebido_como_fornecedor` | `DOUBLE` | `float64` | Valor recebido como fornecedor pela empresa vinculada ao doador nesta campanha (chave para auditoria de conflito de interesses / Porta Giratória). | `15000.00` |

---

## 🔍 Regras de Integridade e Validação

1. **Unicidade de Candidatos:**
   Para computar o número de candidaturas distintas, deve-se usar a chave composta `(cpf_candidato, ano, cargo)` ou `nunique('cpf_candidato')` no recorte temporal.
2. **Consolidação de Votos:**
   Como a tabela está no grão de transações de receita, somar a coluna `total_votos` diretamente duplica os votos de candidatos com múltiplos doadores. A agregação correta é agrupar por candidato e extrair o `max(total_votos)` antes de qualquer soma.
3. **Anonimização LGPD:**
   Em exibições públicas de doadores pessoas físicas, os 6 dígitos centrais do CPF devem ser mascarados (ex: `123.***.***-00`) para estrita conformidade com a Lei Geral de Proteção de Dados Pessoais.
