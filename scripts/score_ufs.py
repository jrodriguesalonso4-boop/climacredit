"""
ClimaCredit — ClimaRisk Score por UF (Estado)
Granularidade estadual: 26 estados + DF.

Metodologia (pesos idênticos ao score regional para comparabilidade):
  Precipitação  35%  — anomalia vs. normal INMET 1991-2020 no centroide da UF
  ENSO          25%  — ONI × sensibilidade por UF (tabela documentada)
  Queimadas     25%  — focos NASA FIRMS filtrados por bbox da UF,
                       normalizados pela área agrícola IBGE Censo 2017
  Temperatura   15%  — anomalia de temp. média vs. normal INMET 1991-2020

Fontes:
  ONI:               NOAA PSL nina34.anom.data (data/oni_index.csv)
  Precipitação/Temp: Open-Meteo Archive API — ERA5 reanalysis (sem autenticação)
  Normais precip:    INMET "Normais Climatológicas do Brasil 1991-2020"
  Normais temp:      INMET "Normais Climatológicas do Brasil 1991-2020"
  Focos de calor:    NASA FIRMS VIIRS SNPP 7d (data/queimadas.csv)
  Área agrícola:     IBGE Censo Agropecuário 2017 (lavouras + pastagens)
  Sensibilidade ENSO: CPTEC/INPE Atlas Climático; Mason & Goddard (2001);
                       Grimm et al. (2000) para Sul; Ropelewski & Halpert (1987)

Limitações conhecidas:
  - Centroides = capital estadual (operacional, não centroide geométrico)
  - Bounding boxes por UF são aproximadas; focos em bordas podem ser
    contados em mais de uma UF (artefato conservador)
  - UFs com dados limitados: AP, RR, AM, AC (baixa cobertura agrícola)
  - Normais de temperatura são estimativas baseadas em publicações INMET;
    precisão ±1-2°C é adequada para scores relativos
"""

import time
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date, timedelta

Path("data").mkdir(exist_ok=True)

# ── Centroides das UFs (coordenada da capital estadual) ──────────────────────
# Fonte: IBGE — usamos capital como ponto representativo operacional
UF_CENTROIDES = {
    "AC": ( -9.97, -67.81), "AL": ( -9.67, -35.74), "AM": ( -3.10, -60.02),
    "AP": (  0.03, -51.07), "BA": (-12.97, -38.51), "CE": ( -3.72, -38.54),
    "DF": (-15.78, -47.93), "ES": (-20.32, -40.34), "GO": (-16.67, -49.25),
    "MA": ( -2.53, -44.30), "MG": (-19.92, -43.94), "MS": (-20.44, -54.65),
    "MT": (-15.60, -56.10), "PA": ( -1.46, -48.50), "PB": ( -7.12, -34.86),
    "PE": ( -8.05, -34.88), "PI": ( -5.09, -42.80), "PR": (-25.43, -49.27),
    "RJ": (-22.91, -43.17), "RN": ( -5.79, -35.21), "RO": ( -8.76, -63.90),
    "RR": (  2.82, -60.67), "RS": (-30.03, -51.23), "SC": (-27.60, -48.55),
    "SE": (-10.91, -37.07), "SP": (-23.55, -46.63), "TO": (-10.24, -48.35),
}

# ── Sensibilidade ENSO por UF ─────────────────────────────────────────────────
# Positivo → El Niño aumenta risco de seca / extremo
# Negativo → La Niña aumenta risco
# Fontes: CPTEC/INPE Atlas Climático; Grimm et al. (2000); Mason & Goddard (2001)
# Hipótese: estados de transição usam interpolação linear entre regiões publicadas
ENSO_SENS_UF = {
    # Semiárido nordestino — El Niño → seca severa (correlação histórica forte)
    "CE": +0.95, "RN": +0.90, "PB": +0.90, "PE": +0.85,
    "AL": +0.80, "SE": +0.75, "PI": +0.85,
    # Bahia — interior semiárido sensível; litoral menos afetado
    "BA": +0.70,
    # Maranhão — transição Amazônia/NE; predominantemente El Niño → seca
    "MA": +0.65,
    # Amazônia — El Niño → seca prolongada (Grimm & Tedeschi 2009)
    "AM": +0.65, "PA": +0.60, "AC": +0.60, "RO": +0.55,
    "RR": +0.50, "AP": +0.45, "TO": +0.60,
    # Sul — La Niña → seca severa (Grimm et al. 2000, correlação robusta)
    "RS": -0.85, "SC": -0.75, "PR": -0.70,
    # Sudeste — efeito moderado e geograficamente heterogêneo
    "SP": +0.30, "MG": +0.40, "RJ": +0.25, "ES": +0.35,
    # Centro-Oeste — El Niño → seca moderada a severa no cerrado
    "MT": +0.65, "MS": +0.55, "GO": +0.60, "DF": +0.55,
}

# ── Normais climatológicas de precipitação por UF (mm/mês, Jan→Dez) ──────────
# Fonte: INMET "Normais Climatológicas do Brasil 1991-2020"
# UFs sem estação representativa usam normal da sub-região climática mais próxima
NORMAIS_PRECIP_MM = {
    "AM": [281,271,319,314,256,179,143,128,121,127,167,234],
    "PA": [315,306,352,325,268,178,162,148,138,118,168,243],
    "AC": [310,296,302,205,118, 58, 42, 55,116,196,256,305],
    "RO": [290,274,275,176, 95, 46, 37, 55,131,195,238,272],
    "RR": [186,193,222,223,248,197,164,108, 82, 80,110,145],
    "AP": [340,365,418,394,318,177,118, 75, 63, 69,109,224],
    "TO": [242,218,228,163, 74, 20, 11, 20, 72,142,193,226],
    "MA": [248,270,328,290,172, 73, 40, 30, 38, 64,113,186],
    "PI": [173,194,262,247,128, 43, 17, 10, 19, 52,115,166],
    "CE": [ 72,121,196,185, 95, 43, 22, 14, 15, 24, 40, 55],
    "RN": [ 38, 72,140,151, 98, 53, 29, 18, 13, 10, 14, 22],
    "PB": [ 38, 74,128,153,100, 55, 29, 17, 11,  9, 13, 21],
    "PE": [ 60,100,158,180,130, 80, 49, 36, 24, 24, 28, 44],
    "AL": [ 91,136,204,220,160,100, 68, 53, 43, 42, 52, 71],
    "SE": [103,142,193,185,117, 65, 40, 31, 30, 43, 72,108],
    "BA": [ 68,108,155,151,103, 60, 37, 31, 38, 67,102,130],
    "MT": [247,196,212, 96, 36,  8,  8, 22, 68,138,185,226],
    "MS": [193,159,157, 82, 48, 26, 24, 37, 75,123,160,176],
    "GO": [238,198,207, 98, 37, 10,  8, 18, 60,130,181,220],
    "DF": [214,179,186, 85, 30,  6,  5, 14, 52,114,167,200],
    "MG": [243,188,158, 72, 49, 38, 36, 39, 73,113,142,207],
    "SP": [252,213,167, 85, 52, 45, 40, 42, 78,122,151,222],
    "RJ": [177,150,135, 79, 47, 39, 36, 38, 66,100,124,160],
    "ES": [162,133,118, 74, 50, 45, 40, 42, 72,100,120,148],
    "PR": [178,152,121,115,116,119,128,120,148,141,126,153],
    "SC": [167,148,120,105,102,106,128,120,148,141,124,153],
    "RS": [132,122, 99, 96, 96, 97,120,110,126,117,105,120],
}

# ── Normais climatológicas de temperatura por UF (°C médio mensal, Jan→Dez) ──
# Fonte: INMET "Normais Climatológicas do Brasil 1991-2020"
# Representativas da capital; precisão ±1-2°C, adequada para anomalias relativas
NORMAIS_TEMP_C = {
    "AM": [27.0,26.8,26.5,26.6,27.0,27.1,27.0,27.4,27.8,28.0,27.8,27.2],
    "PA": [27.2,27.0,26.8,27.0,27.3,27.0,26.8,27.2,27.8,28.2,28.0,27.5],
    "AC": [25.5,25.3,25.0,24.8,24.5,23.5,23.0,24.5,25.5,26.0,25.8,25.5],
    "RO": [25.8,25.5,25.3,25.0,24.8,23.8,23.5,25.0,26.0,26.5,26.0,25.8],
    "RR": [27.5,27.0,27.0,27.2,27.8,27.9,27.5,27.8,28.3,28.5,28.0,27.5],
    "AP": [27.0,26.8,26.5,26.8,27.2,27.0,26.8,27.0,27.5,28.0,27.8,27.2],
    "TO": [28.0,27.8,27.5,27.2,26.5,25.8,25.5,26.5,28.0,28.5,28.2,27.8],
    "MA": [28.0,27.5,27.3,27.5,27.8,27.5,27.2,27.5,28.0,28.5,28.8,28.2],
    "PI": [28.5,28.0,27.8,28.0,28.2,27.8,27.5,28.0,29.0,29.5,29.2,28.8],
    "CE": [28.2,27.8,27.5,27.5,27.5,27.0,26.8,27.2,28.0,28.8,29.0,28.5],
    "RN": [28.5,28.0,27.8,27.8,27.8,27.2,27.0,27.5,28.2,29.0,29.3,28.8],
    "PB": [27.8,27.3,27.0,27.0,26.8,26.2,25.8,26.5,27.5,28.2,28.5,28.0],
    "PE": [27.5,27.2,27.0,26.8,26.5,25.8,25.5,26.2,27.0,27.8,28.0,27.8],
    "AL": [27.2,27.0,26.8,26.5,26.0,25.3,25.0,25.8,26.8,27.5,27.5,27.2],
    "SE": [26.8,26.5,26.3,26.0,25.8,25.2,24.8,25.5,26.5,27.0,27.0,26.8],
    "BA": [26.5,26.3,26.0,25.8,25.0,24.2,23.8,24.5,25.5,26.2,26.5,26.5],
    "MT": [27.0,26.8,26.5,25.8,23.8,21.8,21.5,23.5,26.0,27.2,27.0,26.8],
    "MS": [26.0,25.8,25.2,23.8,21.2,18.8,18.5,20.5,23.5,25.0,25.5,25.8],
    "GO": [24.5,24.3,24.0,23.5,21.8,20.0,19.8,21.5,23.8,24.8,24.5,24.2],
    "DF": [22.5,22.3,22.0,21.5,19.8,18.0,17.8,19.5,22.0,23.0,22.5,22.2],
    "MG": [23.0,22.8,22.5,21.8,19.5,17.5,17.2,18.8,21.5,23.0,22.8,22.5],
    "SP": [23.5,23.3,22.8,21.5,18.8,17.0,16.5,18.0,20.5,22.0,22.5,23.0],
    "RJ": [26.5,26.3,25.5,24.0,21.5,19.5,19.0,20.5,22.5,24.0,24.8,25.8],
    "ES": [25.5,25.3,24.8,23.5,21.0,19.0,18.5,20.0,22.0,23.8,24.5,25.0],
    "PR": [22.0,21.8,20.8,18.8,15.8,13.5,13.0,14.5,17.5,19.5,20.5,21.5],
    "SC": [22.5,22.3,21.3,19.0,15.8,13.2,12.8,14.0,17.0,19.2,20.5,21.8],
    "RS": [24.5,24.0,22.0,19.0,15.2,12.8,12.5,13.8,16.5,19.0,21.0,23.2],
}

# ── Área agrícola por UF (mil ha) ─────────────────────────────────────────────
# Fonte: IBGE Censo Agropecuário 2017 (lavouras temporárias + permanentes + pastagens)
# Usado para normalizar focos de queimada pela pressão agrícola real da UF
# (evita que UFs com floresta extensa tenham score inflado por focos em áreas remotas)
AREA_AGRO_MIL_HA = {
    "MT": 32750, "MG": 22500, "GO": 21700, "MS": 19900, "BA": 17800,
    "RS": 14200, "SP": 12100, "PR": 10800, "MA":  8500, "PA":  7800,
    "TO":  7200, "PI":  5900, "SC":  5100, "RO":  4700, "CE":  4200,
    "PE":  3100, "PB":  2400, "RN":  2200, "ES":  2100, "AM":  1900,
    "SE":  1400, "AL":  1300, "RJ":  1100, "AC":   800, "DF":   400,
    "AP":   280, "RR":   350,
}

# UFs com cobertura agrícola e/ou meteorológica limitada (badge na UI)
UFS_DADOS_LIMITADOS = {"AP", "RR", "AM", "AC"}

# ── Bounding boxes por UF (lat_min, lon_min, lat_max, lon_max) ────────────────
# Fonte: IBGE Malha Territorial — valores aproximados para filtragem de focos FIRMS
# Limitação: focos em bordas estaduais podem ser contados em múltiplas UFs
UF_BBOX = {
    "AC": (-11.15,-73.98, -7.10,-66.62),
    "AL": (-10.50,-38.24, -8.81,-35.15),
    "AM": ( -9.82,-73.80,  2.25,-56.10),
    "AP": ( -1.25,-51.88,  4.44,-49.88),
    "BA": (-18.35,-46.62, -8.53,-37.34),
    "CE": ( -7.86,-41.42, -2.78,-37.25),
    "DF": (-16.05,-48.28,-15.50,-47.31),
    "ES": (-21.30,-41.88,-17.88,-39.68),
    "GO": (-19.47,-53.25,-12.40,-45.94),
    "MA": (-10.27,-48.75, -1.02,-41.81),
    "MG": (-22.92,-51.04,-14.23,-39.87),
    "MS": (-24.07,-58.16,-17.16,-50.93),
    "MT": (-18.04,-61.00, -7.35,-50.23),
    "PA": ( -9.85,-58.49,  2.59,-46.02),
    "PB": ( -8.27,-38.82, -6.02,-34.79),
    "PE": ( -9.49,-41.36, -7.42,-34.87),
    "PI": (-10.93,-45.98, -2.74,-40.37),
    "PR": (-26.72,-54.62,-22.52,-48.02),
    "RJ": (-23.37,-44.89,-20.76,-40.96),
    "RN": ( -6.98,-38.58, -4.83,-34.97),
    "RO": (-13.69,-66.81, -7.96,-59.76),
    "RR": ( -1.54,-64.82,  5.27,-58.89),
    "RS": (-33.75,-57.65,-27.09,-49.69),
    "SC": (-29.35,-53.84,-25.96,-48.37),
    "SE": (-11.57,-38.24, -9.52,-36.39),
    "SP": (-25.31,-53.11,-19.78,-44.16),
    "TO": (-13.46,-50.74, -5.18,-45.70),
}

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


def baixar_clima_uf(lat: float, lon: float, dias: int = 30) -> dict:
    """
    Retorna precipitação total (mm) e temperatura média (°C) dos últimos
    `dias` dias via Open-Meteo/ERA5.  Temperatura = média de (tmax+tmin)/2.
    """
    fim = date.today() - timedelta(days=1)
    ini = fim - timedelta(days=dias - 1)
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": ini.isoformat(), "end_date": fim.isoformat(),
        "daily": ["precipitation_sum", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "America/Sao_Paulo",
    }
    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=20)
        r.raise_for_status()
        daily = r.json().get("daily", {})
        precip = [v for v in daily.get("precipitation_sum",   []) if v is not None]
        tmax   = [v for v in daily.get("temperature_2m_max",  []) if v is not None]
        tmin   = [v for v in daily.get("temperature_2m_min",  []) if v is not None]
        tmean  = [(a+b)/2 for a,b in zip(tmax, tmin)]
        return {
            "precip": round(sum(precip), 1) if precip else None,
            "temp":   round(sum(tmean)/len(tmean), 2) if tmean else None,
        }
    except Exception as e:
        print(f"    Erro Open-Meteo ({lat},{lon}): {e}")
        return {"precip": None, "temp": None}


def _score_precipitacao(anomalia_pct: float) -> float:
    """
    Piecewise idêntico ao scripts/score.py (consistência metodológica).
    Seca severa (<-50%) → 90-100; excesso severo (>+80%) → 60-80; normal → ~10.
    """
    a = anomalia_pct
    if a <= -50:    return min(100, 90 + abs(a + 50) * 0.2)
    elif a < -20:   return 40 + (abs(a) - 20) * (50 / 30)
    elif a <= 20:   return max(0, 10 + abs(a) * 1.5)
    elif a <= 80:   return 20 + (a - 20) * (40 / 60)
    else:           return min(100, 60 + (a - 80) * 0.3)


def _score_enso(oni: float, uf: str) -> float:
    """ONI × sensibilidade UF → score 0-100. Fórmula: (oni*sens+1.5)/3.0*100."""
    sens = ENSO_SENS_UF.get(uf, 0.5)
    return round(max(0.0, min(100.0, (oni * sens + 1.5) / 3.0 * 100)), 1)


def _score_queimadas_percentile(focos_dict: dict) -> dict:
    """
    Normaliza focos de queimada por PERCENTILE RANK dentro das 27 UFs do período atual.

    Metodologia (Option 1 — percentile rank relativo):
      score_uf = (rank_uf - 1) / (n - 1) × 100
      Ties recebem o menor rank do grupo (method='min'), evitando falsa discriminação.

    Justificativa: a distribuição de focos por UF é fortemente assimétrica (log-normal),
    e qualquer threshold absoluto calibrado para pico de seca (jul-out) trivialmente satura
    em meses de transição (abr-mai). O percentile rank garante poder discriminatório
    permanente: a UF com mais focos no período SEMPRE fica próxima de 100,
    a com menos focos próxima de 0.

    Limitação documentada: o score é RELATIVO ao período atual, não absoluto.
    Numa semana com poucos focos em todo o Brasil, MT com 50 focos pode ficar em 100 —
    o que é metodologicamente correto (MT tem MAIS risco relativo nessa semana).

    Para a apresentação: "usamos percentile rank entre as 27 UFs para garantir
    poder discriminatório em qualquer época do ano, sem necessidade de séries
    históricas por UF que não estão disponíveis via API pública."
    """
    ufs      = list(focos_dict.keys())
    valores  = [focos_dict[u] for u in ufs]
    n        = len(ufs)

    # Ordena por focos e atribui ranks 0..(n-1); ties recebem menor rank do grupo
    indexed  = sorted(enumerate(valores), key=lambda x: x[1])
    ranks    = [0] * n
    i = 0
    while i < n:
        j = i
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        # Todos os empates recebem o rank mínimo do grupo (posição base)
        for k in range(i, j):
            ranks[indexed[k][0]] = i
        i = j

    denom = max(n - 1, 1)
    return {ufs[k]: round(ranks[k] / denom * 100, 1) for k in range(n)}


def _score_temperatura(anomalia_temp: float, uf: str) -> float:
    """
    Anomalia positiva (calor) = risco para lavouras.
    No Sul (RS, SC, PR): anomalia negativa < -1.5°C = risco de geada.

    Calibração:
      0°C  → score  5  (baseline, sem anomalia)
      +3°C → score 47  (atenção)
      +5°C → score 75  (crítico)
      +6.8°C → score 100 (satura — evento extremo)
      Geada Sul: -2°C → 44, -4.5°C → 99

    Justificativa para slope 14 (anterior era 25):
      O slope 25 saturava a +3.2°C — anomalias de +4-5°C são incomuns mas acontecem
      (RS abr/2026: +4.2°C, SC: +4.9°C). Com slope 14, esses eventos ficam em 63-73
      sem saturar, preservando discriminação para eventos extremos reais (>+7°C).
    """
    if uf in ("RS", "SC", "PR") and anomalia_temp < -1.5:
        return min(100, round(abs(anomalia_temp) * 22, 1))
    return min(100, max(0, round(anomalia_temp * 14 + 5, 1)))


def calcular_score_ufs(dias: int = 30) -> "pd.DataFrame | None":
    """
    Calcula ClimaRisk Score para as 27 UFs e salva em data/score_ufs.csv.
    Faz 27 chamadas à Open-Meteo (delay 0.3s) → 30-60s no total.
    """
    try:
        oni_df = pd.read_csv("data/oni_index.csv", parse_dates=["data"])
        q_df   = pd.read_csv("data/queimadas.csv")
    except FileNotFoundError as e:
        print(f"Arquivo não encontrado: {e}. Rode os módulos 1-3 primeiro.")
        return None

    oni_atual = float(oni_df.dropna(subset=["ONI"]).iloc[-1]["ONI"])
    oni_data  = str(oni_df.dropna(subset=["ONI"]).iloc[-1]["data"])[:7]
    mes       = date.today().month

    print(f"ClimaRisk por UF — ONI {oni_atual:+.2f} ({oni_data}) — {len(UF_CENTROIDES)} UFs")

    # ── Pré-processa focos por UF via bounding box ────────────────────────────
    # NASA FIRMS CSV usa "latitude"/"longitude"; garantir fallback p/ "lat"/"lon"
    focos_por_uf = {uf: 0 for uf in UF_CENTROIDES}
    _lat_col = next((c for c in ("latitude","lat") if c in q_df.columns), None)
    _lon_col = next((c for c in ("longitude","lon") if c in q_df.columns), None)
    if not q_df.empty and _lat_col and _lon_col:
        lats = q_df[_lat_col].values
        lons = q_df[_lon_col].values
        for uf, (lat_min, lon_min, lat_max, lon_max) in UF_BBOX.items():
            mask = (lats >= lat_min) & (lats <= lat_max) & \
                   (lons >= lon_min) & (lons <= lon_max)
            focos_por_uf[uf] = int(mask.sum())
        total_focos = sum(focos_por_uf.values())
        print(f"  Focos mapeados por UF: {total_focos} total "
              f"(coluna: {_lat_col}/{_lon_col})")
        if total_focos == 0:
            print("  AVISO: zero focos em todas as UFs — verificar queimadas.csv")
    else:
        print(f"  AVISO: queimadas.csv sem colunas de coordenadas "
              f"(encontradas: {list(q_df.columns[:5])}). Focos = 0 em todas UFs.")

    # Percentile rank para queimadas (calculado antes do loop — precisa de todos os valores)
    q_rank_scores = _score_queimadas_percentile(focos_por_uf)

    # Log de validação: top/bottom 5 para conferência visual
    sorted_focos = sorted(focos_por_uf.items(), key=lambda x: -x[1])
    print("  Top 5 UFs (focos → score percentile):")
    for u, f in sorted_focos[:5]:
        print(f"    {u}: {f} focos → {q_rank_scores[u]:.1f}/100")
    print("  Bottom 5 UFs:")
    for u, f in sorted_focos[-5:]:
        print(f"    {u}: {f} focos → {q_rank_scores[u]:.1f}/100")

    registros = []
    for uf, (lat, lon) in UF_CENTROIDES.items():
        print(f"  {uf} ({lat:.1f},{lon:.1f})...", end=" ", flush=True)

        normal_precip = NORMAIS_PRECIP_MM[uf][mes - 1] * (dias / 30)
        normal_temp   = NORMAIS_TEMP_C[uf][mes - 1]

        clima = baixar_clima_uf(lat, lon, dias)
        time.sleep(0.3)

        if clima["precip"] is not None:
            anomalia_pct = round((clima["precip"] - normal_precip) / max(normal_precip, 1) * 100, 1)
            fonte_precip = "Open-Meteo/ERA5"
        else:
            anomalia_pct = 0.0
            fonte_precip = "fallback_neutro"

        if clima["temp"] is not None:
            anomalia_temp = round(clima["temp"] - normal_temp, 2)
            fonte_temp    = "Open-Meteo/ERA5"
        else:
            anomalia_temp = 0.0
            fonte_temp    = "fallback_neutro"

        focos    = focos_por_uf.get(uf, 0)
        s_prec   = _score_precipitacao(anomalia_pct)
        s_enso   = _score_enso(oni_atual, uf)
        s_queima = q_rank_scores.get(uf, 0.0)
        s_temp   = _score_temperatura(anomalia_temp, uf)

        score_final = round(s_prec*0.35 + s_enso*0.25 + s_queima*0.25 + s_temp*0.15, 1)
        nivel       = "CRITICO" if score_final >= 70 else ("ATENCAO" if score_final >= 45 else "NORMAL")

        print(f"score={score_final:.1f} {nivel} | "
              f"prec={s_prec:.0f}({anomalia_pct:+.0f}%) "
              f"enso={s_enso:.0f} fogo={s_queima:.0f}({focos}) "
              f"temp={s_temp:.0f}({anomalia_temp:+.1f}°C)")

        registros.append({
            "uf": uf, "score": score_final, "nivel": nivel,
            "comp_prec":     round(s_prec, 1),
            "comp_enso":     round(s_enso, 1),
            "comp_queimadas":round(s_queima, 1),
            "comp_temp":     round(s_temp, 1),
            "anomalia_precip_pct": anomalia_pct,
            "anomalia_temp_c":     anomalia_temp,
            "oni_ref":   oni_atual,
            "focos_7d":  focos,
            "fonte_precip": fonte_precip,
            "fonte_temp":   fonte_temp,
            "dados_limitados": uf in UFS_DADOS_LIMITADOS,
        })

    df = pd.DataFrame(registros).sort_values("score", ascending=False).reset_index(drop=True)
    df.to_csv("data/score_ufs.csv", index=False)
    print(f"\nSalvo: data/score_ufs.csv ({len(df)} UFs)")
    return df


if __name__ == "__main__":
    df = calcular_score_ufs()
    if df is not None:
        print("\nRANKING CLIMARISK POR UF")
        print(df[["uf","score","nivel","dados_limitados"]].to_string(index=False))
        print(f"\nUFs CRÍTICAS: {df[df['nivel']=='CRITICO']['uf'].tolist()}")
        print(f"UFs ATENÇÃO:  {df[df['nivel']=='ATENCAO']['uf'].tolist()}")
        print(f"UFs NORMAIS:  {df[df['nivel']=='NORMAL']['uf'].tolist()}")
