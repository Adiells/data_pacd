# 🔬 Metodologia Científica e Regras de Negócio

Este documento descreve o arcabouço metodológico, as hipóteses teóricas investigadas e as regras de negócio consolidadas a partir do documento oficial de especificação (`Resumo_Colunas_Tabela_FInal.pdf`) da base de dados eleitorais.

---

## 🎯 1. Hipóteses Científicas Investigadas

### Hipótese H1: O Teto de Vidro Financeiro (Piso de Viabilidade)
> *"Existe um custo por voto mínimo e um piso empírico de capital financeiro abaixo do qual a viabilidade eleitoral para cargos majoritários e proporcionais é estatisticamente nula."*

- **Formalização Matemática:**  
  $$Custo\_Voto_i = \frac{\sum Receitas_i}{Total\_Votos_i}$$
- **Piso Empírico de Viabilidade:**
  $$Piso_{cargo, ano} = \min \{ \text{Receita}_k \mid k \in \text{Eleitos}, \text{Receita}_k > 0 \}$$
- **Critério de Validação Estatística:**
  - Aplica-se o teste não-paramétrico de **Mann-Whitney U** para testar se a distribuição de receitas dos candidatos eleitos é estocasticamente superior à dos não eleitos ($H_0: \text{Receita}_{eleito} \leq \text{Receita}_{nao\_eleito}$; $H_1: \text{Receita}_{eleito} > \text{Receita}_{nao\_eleito}$).
  - Verifica-se se a proporção de candidatos eleitos com receita inferior ao $Piso_{cargo, ano}$ é estatisticamente igual a zero.

---

### Hipótese H2: O Circuito da Porta Giratória (Doador $\rightarrow$ Fornecedor)
> *"O veto formal a doações empresariais (ADI 4650 do STF) é contornado por meio da triangulação entre doações de pessoas físicas e a contratação de empresas ligadas ao seu Quadro de Sócios e Administradores (QSA)."*

- **Mapeamento de Vínculo:**
  Conexão entre o `cpf_cnpj_doador` (Pessoa Física) e as empresas prestadoras de serviços da campanha através da raiz cadastral de 8 dígitos (`cnpj_basico`).
- **Taxa de Retorno Financeiro:**
  $$Taxa\_Retorno (\%) = \left( \frac{\text{Valor Recebido como Fornecedor}}{\text{Valor Doado}} \right) \times 100$$
- **Saldo Líquido da Operação:**
  $$Saldo\_Liquido = \text{Valor Recebido como Fornecedor} - \text{Valor Doado}$$
- **Critério de Auditoria:**
  Identificação de casos em que a taxa de retorno supera 100%, caracterizando um cenário em que a doação serviu como porta de entrada comercial para a obtenção de contratos de campanha lucrativos.

---

## 📐 2. Regras de Negócio e Tratamento de Dados (TSE & CGU)

Conforme as diretrizes especificadas em `Resumo_Colunas_Tabela_FInal.pdf`:

### 2.1. Tipagem e Preservação de Identificadores
- **`ano` (String/VARCHAR):**  
  O ano não deve ser operado como número contínuo, mas como dimensão categórica discreta (`'2018'`, `'2020'`, `'2022'`, `'2024'`), evitando médias temporais aritmeticamente espúrias.
- **`cpf_candidato` (LPAD 11 dígitos):**  
  CPFs iniciados com zero devem obrigatoriamente manter o comprimento de 11 dígitos via `zfill(11)` para evitar perda de dígitos e quebra de integridade referencial.
- **`cnpj_basico` (8 dígitos):**  
  Raiz cadastral limpa sem caracteres especiais, correspondente aos primeiros 8 dígitos do CNPJ, permitindo junção direta com a base do QSA da Receita Federal.
- **Valores Monetários (`valor_receita` e `valor_recebido_como_fornecedor`):**  
  Parsing estrito do padrão monetário brasileiro (`1.234,56` $\rightarrow$ `1234.56`), sem truncamento de centavos nem multiplicação por 100.

### 2.2. Tratamento Geográfico por Escopo do Pleito
- **Eleições Gerais (2018 e 2022):**  
  Disputas para Presidente, Senador, Governador, Deputado Federal e Deputado Estadual ocorrem no escopo estadual ou nacional. Portanto, as colunas `municipio_candidato` e `id_municipio_tse_candidato` são estruturalmente mantidas como `NULL` / vazias.
- **Eleições Municipais (2020 e 2024):**  
  Disputas para Prefeito e Vereador ocorrem no escopo do município. O preenchimento de `municipio_candidato` e `id_municipio_tse_candidato` é de 100%.

### 2.3. Tipologia de Fontes de Financiamento (`tipo_receita`)
As receitas são classificadas em três grandes categorias analíticas:
1. **Dinheiro Público:**
   - Fundo Especial de Financiamento de Campanha (FEFC)
   - Fundo Especial de Assistência Financeira aos Partidos Políticos (Fundo Partidário)
2. **Financiamento Privado:**
   - Doações financeiras de pessoas físicas
   - Autofinanciamento (aportes do próprio candidato à sua campanha)
   - Doações estimáveis em dinheiro (serviços ou cessão de bens)
3. **Repasse entre Aliados:**
   - Recursos repassados por outros candidatos ou comitês financeiros da mesma coligação partidária.

### 2.4. Detecção de Autofinanciamento (`autofinanciamento`)
- Flag binária calculada como:
  $$\text{autofinanciamento} = \begin{cases} 1, & \text{se } \text{cpf\_candidato} == \text{cpf\_cnpj\_doador} \\ 0, & \text{caso contrário} \end{cases}$$
- Permite analisar o impacto do capital patrimonial pessoal do candidato em suas chances reais de vitória eleitoral.

---

## 🎨 3. Padrões de Visualização de Dados (Data Visualization Guidelines)

O projeto adota regras estritas de design analítico para evitar distorções de percepção:

1. **Proibição de Gráficos de Pizza (`pie plot`) e Rosca (`donut plot`):**  
   O olho humano possui baixa precisão para julgar ângulos e áreas em 2D. Todas as partições de recursos utilizam **gráficos de barras horizontais ordenadas** (`px.bar(..., orientation='h')`) com percentuais e valores nominais explícitos no final de cada barra.
2. **Escala Logarítmica para Variáveis Financeiras:**  
   Como a distribuição de capital de campanha é hiperconcentrada (seguindo uma distribuição de cauda pesada / Pareto), histogramas e gráficos de dispersão utilizam escala logarítmica para visualização legível de ordens de magnitude.
3. **Mapas Coropléticos Federativos (Heatmaps):**  
   Apresentação geoespacial das 27 UFs com escalas sequenciais de alta legibilidade (`YlOrRd`, `Blues`, `Greens`, `Purples`) e limites territoriais pré-ajustados (`fitbounds='locations'`).
