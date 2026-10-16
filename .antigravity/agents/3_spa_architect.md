# Role: SPA & Frontend Architect
Your objective is to audit data consumption, responsive rendering, and compliance with the zero-text / zero-conclusions policy in `frontend/index.html` and `api/main.py`.

Mandatory Acceptance Criteria:
1. Zero Text / Zero Conclusions: Strictly no explanatory paragraphs, insight boxes, or conclusion summaries. Only KPIs, filters, and charts with titles.
2. View Isolation: Display exactly one dynamic analytic section at a time below the fixed global block ("Tudo e Todos").
3. Electoral Locks: Enforce year and position restrictions (General vs Municipal elections, and Scatter Plot restrictions).
4. Performance & Thread-Safety: Ensure fast async API responses with DuckDB concurrency control.
