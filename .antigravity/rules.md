# Research Context
- Academic Data Science project on Electoral Financing (TSE, QSA/Federal Revenue Service, CGU).
- Visual framework: Streamlit + Plotly.
- Performance: The dashboard consumes preprocessed data in Parquet format (`base_consolidada_eleicoes.parquet`).
- Best Practices:
  - All data-loading functions must use `@st.cache_data`.
  - Separate statistical metrics from screen rendering.
  - Prioritize interpretable visualizations (interactive Plotly with detailed hover information).
