# 🔬 Metodologia Científica e Regras de Negócio

Este documento consolida as hipóteses investigativas, os critérios de integridade contábil e as regras de visualização da plataforma **PACD (Pesquisa Aplicada em Ciência de Dados)** sobre o financiamento eleitoral brasileiro pós-ADI 4650 (2018–2024).

---

## 🎯 1. Eixos e Hipóteses Investigadas

### Eixo 1: Concentração de Capital e Piso de Viabilidade Eleitoral
> *"Os recursos eleitorais seguem uma distribuição de cauda pesada, existindo um patamar financeiro mínimo (piso de viabilidade) e um diferencial significativo na taxa de vitória entre o decil superior e a base menos financiada."*

- **Custo do Voto:**
  $$Custo\_Voto_i = \frac{\sum Receitas_i}{\max(Total\_Votos_i)}$$
- **Piso Empírico de Viabilidade:**
  $$Piso = \min \{ \text{Receita}_k \mid k \in \text{Eleitos}, \text{Receita}_k > 0 \}$$
- **Diferencial Top 10% vs. Bottom 50%:** Calculado pela função `calcular_sucesso_decil()` em [src/metrics.py](../src/metrics.py), comparando a taxa de eleição das candidaturas no decil mais financiado contra a metade inferior no mesmo recorte.

### Eixo 2: Operação da Elite Empresarial Pós-ADI 4650
> *"Mesmo após o veto a doações diretas de Pessoas Jurídicas pelo STF, redes corporativas continuam influenciando disputas eleitorais por meio de doações de Pessoas Físicas vinculadas ao Quadro de Sócios e Administradores (QSA/RFB)."*

- **Identificação da Elite (`is_empresario`):** Cruzamento entre o `cpf_cnpj_doador` (quando `is_cpf = TRUE`) e a base de sócios/administradores de empresas ativas da Receita Federal, vinculando `cnpj_basico`, `razao_social`, `setor_economico` (CNAE/IBGE) e `uf_empresa`.
- **Visão Consolidada na Teia Empresarial:** As gavetas sanfona agrupam todas as transferências na relação única **`(Sócio ➔ Candidato)`**, exibindo a contagem de **Transações** e o **Montante Acumulado**.

### Eixo 3: Fluxos Federativos e Rotas de Influência Interestadual
> *"A sede matriz da empresa ligada ao sócio doador (`uf_empresa`) permite rastrear fluxos financeiros interestaduais mesmo quando o domicílio da Pessoa Física (`sigla_uf_doador`) está protegido por sigilo/LGPD."*

- Rastreia repasses em que a UF de origem (`uf_empresa` / `sigla_uf_doador` / `sede_doadores`) difere de `uf_candidato`.
- Em disputas presidenciais (`cargo = 'PRESIDENTE'`), o mapa federativo exibe a origem estadual dos recursos e a tabela interestadual mapeia os fluxos para o escopo nacional `'BR'`.

---

## 📐 2. Regras de Integridade, Travas e Saneamento

### 2.1. Blindagem Contábil de Candidaturas
- Todas as agregações dinâmicas por candidato utilizam a chave composta **`(ano, cpf_candidato, cargo)`** (e `sequencial_candidato` no bloco global), evitando que o mesmo CPF em eleições diferentes (ex.: 2018 e 2022) ou cargos diferentes tenha receitas somadas indevidamente ou seus votos duplicados.

### 2.2. Travas Constitucionais de Filtro
- **Eleições Gerais (2018 e 2022):** Restritas a *Presidente*, *Governador*, *Senador*, *Deputado Federal*, *Deputado Estadual* e *Deputado Distrital*.
- **Eleições Municipais (2020 e 2024):** Restritas a *Prefeito* e *Vereador*.
- **Art. 32 da CF/88 (Distrito Federal):** Bloqueio automático de cargos municipais (*Prefeito* e *Vereador*) quando apenas `DF` está selecionado.
- **Trava do Custo do Voto:** Exige obrigatoriamente a seleção de **1 Cargo específico** para evitar distorções de escala entre disputas proporcionais e majoritárias.
- **Adaptação do Gráfico de Partidos:**
  - Múltiplos partidos selecionados ➔ exibe *Top Partidos*.
  - 1 Partido específico com múltiplas UFs ➔ adapta para *Distribuição por Estado das Candidaturas*.
  - 1 Partido + 1 UF + 1 Cargo específico ➔ oculta o gráfico redundante (`modo_grafico_partidos = 'oculto'`).

### 2.3. Classificação de Recursos e Filtro de Crowdfunding
- **Interruptor Global em 3 Fases:**
  - `todos`: Base completa.
  - `privado` (*Somente Doações*): `tipo_receita = 'Financiamento Privado'`.
  - `elite` (*Elite Empresarial*): `tipo_receita = 'Financiamento Privado' AND is_empresario = TRUE`.
- **Higienização de Intermediários (`REGEX_CROWD`):** Nos rankings de maiores doadores e sócios financiadores, plataformas de arrecadação coletiva (vaquinha/crowdfunding) e intermediários de pagamento são filtrados para não mascararem os financiadores finais.

### 2.4. Auditoria de Qualidade e Saneamento Cirúrgico (SPCE/TSE)
Na camada analítica (`VIEW eleicoes` em [api/main.py](../api/main.py)), dois erros extremos de digitação autodeclarados no sistema SPCE/TSE são saneados cirurgicamente para preservar a fidelidade estatística:
1. **Outlier do Amazonas (2020):** Rateio de material gráfico estimado de R$ 2.486,00 entre 12 vereadores do Republicanos no AM (R$ 207,17 cada) lançado sem pontuação decimal como R$ 207.166.666,66 por candidato (`cpf_cnpj_doador = '38121911000140'` com valor `> 200.000.000`). Saneado para **R$ 207,17**.
2. **Outlier de Salvador/BA (2024):** Lançamento autodeclarado de R$ 1.250.125.000,00 para candidatura a vereador (`cpf_cnpj_doador = '16068108000156'`). Saneado para **R$ 1.250,00**.

### 2.5. Legislação e LGPD
- **Autofinanciamento (Lei nº 13.877/2019):** A partir das eleições de 2020, o uso de recursos próprios passou a ser limitado a 10% do teto de gastos do cargo — explicando por que o recorde histórico de 2018 (R$ 57,03 milhões) não se repete nos ciclos seguintes.
- **Sigilo de Pessoas Físicas:** Em respeito à legislação eleitoral e à LGPD, endereços/UFs de doadores pessoas físicas frequentemente não constam nos registros públicos (`sigla_uf_doador`).

---

## 🎨 3. Padrões de Visualização de Dados

1. **Ausência de Gráficos Circulares:** Proibição de gráficos de pizza (`pie`) e rosca (`doughnut`), priorizando gráficos de barras ordenadas (mais precisos para comparação quantitativa).
2. **Escala Logarítmica para Assimetria Financeira:** Utilizada no histograma de distribuição de receitas para representar ordens de grandeza em distribuições de cauda pesada.
3. **Cartograma Grid 8×8:** Representação uniforme das 27 UFs no mapa de calor para evitar que estados de grande área territorial (como AM ou PA) dominem visualmente sobre estados populosos de menor extensão (como RJ ou DF).
