# ClimaCredit — Módulo 3: Anomalia de Precipitação
# Fonte: Open-Meteo Archive API (ERA5 reanalysis, sem autenticação)
# Normal climatológica: INMET 1991-2020 (valores tabelados por região/mês)

import requests
import pandas as pd
from pathlib import Path
from datetime import date, timedelta

Path("data").mkdir(exist_ok=True)

# Coordenadas representativas de cada região agrícola
REGIOES_COORDS = {
    "Centro-Oeste": (-15.60, -56.10),  # Cuiabá/MT
    "Sul":          (-25.43, -49.27),  # Curitiba/PR
    "Nordeste":     (-12.97, -38.51),  # Salvador/BA
    "Sudeste":      (-21.76, -43.35),  # Juiz de Fora/MG (polo agrícola)
    "Norte":        ( -1.46, -48.50),  # Belém/PA
}

# Normais climatológicas mensais INMET 1991-2020 (precip mm/mês, Jan→Dez)
NORMAIS_MM = {
    "Centro-Oeste": [247, 196, 212,  96,  36,   8,   8,  22,  68, 138, 185, 226],
    "Sul":          [161, 143, 113, 108, 109, 111, 127, 118, 142, 131, 118, 143],
    "Nordeste":     [ 70, 120, 168, 163, 103,  52,  28,  18,  22,  30,  43,  52],
    "Sudeste":      [243, 188, 158,  72,  49,  38,  36,  39,  73, 113, 142, 207],
    "Norte":        [315, 306, 352, 325, 268, 178, 162, 148, 138, 118, 168, 243],
}

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"

def baixar_precipitacao_recente(lat: float, lon: float, dias: int = 30) -> float | None:
    """Retorna precipitação total (mm) dos últimos `dias` dias via Open-Meteo."""
    fim = date.today() - timedelta(days=1)   # ontem (dados confirmados)
    ini = fim - timedelta(days=dias - 1)
    params = {
        "latitude":  lat,
        "longitude": lon,
        "start_date": ini.isoformat(),
        "end_date":   fim.isoformat(),
        "daily":      "precipitation_sum",
        "timezone":   "America/Sao_Paulo",
    }
    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=15)
        r.raise_for_status()
        valores = r.json().get("daily", {}).get("precipitation_sum", [])
        valores = [v for v in valores if v is not None]
        return round(sum(valores), 1) if valores else None
    except Exception as e:
        print(f"    Erro Open-Meteo ({lat},{lon}): {e}")
        return None

def calcular_anomalias(dias: int = 30) -> pd.DataFrame | None:
    hoje = date.today()
    mes_atual = hoje.month

    print(f"Calculando anomalia de precipitação — últimos {dias} dias (Open-Meteo/ERA5)...")
    registros = []

    for regiao, (lat, lon) in REGIOES_COORDS.items():
        normal_mensal = NORMAIS_MM[regiao][mes_atual - 1]
        # Ajusta normal para o número de dias consultados vs. ~30 dias do mês
        normal_periodo = normal_mensal * (dias / 30)

        print(f"  {regiao} ({lat:.1f}, {lon:.1f})...", end=" ")
        precip_obs = baixar_precipitacao_recente(lat, lon, dias)

        if precip_obs is not None:
            anomalia_mm  = round(precip_obs - normal_periodo, 1)
            anomalia_pct = round((precip_obs - normal_periodo) / max(normal_periodo, 1) * 100, 1)
            fonte = "Open-Meteo/ERA5"
            print(f"{precip_obs:.1f} mm obs | normal {normal_periodo:.1f} mm | anomalia {anomalia_pct:+.1f}%")
        else:
            # Fallback: sem anomalia (neutro) — app sinaliza na UI
            precip_obs   = normal_periodo
            anomalia_mm  = 0.0
            anomalia_pct = 0.0
            fonte = "fallback_neutro"
            print("FALLBACK — sem dados, usando neutro")

        registros.append({
            "regiao":        regiao,
            "lat":           lat,
            "lon":           lon,
            "precip_obs_mm": precip_obs,
            "normal_mm":     round(normal_periodo, 1),
            "anomalia_mm":   anomalia_mm,
            "anomalia_pct":  anomalia_pct,
            "mes_ref":       mes_atual,
            "dias":          dias,
            "fonte":         fonte,
        })

    df = pd.DataFrame(registros)
    df.to_csv("data/anomalia_chuva.csv", index=False)
    print(f"\nSalvo: data/anomalia_chuva.csv ({len(df)} regiões)")
    return df

if __name__ == "__main__":
    df = calcular_anomalias(dias=30)
    if df is not None:
        print("\nANOMALIA DE PRECIPITAÇÃO POR REGIÃO")
        for _, row in df.iterrows():
            sinal = "SECO" if row["anomalia_pct"] < -20 else ("CHUVOSO" if row["anomalia_pct"] > 20 else "NORMAL")
            print(f"   {row['regiao']:<14}: {row['anomalia_pct']:+.1f}% ({sinal}) — fonte: {row['fonte']}")
