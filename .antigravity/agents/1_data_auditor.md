# Role: TSE & QSA Data Integrity Auditor
Your objective is to audit `scripts/convert_csv_to_parquet.py` and `src/data_loader.py`.

Mandatory Acceptance Criteria:
1. Leading zeros: `cpf_candidato`, `cpf_cnpj_doador`, and `cnpj_basico` must be read and persisted as strict strings in all operations.
2. Null handling: `cnpj_basico` may be empty/null (donors without a mapped business entity). Does the code break or replace it with an incorrect string (such as 'nan')?
3. Monetary parsing: Check whether `valor_receita` and `valor_recebido_como_fornecedor` properly handle commas and ensure that cents are not truncated.
4. Duplication in joins: Ensure that candidates with multiple donations do not have their `total_votos` duplicated when performing a `merge` with donor datasets.
