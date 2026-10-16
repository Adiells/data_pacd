# Research Context
- Academic Data Science project on Electoral Financing (TSE, QSA/Federal Revenue Service, CGU).
- Visual framework: Single-Page Application (SPA) with React 18, TailwindCSS, Chart.js, and FastAPI backend.
- Performance: DuckDB SQL queries over Parquet format (`base_consolidada_eleicoes.parquet`) with thread-safe query locking.
- Best Practices:
  - Zero-text and zero-conclusions policy: only KPIs, filters, and charts with titles.
  - Strict electoral rules and locks (General 2018/2022 vs Municipal 2020/2024, Custo do Voto requires 1 Year + 1 Position).
  - Malha fina textual via Regex to isolate purely private contributions in Porta Giratória.
