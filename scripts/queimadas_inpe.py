# ClimaCredit — Módulo 2: Focos de Calor (Queimadas)
# Fonte: NASA FIRMS / VIIRS SNPP — inclui dados dos satélites do INPE
# Cobertura: América do Sul, últimos 7 dias (janela máxima do endpoint público)

import io
import warnings
import requests
import urllib3
import pandas as pd
from pathlib import Path
from datetime import date

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

Path("data").mkdir(exist_ok=True)

# Bounding box do Brasil (lat, lon)
BRASIL_LAT = (-33.8, 5.3)
BRASIL_LON = (-73.9, -28.8)

REGIOES = {
    "Centro-Oeste": ["MT", "MS", "GO", "DF"],
    "Sul":          ["RS", "SC", "PR"],
    "Nordeste":     ["MA", "PI", "CE", "RN", "PB", "PE", "AL", "SE", "BA"],
    "Sudeste":      ["MG", "ES", "RJ", "SP"],
    "Norte":        ["AM", "PA", "AC", "RO", "RR", "AP", "TO"],
}

# URL pública do NASA FIRMS — VIIRS SNPP, América do Sul, 7 dias (sem autenticação)
FIRMS_URL = (
    "https://firms.modaps.eosdis.nasa.gov"
    "/data/active_fire/suomi-npp-viirs-c2/csv"
    "/SUOMI_VIIRS_C2_South_America_7d.csv"
)

def lat_lon_para_regiao(lat: float, lon: float) -> str:
    """Mapeia coordenada para região agrícola brasileira (aproximação por bbox)."""
    if not (BRASIL_LAT[0] <= lat <= BRASIL_LAT[1] and
            BRASIL_LON[0] <= lon <= BRASIL_LON[1]):
        return "Outro"
    # Sul (RS, SC, PR) — latitude mais ao sul
    if lat < -22.5 and lon > -54.5:
        return "Sul"
    # Sudeste (MG, ES, RJ, SP)
    if -24 <= lat < -14 and lon >= -51:
        return "Sudeste"
    # Nordeste (MA, PI, CE, RN, PB, PE, AL, SE, BA) — faixa leste/nordeste
    if lat >= -18 and lon >= -48:
        return "Nordeste"
    # Norte (AM, PA, AC, RO, RR, AP, TO)
    if lat >= -13:
        return "Norte"
    # Centro-Oeste (MT, MS, GO, DF)
    return "Centro-Oeste"

def baixar_queimadas():
    print("Baixando focos de queimadas — NASA FIRMS / VIIRS SNPP (últimos 7 dias)...")
    print(f"   Referência: {date.today().strftime('%d/%m/%Y')}")
    try:
        r = requests.get(FIRMS_URL, timeout=30, verify=False)
        r.raise_for_status()
    except Exception as e:
        print(f"Erro ao conectar com NASA FIRMS: {e}")
        return None

    try:
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f"Erro ao parsear CSV: {e}")
        return None

    if df.empty:
        print("Nenhum foco encontrado.")
        return None

    # Filtra Brasil pelo bounding box
    df = df[
        df["latitude"].between(*BRASIL_LAT) &
        df["longitude"].between(*BRASIL_LON)
    ].copy()

    df["regiao"] = df.apply(
        lambda row: lat_lon_para_regiao(row["latitude"], row["longitude"]),
        axis=1
    )

    df.to_csv("data/queimadas.csv", index=False)
    total_brasil = len(df)
    print(f"Dados salvos: data/queimadas.csv ({total_brasil} focos no Brasil)")
    return df

def status_queimadas_atual(df):
    contagem = (
        df[df["regiao"] != "Outro"]
        .groupby("regiao")
        .size()
        .reindex(list(REGIOES.keys()), fill_value=0)
    )

    print("\nFOCOS DE CALOR POR REGIÃO AGRÍCOLA (últimos 7 dias)")
    resultado = {}
    for regiao, total in contagem.items():
        if total >= 200:
            nivel = "CRITICO"
        elif total >= 60:
            nivel = "ATENCAO"
        else:
            nivel = "NORMAL"
        print(f"   {regiao:<14}: {total:>5} focos — {nivel}")
        resultado[regiao] = {"focos": int(total), "nivel": nivel}

    # Top 5 estados por densidade de focos (proxy por célula de lat/lon)
    df_br = df[df["regiao"] != "Outro"].copy()
    df_br["lat_bin"] = (df_br["latitude"] // 2).astype(int)
    df_br["lon_bin"] = (df_br["longitude"] // 2).astype(int)
    top_regioes = (
        df_br.groupby("regiao").size()
        .sort_values(ascending=False)
        .head(5)
    )
    print("\nREGIÕES COM MAIS FOCOS:")
    print("   " + " | ".join(f"{r}: {n}" for r, n in top_regioes.items()))

    return resultado

def risco_queimadas_agro(regioes_status):
    resultado = {}
    for regiao, info in regioes_status.items():
        focos = info["focos"]
        nivel = info["nivel"]
        if nivel == "CRITICO":
            resultado[regiao] = (
                f"RISCO CRITICO - {focos} focos nos ultimos 7 dias"
                f" - risco severo para qualidade do ar e agricultura"
            )
        elif nivel == "ATENCAO":
            resultado[regiao] = (
                f"ATENCAO - {focos} focos nos ultimos 7 dias"
                f" - monitorar qualidade do ar e umidade do solo"
            )
        else:
            resultado[regiao] = (
                f"OK - {focos} focos nos ultimos 7 dias - nivel normal"
            )
    return resultado

if __name__ == "__main__":
    df = baixar_queimadas()
    if df is not None:
        status   = status_queimadas_atual(df)
        riscos   = risco_queimadas_agro(status)
        print("\nRISCO AGRÍCOLA POR REGIÃO:")
        for regiao, msg in riscos.items():
            print(f"   {regiao}: {msg}")
        print(f"\nHISTÓRICO RECENTE (últimos 10 registros):")
        print(df[["latitude", "longitude", "acq_date", "regiao"]].tail(10).to_string(index=False))
