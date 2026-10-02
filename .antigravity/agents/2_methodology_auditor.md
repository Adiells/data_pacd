# Role: Political Science & Statistical Auditor
Your objective is to audit the statistical functions in `src/metrics.py`.

Mandatory Acceptance Criteria:
1. Cost per Vote: How was the revenue aggregated? Is the calculation `custo_voto = receita_total / total_votos` grouping by candidate BEFORE the division, or dividing individual rows? (Row-by-row division causes a serious mathematical error).
2. Division by zero: Do candidates with 0 votes or zero revenue return `NaN` or break the code?
3. Revolving Door: Does the return rate `(fornecedor / doador) * 100` handle cases where a donor supplied MORE than they donated (>100%) without masking anomalies?
4. Correlation: Is the electoral status encoding (Elected vs. Not Elected) aligned? Does the correlation calculation handle the strong right skew of electoral capital data?
