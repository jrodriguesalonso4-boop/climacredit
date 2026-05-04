# ClimaCredit — Módulo 1: Índice ENSO (El Niño / La Niña)
# Fonte: NOAA Physical Sciences Laboratory

import requests
import pandas as pd
from pathlib import Path

Path("data").mkdir(exist_ok=True)

def baixar_oni():
    url = "https://psl.noaa.gov/data/correlation/nina34.anom.data"
    print("Baixando índice ENSO (ONI) da NOAA...")
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"Erro ao conectar com a NOAA: {e}")
        return None
    linhas = r.text.strip().split("\n")
    dados = []
    for linha in linhas:
        partes = linha.split()
        if len(partes) == 13:
            try:
                ano = int(partes[0])
                for mes, val in enumerate(partes[1:], start=1):
                    v = float(val)
                    if v > -99:
                        dados.append({"ano": ano, "mes": mes, "ONI": v})
            except ValueError:
                continue
    df = pd.DataFrame(dados)
    df["data"] = pd.to_datetime(
        df["ano"].astype(str) + "-" +
        df["mes"].astype(str).str.zfill(2) + "-01"
    )
    df = df.sort_values("data").reset_index(drop=True)
    df.to_csv("data/oni_index.csv", index=False)
    print(f"Dados salvos: data/oni_index.csv ({len(df)} registros)")
    return df

def status_enso_atual(df):
    ultimo = df.dropna(subset=["ONI"]).iloc[-1]
    oni = ultimo["ONI"]
    data = ultimo["data"].strftime("%b/%Y")
    if oni >= 1.5:
        status = "El Nino Forte"
    elif oni >= 0.5:
        status = "El Nino Moderado"
    elif oni <= -1.5:
        status = "La Nina Forte"
    elif oni <= -0.5:
        status = "La Nina Moderada"
    else:
        status = "Neutro"
    print(f"\nSTATUS ENSO ATUAL")
    print(f"   Periodo: {data}")
    print(f"   ONI: {oni:+.2f} graus C")
    print(f"   Status: {status}")
    return {"status": status, "oni": oni, "data": data}

def impacto_enso_agro(oni):
    if oni >= 0.5:
        return {
            "Centro-Oeste": "ATENCAO - Seca mais provavel - risco para soja e milho",
            "Sul": "OK - Chuvas acima da media - favoravel para graos",
            "Nordeste": "RISCO CRITICO - Seca severa mais provavel",
            "Sudeste": "ATENCAO - Chuvas irregulares - atencao ao cafe",
            "Norte": "RISCO - Seca amazonica - risco para energia e logistica"
        }
    elif oni <= -0.5:
        return {
            "Centro-Oeste": "OK - Chuvas normais a acima - favoravel",
            "Sul": "RISCO - Seca mais provavel - risco para soja e trigo",
            "Nordeste": "OK - Chuvas acima da media",
            "Sudeste": "ATENCAO - Variabilidade alta - monitorar",
            "Norte": "OK - Chuvas normais a acima"
        }
    else:
        return {
            "Centro-Oeste": "OK - Condicoes normais esperadas",
            "Sul": "OK - Condicoes normais esperadas",
            "Nordeste": "MONITORAR - Variabilidade natural",
            "Sudeste": "OK - Condicoes normais esperadas",
            "Norte": "OK - Condicoes normais esperadas"
        }

if __name__ == "__main__":
    df = baixar_oni()
    if df is not None:
        enso = status_enso_atual(df)
        impactos = impacto_enso_agro(enso["oni"])
        print(f"\nIMPACTO ESPERADO NAS REGIOES AGRICOLAS:")
        for regiao, impacto in impactos.items():
            print(f"   {regiao}: {impacto}")
        print(f"\nHISTORICO RECENTE (ultimos 12 meses):")
        print(df.tail(12)[["data", "ONI"]].to_string(index=False))
