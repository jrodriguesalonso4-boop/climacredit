# ClimaCredit — Módulo 4: ClimaRisk Score
# Score 0–100 por região agrícola. Quanto maior, maior o risco climático.
#
# Metodologia de pesos:
#   Precipitação  35%  — anomalia percentual vs. normal 1991-2020
#   ENSO          25%  — ONI atual × sensibilidade regional
#   Queimadas     25%  — focos ativos normalizados pelo histórico sazonal
#   Temperatura   15%  — proxy ENSO (sem fonte direta de temp. disponível)
#
# Normalização:
#   Cada componente é convertido para 0–100 antes da ponderação.
#   Score final = soma ponderada dos componentes normalizados.

import numpy as np
import pandas as pd
from pathlib import Path

Path("data").mkdir(exist_ok=True)

REGIOES = ["Centro-Oeste", "Sul", "Nordeste", "Sudeste", "Norte"]

# ── Sensibilidade ENSO por região ──────────────────────────────────────────
# Positivo = El Niño aumenta risco; negativo = La Niña aumenta risco
# Escala -1 a +1 (pesquisa: CPTEC/INPE, Mason & Goddard 2001)
ENSO_SENS = {
    "Centro-Oeste": +0.7,   # El Niño → seca
    "Sul":          -0.8,   # La Niña → seca
    "Nordeste":     +0.9,   # El Niño → seca severa
    "Sudeste":      +0.4,   # El Niño → chuvas irregulares
    "Norte":        +0.6,   # El Niño → seca amazônica
}

# ── Teto de focos por região para normalização (P95 histórico, ~7 dias) ───
# Fonte: NASA FIRMS VIIRS SNPP South America — estimativa P95 do pico de queimadas
# (julho-outubro, quando Cerrado e Amazônia atingem máximos históricos).
# Calibração: MT sozinho chega a ~5.000-8.000 focos/7d em setembro de anos severos.
# Valores anteriores {800,600,700,800,1200} eram ~5-10x subdimensionados,
# saturando a componente em qualquer período fora da entressafra.
# Referência: INPE BDQueimadas / FIRMS historical archive 2012-2023.
FOCOS_P95 = {
    "Centro-Oeste": 6000,   # MT + GO + MS + DF em pico (ago-set)
    "Sul":          3000,   # RS + PR + SC em seca severa La Niña
    "Nordeste":     2500,   # BA + MA + PI em seca extrema
    "Sudeste":      3500,   # MG + SP dominam; pico mai-ago
    "Norte":        6000,   # PA + AM + RO + TO em seca amazônica
}

def _score_precipitacao(anomalia_pct: float) -> float:
    """
    Anomalia negativa (seca) e anomalia muito positiva (excesso) são ambas ruins.
    Seca severa (<-50%) → 90-100. Excesso severo (>+80%) → 60-80. Normal → ~10.
    """
    a = anomalia_pct
    if a <= -50:
        return min(100, 90 + abs(a + 50) * 0.2)
    elif a < -20:
        return 40 + (abs(a) - 20) * (50 / 30)
    elif a <= 20:
        return max(0, 10 + abs(a) * 1.5)
    elif a <= 80:
        return 20 + (a - 20) * (40 / 60)
    else:
        return min(100, 60 + (a - 80) * 0.3)

def _score_enso(oni: float, regiao: str) -> float:
    """
    ONI × sensibilidade regional → score 0-100.
    Risco aumenta quando ONI e sensibilidade têm mesmo sinal.
    """
    sens = ENSO_SENS.get(regiao, 0.5)
    risco_raw = oni * sens        # positivo = risco, negativo = favorável
    # Normaliza: ±3 ONI = ±100% risco
    normalizado = max(0, min(1, (risco_raw + 1.5) / 3.0))
    return round(normalizado * 100, 1)

def _score_queimadas(focos: int, regiao: str) -> float:
    """Normaliza focos pelo P95 histórico da região. Linear 0-100."""
    teto = FOCOS_P95.get(regiao, 800)
    return min(100, round(focos / teto * 100, 1))

def calcular_score() -> pd.DataFrame | None:
    # ── Carrega dados dos módulos anteriores ──────────────────────────────
    try:
        oni_df   = pd.read_csv("data/oni_index.csv", parse_dates=["data"])
        prec_df  = pd.read_csv("data/anomalia_chuva.csv")
        q_df     = pd.read_csv("data/queimadas.csv")
    except FileNotFoundError as e:
        print(f"Arquivo não encontrado: {e}. Rode os módulos 1-3 primeiro.")
        return None

    # ONI mais recente
    oni_atual = float(oni_df.dropna(subset=["ONI"]).iloc[-1]["ONI"])
    oni_data  = str(oni_df.dropna(subset=["ONI"]).iloc[-1]["data"])[:7]

    # Focos por região (queimadas.csv)
    focos_por_regiao = (
        q_df[q_df["regiao"] != "Outro"]
        .groupby("regiao").size()
        .reindex(REGIOES, fill_value=0)
        .to_dict()
    )

    # Anomalia precip por região
    prec_map = prec_df.set_index("regiao")[["anomalia_pct", "fonte"]].to_dict("index")

    print(f"Calculando ClimaRisk Score — ONI atual: {oni_atual:+.2f} ({oni_data})")
    registros = []

    for regiao in REGIOES:
        anom_pct = prec_map.get(regiao, {}).get("anomalia_pct", 0.0)
        fonte    = prec_map.get(regiao, {}).get("fonte", "desconhecida")
        focos    = focos_por_regiao.get(regiao, 0)

        s_prec   = _score_precipitacao(anom_pct)
        s_enso   = _score_enso(oni_atual, regiao)
        s_queima = _score_queimadas(focos, regiao)
        s_temp   = s_enso * 0.7   # proxy temperatura via ENSO

        score_final = round(
            s_prec   * 0.35 +
            s_enso   * 0.25 +
            s_queima * 0.25 +
            s_temp   * 0.15,
            1
        )

        if score_final >= 70:
            nivel = "CRITICO"
        elif score_final >= 45:
            nivel = "ATENCAO"
        else:
            nivel = "NORMAL"

        print(f"  {regiao:<14}: score {score_final:5.1f} | prec {s_prec:.0f} | enso {s_enso:.0f} | "
              f"fogo {s_queima:.0f} | temp {s_temp:.0f} → {nivel}")

        registros.append({
            "regiao":         regiao,
            "score":          score_final,
            "nivel":          nivel,
            "comp_prec":      round(s_prec, 1),
            "comp_enso":      round(s_enso, 1),
            "comp_queimadas": round(s_queima, 1),
            "comp_temp":      round(s_temp, 1),
            "anomalia_pct":   anom_pct,
            "oni_ref":        oni_atual,
            "focos_7d":       focos,
            "fonte_prec":     fonte,
        })

    df = pd.DataFrame(registros).sort_values("score", ascending=False).reset_index(drop=True)
    df.to_csv("data/score_regioes.csv", index=False)
    print(f"\nSalvo: data/score_regioes.csv")
    return df

if __name__ == "__main__":
    df = calcular_score()
    if df is not None:
        print("\nRANKING CLIMARISK")
        print(df[["regiao", "score", "nivel"]].to_string(index=False))
