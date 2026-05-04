# ClimaCredit
**Monitor de Risco Climático para Crédito Agro**

> Projeto desenvolvido no GAS Challenge 2026.1 em parceria com a XP Inc.

## Visão geral

O ClimaCredit é um dashboard interativo que agrega dados climáticos públicos brasileiros (NOAA, NASA FIRMS, Open-Meteo ERA5, INMET) e os traduz em métricas financeiras acionáveis para mesas de Crédito Agro, Equity Agro e Commodities.

A ferramenta opera em granularidade de UF (cobertura nacional, 27 estados) e municipal (cálculo on-demand para qualquer município do país).

## Funcionalidades

A ferramenta está organizada em 6 abas:

1. **Dashboard** — Mapa nacional com ClimaRisk Score por UF + busca municipal on-demand + gauge ENSO
2. **Calendário Agrícola** — Cruzamento cultura × região × fase do ciclo, com sobreposição do risco climático atual
3. **ClimaRisk Score** — Ranking detalhado das 27 UFs, decomposição por componente, evolução histórica do ONI
4. **Alertas** — Painel de alertas diferenciado por perfil (Crédito Agro / Equity / Commodities)
5. **Tradutor Financeiro** — Sub-abas: simulação de carteira CRA/LCA com EL/HHI/stress test, mapeamento equity, decomposição de impacto em commodities
6. **Mapa por Variável** — Análise climática isolada (Precipitação, Temperatura, Queimadas, ENSO, Score Composto)

## Metodologia

### ClimaRisk Score
Score composto 0-100 calculado por:
- 35% Precipitação (anomalia vs. normais INMET 1991-2020)
- 25% ENSO (ONI × sensibilidade calibrada por UF)
- 25% Queimadas (focos normalizados por percentil histórico)
- 15% Temperatura (anomalia vs. normais)

Thresholds: NORMAL (<45), ATENÇÃO (45-69), CRÍTICO (≥70).

### Tradutor Financeiro — Crédito Agro
Framework Basel III/IFRS 9: EL = EAD × PD × LGD
- PD base: 3,1%/ano (BCB/SCR)
- Multiplicadores climáticos: NORMAL ×1,0 / ATENÇÃO ×1,5 / CRÍTICO ×2,5
- LGD: 50% (faixa típica crédito rural com garantia)
- Ajuste de concentração via HHI: stress_factor = 1 + HHI × 0,30
- Sensibilidade por cultura: 10 commodities calibradas

## Stack técnico
- Python 3.11+
- Streamlit
- pandas, numpy
- Plotly (mapas choropleth, gráficos)
- scikit-learn (BallTree haversine para vizinho mais próximo)
- yfinance, requests

## Fontes de dados

| Fonte | Instituição | Dado |
|-------|-------------|------|
| ONI | NOAA PSL | Índice ENSO mensal |
| FIRMS VIIRS SNPP | NASA | Focos de calor 7 dias |
| ERA5 | Open-Meteo | Precipitação e temperatura diárias |
| Normais 1991-2020 | INMET | Linha de base climatológica |
| Malha municipal | IBGE | Coordenadas municipais |
| PTAX | BCB | Câmbio USD/BRL |
| Futuros CBOT/ICE | yfinance | Proxies de preço |

## Como rodar localmente

\`\`\`bash
git clone https://github.com/SEU_USUARIO/climacredit.git
cd climacredit
pip install -r requirements.txt
streamlit run app.py
\`\`\`

O app abre automaticamente em http://localhost:8501.

## Estrutura do projeto

\`\`\`
climacredit/
├── app.py                    # Aplicação Streamlit principal (6 abas)
├── scripts/                  # Coleta e processamento de dados
│   ├── enso_noaa.py          # ONI da NOAA
│   ├── queimadas_inpe.py     # Focos NASA FIRMS
│   ├── inmet_anomalia.py     # Anomalia ERA5 vs. normais INMET
│   ├── score_ufs.py          # Score por UF (27 estados)
│   └── score.py              # Score regional (5 grandes regiões)
├── data/                     # CSVs gerados pelos scripts
├── docs/                     # Script gerador de relatório técnico
├── .streamlit/               # Configuração do tema dark
└── requirements.txt
\`\`\`

## Aderência regulatória
- BCB Resolução 139/2021 (gerenciamento de risco climático)
- TCFD (Task Force on Climate-related Financial Disclosures)
- NGFS (Network for Greening the Financial System)

## Mentor
**João Gabriel Amarante** — Head de Estudos Energéticos, XP Global Markets

## Licença
Projeto acadêmico desenvolvido no contexto do GAS Challenge 2026.1.
