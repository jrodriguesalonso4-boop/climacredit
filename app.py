"""
ClimaCredit — Dashboard de Risco Climático para Crédito Agro
GAS Challenge 2026.1 · XP Inc. · Mentor: João Gabriel Amarante
"""

import io
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ClimaCredit · XP",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS global ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .stApp, [data-testid="stAppViewContainer"] { background: #0A0A0A !important; }
  [data-testid="stHeader"] { background: #0A0A0A !important; }
  h1,h2,h3,h4,h5,h6,p,span,div,label { color: #FFFFFF !important; }
  .stTabs [data-baseweb="tab-list"]  { background: #111111; border-radius: 10px; padding: 4px; gap: 4px; }
  .stTabs [data-baseweb="tab"]       { background: transparent; color: #888 !important; border-radius: 8px; padding: 8px 20px; font-weight: 600; }
  .stTabs [aria-selected="true"]     { background: #00B4A2 !important; color: #000 !important; }
  [data-testid="metric-container"]   { background: #111111; border: 1px solid #1E1E1E; border-radius: 12px; padding: 16px !important; }
  [data-testid="stMetricValue"]      { font-size: 1.6rem !important; font-weight: 800; color: #00B4A2 !important; }
  .stSelectbox > div > div { background: #111111 !important; border-color: #1E1E1E !important; }
  .stSlider [data-baseweb="slider"] div[role="slider"] { background: #00B4A2 !important; }
  hr { border-color: #1E1E1E !important; }
  .stDataFrame thead tr th { background: #111111 !important; color: #00B4A2 !important; }
  .badge-critico  { background:#FF4444; color:#FFF; padding:3px 10px; border-radius:20px; font-size:.75rem; font-weight:700; }
  .badge-atencao  { background:#F5A623; color:#000; padding:3px 10px; border-radius:20px; font-size:.75rem; font-weight:700; }
  .badge-normal   { background:#00B4A2; color:#000; padding:3px 10px; border-radius:20px; font-size:.75rem; font-weight:700; }
  .alert-card { background:#111111; border-left:4px solid; border-radius:8px; padding:12px 16px; margin:6px 0; }
  .alert-critico  { border-color:#FF4444; }
  .alert-atencao  { border-color:#F5A623; }
  .alert-normal   { border-color:#00B4A2; }
  .muni-card { background:#111; border:1px solid #1E1E1E; border-radius:10px; padding:16px; margin-top:10px; }
</style>
""", unsafe_allow_html=True)

PLOTLY_LAYOUT = dict(
    paper_bgcolor="#0A0A0A", plot_bgcolor="#111111",
    font_color="#FFFFFF", font_family="Inter, sans-serif",
    margin=dict(l=20, r=20, t=40, b=20),
    colorway=["#00B4A2","#F5A623","#FF4444","#7B61FF","#4ADE80"],
)
NIVEL_COR = {"CRITICO":"#FF4444","ATENCAO":"#F5A623","NORMAL":"#00B4A2"}

def format_or_dash(valor, fmt=".0f"):
    """Formata valor numérico com fmt, ou retorna '—' se for None/NaN/vazio."""
    if valor is None:
        return "—"
    try:
        if np.isnan(float(valor)):
            return "—"
    except (TypeError, ValueError):
        return "—"
    return format(float(valor), fmt)

def fmt_sensibilidade(valor) -> str:
    """Formata coeficiente de sensibilidade ENSO com sinal e 3 casas decimais.
    Usa f-string formatting (camada de exibição) — nunca round(), que preserva imprecisão de float.
    Ex.: -0.6999999999999998 → '-0.700'  |  0.5 → '+0.500'  |  None → '—'
    """
    if valor is None:
        return "—"
    try:
        v = float(valor)
        if np.isnan(v):
            return "—"
        return f"{v:+.3f}"
    except (TypeError, ValueError):
        return "—"

def fazer_limpar_callback(*keys):
    """Retorna um callback que zera as session_state keys informadas.
    Use em on_click= de botões para evitar StreamlitAPIException ao
    modificar session_state de widgets já instanciados no mesmo run."""
    def _callback():
        for k in keys:
            if k in st.session_state:
                st.session_state[k] = ""
    return _callback

import textwrap as _textwrap

def html_card(content: str):
    """Render HTML safely, stripping Python-indentation whitespace via textwrap.dedent.
    Markdown treats lines with 4+ leading spaces as code blocks — dedent prevents that."""
    st.markdown(_textwrap.dedent(content), unsafe_allow_html=True)

def _comp_color(score_val: float) -> str:
    """Retorna cor hex para um valor de componente de score (0-100)."""
    if score_val >= 70: return NIVEL_COR["CRITICO"]
    if score_val >= 45: return NIVEL_COR["ATENCAO"]
    return NIVEL_COR["NORMAL"]

def _enso_label(oni: float) -> str:
    if oni >= 1.5:  return "El Niño Forte"
    if oni >= 0.5:  return "El Niño"
    if oni <= -1.5: return "La Niña Forte"
    if oni <= -0.5: return "La Niña"
    return "Neutro"

def _enso_color(oni: float) -> str:
    if oni >= 0.5:  return "#F5A623"
    if oni <= -0.5: return "#4A90D9"
    return "#888"

def render_card_municipio(
    nome_muni: str, uf: str, micro: str, regiao_muni: str,
    coord_nota: str, aviso_vizinho: str,
    res: dict,
    uf_score_str: str, uf_delta_str: str,
    precisao: str, cache_lbl: str,
):
    """
    Renderiza o card de ClimaRisk Score municipal.
    Ponto único de renderização — ambos os caminhos de busca devem chamar esta função.

    Regra crítica de HTML/Markdown:
      O CommonMark encerra um bloco HTML tipo-6 (<div>) na primeira linha em branco.
      Qualquer variável opcional que possa ser "" DEVE usar "<!-- -->" como fallback,
      caso contrário a linha em branco gerada quebra o bloco e o restante vaza como texto literal.
    """
    cor_nivel    = NIVEL_COR.get(res["nivel"], "#555")
    _uf_dlta_cor = ('#FF4444' if uf_delta_str.startswith('↑')
                    else ('#4ADE80' if uf_delta_str.startswith('↓') else '#555'))

    # Scores como strings
    _s_prec  = f"{res['comp_prec']:.0f}"
    _s_enso  = f"{res['comp_enso']:.0f}"
    _s_qm    = f"{res['comp_queimadas']:.0f}"
    _s_temp  = f"{res['comp_temp']:.0f}"
    _s_score = f"{res['score']:.0f}"
    _nivel_l = res['nivel'].lower()

    # Cores das componentes (para linhas de anomalia)
    _c_prec = _comp_color(res['comp_prec'])
    _c_temp = _comp_color(res['comp_temp'])

    # Valores físicos reais — destaque grande
    _precip_v = f"{res['precip_obs']:.0f} mm" if res['precip_obs'] is not None else "— mm"
    _temp_v   = f"{res['temp_obs']:.1f}°C"    if res['temp_obs']  is not None else "—°C"

    # Anomalias com seta
    _anom_p  = format_or_dash(res['anomalia_pct'],  '+.1f')
    _anom_t  = format_or_dash(res['anomalia_temp'], '+.1f')
    _arrow_p = "▲" if (res['anomalia_pct']  or 0) > 0 else "▼"
    _arrow_t = "▲" if (res['anomalia_temp'] or 0) > 0 else "▼"

    # ENSO
    _oni_s    = f"{res['oni_val']:+.2f}"
    _enso_lbl = _enso_label(res['oni_val'])
    _enso_cor = _enso_color(res['oni_val'])
    _sens_val = ENSO_SENS_UF.get(uf, 0.5) if ENSO_SENS_UF else 0.5
    _sens_mag = ("alta" if abs(_sens_val) >= 0.7
                 else ("média" if abs(_sens_val) >= 0.4 else "baixa"))
    _sens_dir = "El Niño" if _sens_val > 0 else "La Niña"
    _sens_lbl = f"Sensib. {uf}: {_sens_mag} a {_sens_dir}"

    # Nota temperatura
    _temp_note = " · sem risco térmico no índice" if res['comp_temp'] == 0 else ""

    # CRÍTICO: nunca deixar string vazia em posição de linha isolada no f-string.
    # Uma linha em branco encerra o bloco HTML no CommonMark → use <!-- --> como fallback.
    _aviso_h = (f'<div style="color:#888;font-size:.72rem;margin-top:2px">{aviso_vizinho}</div>'
                if aviso_vizinho else "<!-- -->")

    html_card(f"""
<div class="muni-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
    <div>
      <div style="font-size:1.2rem;font-weight:800">{nome_muni}
        <span style="color:#555;font-weight:400">/ {uf}</span>
      </div>
      <div style="color:#888;font-size:.82rem">Microrregião: {micro} · Região: <b style="color:#CCC">{regiao_muni}</b></div>
      <div style="color:#555;font-size:.73rem;margin-top:4px">📍 {coord_nota}</div>
      {_aviso_h}
    </div>
    <div style="text-align:center;min-width:110px">
      <div style="font-size:2.4rem;font-weight:800;color:{cor_nivel};line-height:1">{_s_score}</div>
      <div style="font-size:.68rem;color:#555">ClimaRisk Score</div>
      <span class="badge-{_nivel_l}">{res['nivel']}</span>
      <div style="font-size:.7rem;color:#888;margin-top:4px">UF {uf}: {uf_score_str}</div>
      <div style="font-size:.7rem;color:{_uf_dlta_cor};font-weight:600">{uf_delta_str}</div>
    </div>
  </div>
  <hr style="margin:12px 0">
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">
    <div style="background:#0A0A0A;border-radius:8px;padding:10px 12px">
      <div style="color:#888;font-size:.70rem;margin-bottom:4px">🌧 Precipitação (35%)</div>
      <div style="font-size:1.45rem;font-weight:800;color:#FFF;line-height:1.1">{_precip_v}</div>
      <div style="font-size:.73rem;color:{_c_prec};margin-top:4px">{_arrow_p} {_anom_p}% vs. normal · 30d</div>
      <div style="font-size:.65rem;color:#555;margin-top:3px">Normal: {res['normal_precip']:.0f} mm · Score: {_s_prec}/100</div>
    </div>
    <div style="background:#0A0A0A;border-radius:8px;padding:10px 12px">
      <div style="color:#888;font-size:.70rem;margin-bottom:4px">🌊 ENSO (25%)</div>
      <div style="font-size:1.45rem;font-weight:800;color:#FFF;line-height:1.1">{_oni_s} °C</div>
      <div style="font-size:.73rem;color:{_enso_cor};margin-top:4px">{_enso_lbl}</div>
      <div style="font-size:.65rem;color:#555;margin-top:3px">{_sens_lbl} · Score: {_s_enso}/100</div>
    </div>
    <div style="background:#0A0A0A;border-radius:8px;padding:10px 12px">
      <div style="color:#888;font-size:.70rem;margin-bottom:4px">🔥 Queimadas (25%)</div>
      <div style="font-size:1.45rem;font-weight:800;color:#FFF;line-height:1.1">{res['focos_50km']} focos</div>
      <div style="font-size:.73rem;color:#888;margin-top:4px">últimos 7d · raio 50 km</div>
      <div style="font-size:.65rem;color:#555;margin-top:3px">P95 ref.: 30 focos · Score: {_s_qm}/100</div>
    </div>
    <div style="background:#0A0A0A;border-radius:8px;padding:10px 12px">
      <div style="color:#888;font-size:.70rem;margin-bottom:4px">🌡 Temperatura (15%)</div>
      <div style="font-size:1.45rem;font-weight:800;color:#FFF;line-height:1.1">{_temp_v}</div>
      <div style="font-size:.73rem;color:{_c_temp};margin-top:4px">{_arrow_t} {_anom_t}°C vs. normal · 30d</div>
      <div style="font-size:.65rem;color:#555;margin-top:3px">Normal: {res['normal_temp']:.1f}°C · Score: {_s_temp}/100{_temp_note}</div>
    </div>
  </div>
  <div style="margin-top:8px;font-size:.71rem;color:#444;display:flex;justify-content:space-between">
    <span>Fonte: {res['fonte_clima']} · Granularidade: {precisao}</span>
    <span style="color:#555">{cache_lbl}</span>
  </div>
</div>
""")

# ── Coordenadas municipais ────────────────────────────────────────────────────
# importa dicionário COORDS e CAPITAIS_UF do arquivo de dados
import importlib.util, os
_spec = importlib.util.spec_from_file_location(
    "municipios_coords",
    os.path.join(os.path.dirname(__file__), "data", "municipios_coords.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
COORDS_MUNI   = _mod.COORDS
CAPITAIS_UF   = _mod.CAPITAIS_UF

# ── BallTree nearest-neighbor para municípios ─────────────────────────────────
@st.cache_resource
def build_muni_tree():
    from sklearn.neighbors import BallTree
    nomes  = list(COORDS_MUNI.keys())
    coords = np.radians([[v[0], v[1]] for v in COORDS_MUNI.values()])
    tree   = BallTree(coords, metric="haversine")
    return tree, nomes

def buscar_vizinho_mais_proximo(lat_query: float, lon_query: float):
    """Retorna (nome, lat, lon, dist_km) do município mapeado mais próximo."""
    tree, nomes = build_muni_tree()
    query   = np.radians([[lat_query, lon_query]])
    dist_r, idx = tree.query(query, k=1)
    dist_km = float(dist_r[0][0]) * 6_371
    nome    = nomes[int(idx[0][0])]
    lat_v, lon_v = COORDS_MUNI[nome]
    return nome, lat_v, lon_v, dist_km

# ── Constantes climáticas por UF (importadas de scripts/score_ufs.py) ─────────
try:
    _suf_spec = importlib.util.spec_from_file_location(
        "score_ufs", os.path.join(os.path.dirname(__file__), "scripts", "score_ufs.py"))
    _suf = importlib.util.module_from_spec(_suf_spec)
    _suf_spec.loader.exec_module(_suf)
    ENSO_SENS_UF         = _suf.ENSO_SENS_UF
    NORMAIS_PRECIP_MM_UF = _suf.NORMAIS_PRECIP_MM
    NORMAIS_TEMP_C_UF    = _suf.NORMAIS_TEMP_C
    UF_BBOX              = _suf.UF_BBOX
    UFS_DADOS_LIMITADOS  = _suf.UFS_DADOS_LIMITADOS
    AREA_AGRO_MIL_HA     = _suf.AREA_AGRO_MIL_HA
except Exception:
    ENSO_SENS_UF = NORMAIS_PRECIP_MM_UF = NORMAIS_TEMP_C_UF = UF_BBOX = {}
    UFS_DADOS_LIMITADOS = set()
    AREA_AGRO_MIL_HA    = {}

# Mapeamento UF → Região para Tab 2/4/5 que ainda usam visão regional
UF_REGIAO = {
    "MT":"Centro-Oeste","MS":"Centro-Oeste","GO":"Centro-Oeste","DF":"Centro-Oeste",
    "RS":"Sul","SC":"Sul","PR":"Sul",
    "MA":"Nordeste","PI":"Nordeste","CE":"Nordeste","RN":"Nordeste",
    "PB":"Nordeste","PE":"Nordeste","AL":"Nordeste","SE":"Nordeste","BA":"Nordeste",
    "MG":"Sudeste","ES":"Sudeste","RJ":"Sudeste","SP":"Sudeste",
    "AM":"Norte","PA":"Norte","AC":"Norte","RO":"Norte","RR":"Norte","AP":"Norte","TO":"Norte",
}

# ── Mecanismo ENSO por UF ─────────────────────────────────────────────────────
# Descreve o mecanismo de transmissão climática do ENSO para cada UF do Brasil.
# Fontes: CPTEC/INPE — boletins de teleconexões ENSO-Brasil; EMBRAPA — relatórios
# de impacto agroclimático; Cavalcanti et al. (2009); Marengo et al. (2011);
# Grimm (2000); Ropelewski & Halpert (1987); Nobre & Shukla (1996).
# Sinal do coef. ENSO: positivo → El Niño aumenta risco; negativo → La Niña aumenta risco.
# [CALIBRAÇÃO PRELIMINAR baseada em literatura — referências específicas a verificar
#  com climatologista em V2. Magnitude qualitativa (fraca/moderada/forte) sem número.]
ENSO_MECANISMO_UF = {
    # ── Sul ───────────────────────────────────────────────────────────────────
    "PR": {
        "regiao": "Sul",
        "el_nino": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "la_nina": {"sinal": "-", "tipo": "seca de primavera-verão", "magnitude": "forte"},
        "culturas_afetadas": ["soja 1ª safra", "milho 1ª safra", "trigo"],
        "comentario": (
            "PR sofre principalmente em La Niña — seca de primavera-verão atrasa o plantio de "
            "soja e milho e reduz a produtividade do trigo de inverno. Em El Niño, chuvas acima "
            "da média favorecem o desenvolvimento vegetativo mas podem causar excesso hídrico e "
            "atraso de colheita."
        ),
    },
    "SC": {
        "regiao": "Sul",
        "el_nino": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "la_nina": {"sinal": "-", "tipo": "seca de primavera-verão", "magnitude": "forte"},
        "culturas_afetadas": ["soja", "milho 1ª safra", "arroz irrigado"],
        "comentario": (
            "SC é altamente sensível a La Niña: déficit hídrico em primavera-verão afeta soja, "
            "milho e o arroz irrigado do Vale do Itajaí. Em El Niño, chuvas acima da média "
            "podem gerar excesso hídrico e favorecer fungos em grãos."
        ),
    },
    "RS": {
        "regiao": "Sul",
        "el_nino": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada a forte"},
        "la_nina": {"sinal": "-", "tipo": "seca severa de primavera-verão", "magnitude": "muito forte"},
        "culturas_afetadas": ["soja", "arroz irrigado", "trigo", "milho"],
        "comentario": (
            "RS tem a maior sensibilidade a La Niña de todo o Brasil — secas severas em "
            "primavera-verão comprometem soja e o maior polo arrozeiro do país. Em El Niño, "
            "chuvas acima da média beneficiam a produção mas elevam risco de cheias no Delta "
            "do Jacuí e nas lavouras de várzea."
        ),
    },
    # ── Sudeste ───────────────────────────────────────────────────────────────
    "SP": {
        "regiao": "Sudeste",
        "el_nino": {"sinal": "+", "tipo": "veranicos no interior e redução de PCC da cana", "magnitude": "fraca a moderada"},
        "la_nina": {"sinal": "~", "tipo": "padrão próximo ao normal", "magnitude": "fraca"},
        "culturas_afetadas": ["cana-de-açúcar", "laranja", "café (sul de SP)"],
        "comentario": (
            "SP sente El Niño principalmente via veranicos no interior paulista: queda de "
            "tonelada de cana por hectare (TCH) e atraso na maturação. Laranja é sensível a "
            "anomalias térmicas associadas a El Niño. La Niña tem efeito fraco em SP."
        ),
    },
    "MG": {
        "regiao": "Sudeste",
        "el_nino": {"sinal": "+", "tipo": "veranicos prolongados no Sul de MG", "magnitude": "moderada"},
        "la_nina": {"sinal": "~", "tipo": "variabilidade alta sem padrão claro", "magnitude": "fraca"},
        "culturas_afetadas": ["café arábica", "milho", "cana"],
        "comentario": (
            "MG é o maior produtor de café do Brasil (~50% da safra nacional) e o Sul de MG "
            "é fortemente afetado por veranicos em El Niño, que reduzem o enchimento dos grãos. "
            "La Niña não tem sinal claro em MG — variabilidade interna domina."
        ),
    },
    "ES": {
        "regiao": "Sudeste",
        "el_nino": {"sinal": "+", "tipo": "redução de chuvas no verão", "magnitude": "fraca a moderada"},
        "la_nina": {"sinal": "~", "tipo": "sem sinal consistente", "magnitude": "fraca"},
        "culturas_afetadas": ["café conilon", "eucalipto"],
        "comentario": (
            "ES sofre redução de chuvas em El Niño principalmente no verão, com impacto "
            "moderado no café conilon (mais resistente a seca que o arábica). "
            "La Niña não apresenta sinal consistente no ES — efeito oceânico local domina. "
            "[descrição regional Sudeste aplicada ao ES — calibração específica em V2]"
        ),
    },
    "RJ": {
        "regiao": "Sudeste",
        "el_nino": {"sinal": "+", "tipo": "redução de chuvas no verão", "magnitude": "fraca"},
        "la_nina": {"sinal": "~", "tipo": "sem sinal claro", "magnitude": "fraca"},
        "culturas_afetadas": ["cana", "fruticultura"],
        "comentario": (
            "RJ tem efeito ENSO fraco — a maritimidade e a orografia da Serra do Mar atenuam "
            "as teleconexões. El Niño pode reduzir levemente as chuvas de verão no interior "
            "fluminense. Exposição agrícola limitada na região metropolitana. "
            "[descrição regional Sudeste aplicada ao RJ — calibração específica em V2]"
        ),
    },
    # ── Centro-Oeste ──────────────────────────────────────────────────────────
    "MT": {
        "regiao": "Centro-Oeste",
        "el_nino": {"sinal": "-", "tipo": "atraso no início das chuvas (out–nov)", "magnitude": "moderada"},
        "la_nina": {"sinal": "~", "tipo": "padrão próximo ao normal", "magnitude": "fraca"},
        "culturas_afetadas": ["soja", "milho 2ª safra (safrinha)", "algodão"],
        "comentario": (
            "MT é o maior produtor de soja do Brasil (~28% da safra nacional) e o atraso das "
            "chuvas em El Niño — típico de outubro-novembro — compromete a janela de plantio. "
            "Isso causa efeito cascata na safrinha de milho: plantio atrasado da soja → "
            "colheita tardia → plantio da safrinha fora da janela ideal."
        ),
    },
    "MS": {
        "regiao": "Centro-Oeste",
        "el_nino": {"sinal": "-", "tipo": "atraso e irregularidade de chuvas", "magnitude": "moderada"},
        "la_nina": {"sinal": "~", "tipo": "padrão próximo ao normal", "magnitude": "fraca"},
        "culturas_afetadas": ["soja", "milho safrinha", "cana"],
        "comentario": (
            "MS sofre em El Niño pelo atraso e irregularidade das chuvas, com impacto em "
            "soja e milho safrinha. A cana, mais resistente a stress hídrico moderado, tem "
            "impacto menor. La Niña não altera significativamente o regime chuvoso do MS."
        ),
    },
    "GO": {
        "regiao": "Centro-Oeste",
        "el_nino": {"sinal": "-", "tipo": "atraso no início das chuvas", "magnitude": "moderada"},
        "la_nina": {"sinal": "~", "tipo": "padrão próximo ao normal", "magnitude": "fraca"},
        "culturas_afetadas": ["soja", "milho safrinha", "cana", "café (Sul Goiano)"],
        "comentario": (
            "GO tem padrão similar ao MT em El Niño: atraso das chuvas de outubro-novembro "
            "compromete janela de plantio da soja. O Sul Goiano tem polo emergente de café "
            "(Cristalina, altitude ~1000m) que é sensível a veranicos em El Niño."
        ),
    },
    "DF": {
        "regiao": "Centro-Oeste",
        "el_nino": {"sinal": "-", "tipo": "atraso e redução de chuvas no início da estação", "magnitude": "moderada"},
        "la_nina": {"sinal": "~", "tipo": "padrão próximo ao normal", "magnitude": "fraca"},
        "culturas_afetadas": ["horticultura", "soja (entorno do DF)"],
        "comentario": (
            "DF tem pouca área agrícola própria, mas o entorno (RIDE-DF) produz soja e grãos "
            "com sensibilidade ao atraso de chuvas de El Niño. Horticultura é impactada por "
            "deficit hídrico. La Niña tem efeito fraco. "
            "[descrição regional Centro-Oeste aplicada ao DF — calibração específica em V2]"
        ),
    },
    # ── Nordeste ──────────────────────────────────────────────────────────────
    "CE": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "seca severa no semiárido", "magnitude": "muito forte"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada a forte"},
        "culturas_afetadas": ["milho", "feijão", "algodão", "caju"],
        "comentario": (
            "CE é o estado mais afetado pelo ENSO no Brasil — El Niño inibe a ZCIT e "
            "praticamente suprime as chuvas do quadrimestre chuvoso (fev–mai). Secas "
            "históricas de 1983, 1998 e 2015-16 ocorreram em El Niño forte. La Niña "
            "tende a chuvas acima da média, beneficiando milho e feijão."
        ),
    },
    "RN": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "seca severa no semiárido", "magnitude": "muito forte"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "culturas_afetadas": ["milho", "feijão", "caju", "melão"],
        "comentario": (
            "RN segue o padrão nordestino clássico: El Niño inibe a ZCIT e suprime as chuvas "
            "do quadrimestre fev–mai. O semiárido do RN é especialmente vulnerável à seca de "
            "El Niño. Produção de melão no Vale do Açu é sensível a anomalias de temperatura. "
            "[descrição regional Nordeste aplicada ao RN — calibração específica em V2]"
        ),
    },
    "PB": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "seca no semiárido", "magnitude": "forte"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "culturas_afetadas": ["cana (litoral)", "algodão", "feijão"],
        "comentario": (
            "PB tem dois biomas agrícolas distintos: litoral úmido (cana, menos afetado) e "
            "semiárido interior (feijão, algodão, fortemente afetados por El Niño). "
            "La Niña beneficia especialmente o sertão. "
            "[descrição regional Nordeste aplicada à PB — calibração específica em V2]"
        ),
    },
    "PE": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "seca no semiárido, chuvas reduzidas na Zona da Mata", "magnitude": "forte"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "culturas_afetadas": ["cana (Zona da Mata)", "milho", "feijão (sertão)"],
        "comentario": (
            "PE combina dois regimes: a Zona da Mata úmida (cana) sente El Niño via redução "
            "das chuvas de outono-inverno; o sertão semiárido (feijão, milho) é severamente "
            "afetado pela seca de El Niño. La Niña beneficia ambas as zonas."
        ),
    },
    "AL": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "redução de chuvas", "magnitude": "moderada"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "culturas_afetadas": ["cana-de-açúcar", "mandioca"],
        "comentario": (
            "AL é o maior produtor de cana por área colhida do Nordeste e sofre com redução "
            "de chuvas em El Niño, que impacta o TCH (tonelada de cana por hectare). "
            "O litoral de AL é mais úmido que o semiárido e tem efeito ENSO moderado. "
            "[descrição regional Nordeste aplicada a AL — calibração específica em V2]"
        ),
    },
    "SE": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "redução de chuvas no quadrimestre úmido", "magnitude": "moderada"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "culturas_afetadas": ["cana", "laranja", "milho"],
        "comentario": (
            "SE é o menor estado do Nordeste e seu regime de chuvas é influenciado tanto "
            "pela ZCIT (El Niño inibe) quanto pela Zona de Convergência do Atlântico Sul. "
            "Cana e laranja são as principais culturas afetadas por El Niño. "
            "[descrição regional Nordeste aplicada a SE — calibração específica em V2]"
        ),
    },
    "BA": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "seca no semiárido baiano e Oeste da Bahia", "magnitude": "moderada a forte"},
        "la_nina": {"sinal": "+", "tipo": "chuvas próximas ao normal ou ligeiramente acima", "magnitude": "fraca"},
        "culturas_afetadas": ["soja (Oeste BA)", "algodão", "café (Chapada Diamantina)", "cana (litoral)"],
        "comentario": (
            "BA tem alta heterogeneidade: o Oeste baiano (MATOPIBA) produz soja e é afetado "
            "pelo atraso de chuvas de El Niño; o semiárido sofre com secas severas; o litoral "
            "úmido (cana) tem impacto menor. O café da Chapada Diamantina é sensível a "
            "veranicos em El Niño."
        ),
    },
    "MA": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "seca no Cerrado maranhense (MATOPIBA)", "magnitude": "moderada"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média no litoral", "magnitude": "fraca a moderada"},
        "culturas_afetadas": ["soja (Sul do MA)", "arroz", "milho"],
        "comentario": (
            "MA tem duas zonas: o litoral equatorial (úmido, menos afetado por ENSO) e o "
            "sul/cerrado (MATOPIBA — maior fronteira agrícola, afetado pelo atraso de chuvas "
            "de El Niño). La Niña tende a chuvas acima da média no litoral. "
            "[descrição regional Nordeste/Norte aplicada ao MA — calibração específica em V2]"
        ),
    },
    "PI": {
        "regiao": "Nordeste",
        "el_nino": {"sinal": "-", "tipo": "seca severa no semiárido piauiense", "magnitude": "forte"},
        "la_nina": {"sinal": "+", "tipo": "chuvas acima da média", "magnitude": "moderada"},
        "culturas_afetadas": ["soja (Sul do PI)", "feijão", "milho", "cajueiro"],
        "comentario": (
            "PI combina semiárido nordestino (feijão, milho, cajueiro — fortemente afetados "
            "pela seca de El Niño) com o Cerrado piauiense no Sul (soja, crescimento rápido, "
            "afetado pelo atraso de chuvas). La Niña beneficia especialmente o sertão."
        ),
    },
    # ── Norte ─────────────────────────────────────────────────────────────────
    "AM": {
        "regiao": "Norte",
        "el_nino": {"sinal": "-", "tipo": "seca amazônica intensa, redução do nível dos rios", "magnitude": "forte a muito forte"},
        "la_nina": {"sinal": "+", "tipo": "cheias extremas, transbordamento de rios", "magnitude": "forte"},
        "culturas_afetadas": ["açaí", "castanha-do-pará", "pesca fluvial", "pecuária (várzea)"],
        "comentario": (
            "AM é o estado mais afetado por El Niño no Norte: secas de 1997-98, 2005, 2010 "
            "e 2015-16 causaram colapso do transporte fluvial, mortandade de peixes e impacto "
            "severo no extrativismo. La Niña causa cheias históricas (2009, 2012, 2021) com "
            "perdas em pecuária de várzea."
        ),
    },
    "PA": {
        "regiao": "Norte",
        "el_nino": {"sinal": "-", "tipo": "seca amazônica e redução fluvial no oeste do PA", "magnitude": "moderada a forte"},
        "la_nina": {"sinal": "+", "tipo": "cheias no oeste, chuvas acima no sul", "magnitude": "moderada"},
        "culturas_afetadas": ["soja (Sul do PA — MATOPIBA)", "açaí", "pecuária"],
        "comentario": (
            "PA é heterogêneo: o oeste amazônico sofre com seca em El Niño (hidrologia, pesca), "
            "enquanto o sul (nova fronteira de soja) sente o atraso de chuvas do Cerrado. "
            "La Niña causa cheias no oeste. Logística fluvial (hidrovia Tapajós-Amazonas) é "
            "afetada por ambos os extremos."
        ),
    },
    "AC": {
        "regiao": "Norte",
        "el_nino": {"sinal": "-", "tipo": "seca intensa — dentre as mais severas do Norte", "magnitude": "forte"},
        "la_nina": {"sinal": "+", "tipo": "cheias extremas", "magnitude": "forte"},
        "culturas_afetadas": ["castanha-do-pará", "seringueira", "pecuária"],
        "comentario": (
            "AC foi o epicentro da seca de 2005 (a mais severa da Amazônia até então) e "
            "sofreu novamente em 2010 e 2015-16, todas associadas a El Niño. La Niña gera "
            "cheias no Rio Juruá e Purus. Extrativismo e pecuária extensiva são os principais "
            "ativos afetados."
        ),
    },
    "RO": {
        "regiao": "Norte",
        "el_nino": {"sinal": "-", "tipo": "seca moderada, atraso de chuvas", "magnitude": "moderada"},
        "la_nina": {"sinal": "+", "tipo": "cheias no vale do Madeira", "magnitude": "moderada"},
        "culturas_afetadas": ["soja (crescimento rápido)", "café robusta", "cacau", "pecuária"],
        "comentario": (
            "RO experimenta crescimento acelerado da fronteira agrícola de soja e a seca de "
            "El Niño atrasa as chuvas de outubro-novembro, impactando o plantio. O vale do "
            "Madeira sofre cheias em La Niña. Café robusta (conilon) é relativamente "
            "resistente mas perde em secas prolongadas."
        ),
    },
    "TO": {
        "regiao": "Norte",
        "el_nino": {"sinal": "-", "tipo": "atraso no início das chuvas (Cerrado)", "magnitude": "moderada"},
        "la_nina": {"sinal": "~", "tipo": "padrão próximo ao normal", "magnitude": "fraca"},
        "culturas_afetadas": ["soja", "milho", "pecuária de corte"],
        "comentario": (
            "TO está na transição entre a Amazônia e o Cerrado e segue o padrão do Centro-Oeste "
            "em El Niño: atraso das chuvas de outubro-novembro afeta plantio de soja. "
            "La Niña tem efeito fraco em TO. Pecuária extensiva é afetada por irregularidades "
            "no regime de chuvas que impactam a pastagem."
        ),
    },
    "AP": {
        "regiao": "Norte",
        "el_nino": {"sinal": "-", "tipo": "efeito moderado — regime controlado pela ITCZ equatorial", "magnitude": "fraca a moderada"},
        "la_nina": {"sinal": "+", "tipo": "cheias", "magnitude": "fraca a moderada"},
        "culturas_afetadas": ["arroz", "pecuária extensiva", "pesca"],
        "comentario": (
            "AP tem regime de chuvas fortemente influenciado pela ITCZ equatorial, o que atenua "
            "as teleconexões ENSO. El Niño tem efeito moderado. La Niña pode gerar cheias no "
            "baixo Amazonas/foz. Baixa cobertura agrícola comercial. "
            "[descrição regional Norte aplicada ao AP — calibração específica em V2]"
        ),
    },
    "RR": {
        "regiao": "Norte",
        "el_nino": {"sinal": "-", "tipo": "seca moderada — regime misto (Caribe + ITCZ)", "magnitude": "fraca a moderada"},
        "la_nina": {"sinal": "+", "tipo": "cheias, especialmente no Rio Branco", "magnitude": "fraca a moderada"},
        "culturas_afetadas": ["pecuária extensiva (lavrados)", "arroz", "soja (incipiente)"],
        "comentario": (
            "RR tem regime climático único: influenciado pelo Caribe (norte) e pela Amazônia "
            "(sul), com estação seca pronunciada de dez–mar. El Niño intensifica essa seca; "
            "La Niña pode gerar cheias no Rio Branco. Baixa cobertura agrícola comercial. "
            "[descrição regional Norte aplicada ao RR — calibração específica em V2]"
        ),
    },
}

# ── Score helpers (espelham scripts/score_ufs.py) ─────────────────────────────
def _score_prec_app(anomalia_pct: float) -> float:
    a = anomalia_pct
    if a <= -50:   return min(100, 90 + abs(a + 50) * 0.2)
    elif a < -20:  return 40 + (abs(a) - 20) * (50 / 30)
    elif a <= 20:  return max(0, 10 + abs(a) * 1.5)
    elif a <= 80:  return 20 + (a - 20) * (40 / 60)
    else:          return min(100, 60 + (a - 80) * 0.3)

def _score_enso_app(oni: float, uf: str) -> float:
    sens = ENSO_SENS_UF.get(uf, 0.5) if ENSO_SENS_UF else 0.5
    return round(max(0., min(100., (oni * sens + 1.5) / 3.0 * 100)), 1)

def _score_temp_app(anomalia_temp: float, uf: str) -> float:
    # slope 14 satura em +6.8°C (era 25, saturava em +3.2°C — muito cedo)
    if uf in ("RS", "SC", "PR") and anomalia_temp < -1.5:
        return min(100, round(abs(anomalia_temp) * 22, 1))
    return min(100, max(0, round(anomalia_temp * 14 + 5, 1)))

def focos_em_raio(q_df_local: "pd.DataFrame", lat_c: float, lon_c: float, raio_km: float = 50.0) -> int:
    """Conta focos FIRMS dentro de raio_km de (lat_c, lon_c) via haversine vetorizado.
    Aceita colunas 'latitude'/'longitude' (NASA FIRMS) ou 'lat'/'lon' (legado)."""
    _lat_col = next((c for c in ("latitude","lat") if c in q_df_local.columns), None)
    _lon_col = next((c for c in ("longitude","lon") if c in q_df_local.columns), None)
    if q_df_local.empty or not _lat_col or not _lon_col:
        return 0
    lat_r = np.radians(lat_c)
    lats  = np.radians(q_df_local[_lat_col].values)
    lons  = np.radians(q_df_local[_lon_col].values)
    dlat  = lats - lat_r
    dlon  = lons - np.radians(lon_c)
    a     = np.sin(dlat/2)**2 + np.cos(lat_r) * np.cos(lats) * np.sin(dlon/2)**2
    return int((2 * 6371 * np.arcsin(np.sqrt(np.clip(a, 0, 1))) <= raio_km).sum())

# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_oni():
    p = Path("data/oni_index.csv")
    return pd.read_csv(p, parse_dates=["data"]) if p.exists() else pd.DataFrame()

@st.cache_data(ttl=3600)
def load_score():
    p = Path("data/score_regioes.csv")
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

@st.cache_data(ttl=3600)
def load_anomalia():
    p = Path("data/anomalia_chuva.csv")
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

@st.cache_data(ttl=3600)
def load_queimadas():
    p = Path("data/queimadas.csv")
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

@st.cache_data(ttl=3600)
def load_municipios():
    p = Path("data/municipios_ibge.csv")
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

@st.cache_data(ttl=3600)
def load_score_ufs():
    p = Path("data/score_ufs.csv")
    return pd.read_csv(p) if p.exists() else pd.DataFrame()

def compute_uf_physical(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enriquece score_ufs_df com valores físicos derivados e strings pré-formatadas
    para tooltip rico no mapa choropleth do Dashboard.

    Colunas adicionadas:
      normal_precip_mm  — normal climatológica INMET 1991-2020 para o mês atual
      precip_obs_mm     — precipitação observada estimada (inverso da anomalia %)
      normal_temp_c     — normal de temperatura para o mês atual
      temp_obs_c        — temperatura observada estimada
      tt_*              — strings pré-formatadas para hovertemplate Plotly

    Não usa @st.cache_data para evitar dependência circular com globals importados
    de scripts/score_ufs.py após carregamento do módulo.
    """
    if df.empty:
        return df
    mes = date.today().month
    out = df.copy()

    out["normal_precip_mm"] = out["uf"].map(
        lambda u: (NORMAIS_PRECIP_MM_UF.get(u, [100]*12)[mes - 1]
                   if NORMAIS_PRECIP_MM_UF else 100)
    )
    out["precip_obs_mm"] = out.apply(
        lambda r: round(r["normal_precip_mm"] * (1 + r["anomalia_precip_pct"] / 100), 1)
        if pd.notna(r.get("anomalia_precip_pct")) else None, axis=1
    )
    out["normal_temp_c"] = out["uf"].map(
        lambda u: (NORMAIS_TEMP_C_UF.get(u, [25]*12)[mes - 1]
                   if NORMAIS_TEMP_C_UF else 25)
    )
    out["temp_obs_c"] = out.apply(
        lambda r: round(r["normal_temp_c"] + r["anomalia_temp_c"], 1)
        if pd.notna(r.get("anomalia_temp_c")) else None, axis=1
    )

    def _tt_precip(r):
        obs = r.get("precip_obs_mm")
        pct = r.get("anomalia_precip_pct")
        if obs is None or pd.isna(obs) or pct is None or pd.isna(pct):
            return "normal climatológica não disponível — comparação omitida"
        norm  = r["normal_precip_mm"]
        arrow = "▲" if pct > 0 else "▼"
        return f"{obs:.0f} mm (30d) · normal: {norm:.0f} mm · {arrow} {pct:+.1f}% vs. normal"

    def _tt_temp(r):
        obs   = r.get("temp_obs_c")
        delta = r.get("anomalia_temp_c")
        if obs is None or pd.isna(obs) or delta is None or pd.isna(delta):
            return "normal climatológica não disponível — comparação omitida"
        norm  = r["normal_temp_c"]
        arrow = "▲" if delta > 0 else "▼"
        return f"{obs:.1f}°C (30d) · normal: {norm:.1f}°C · {arrow} {delta:+.1f}°C vs. normal"

    def _tt_queimadas(r):
        return f"{int(r['focos_7d']):,} focos (7d · bbox UF)"

    def _tt_enso(r):
        oni  = float(r["oni_ref"])
        lbl  = _enso_label(oni)
        uf   = r["uf"]
        sens = (ENSO_SENS_UF or {}).get(uf, 0.5)
        mag  = "alta" if abs(sens) >= 0.7 else ("média" if abs(sens) >= 0.4 else "baixa")
        dire = "El Niño" if sens > 0 else "La Niña"
        return f"ONI {oni:+.2f}°C ({lbl}) · Sensib. {uf}: {mag} a {dire}"

    _nivel_icon = {"CRITICO": "CRITICO ⚠", "ATENCAO": "ATENÇÃO !", "NORMAL": "NORMAL ✓"}
    out["tt_regiao"]    = out["uf"].map(lambda u: UF_REGIAO.get(u, "—"))
    out["tt_precip"]    = out.apply(_tt_precip,    axis=1)
    out["tt_temp"]      = out.apply(_tt_temp,      axis=1)
    out["tt_queimadas"] = out.apply(_tt_queimadas, axis=1)
    out["tt_enso"]      = out.apply(_tt_enso,      axis=1)
    out["tt_nivel"]     = out["nivel"].map(lambda n: _nivel_icon.get(n, n))
    return out

@st.cache_data(ttl=86400, show_spinner=False)
def calcular_score_municipal_od(
    ibge_code: int, lat: float, lon: float, uf: str, dias: int = 30
) -> dict:
    """
    ClimaRisk Score on-demand para um município. Cache de 24h keyed pelo código IBGE.

    Componentes:
      Precipitação (35%): Open-Meteo ERA5 na lat/lon exata vs. normal INMET 1991-2020 por UF
      ENSO (25%):         ONI × sensibilidade da UF (CPTEC/INPE Atlas Climático)
      Queimadas (25%):    Focos FIRMS em raio de 50km. P95 = 30 focos/7d (Cerrado/Norte).
      Temperatura (15%):  Open-Meteo ERA5 vs. normal INMET 1991-2020 por UF

    Fallback: se Open-Meteo falhar, componentes afetadas ficam em 0 (neutro).
    Vizinho mais próximo (BallTree) só é usado se coordenada exata não estiver em COORDS_MUNI.
    """
    import time as _time
    from datetime import datetime as _dt
    _t0 = _time.time()

    fim = date.today() - timedelta(days=1)
    ini = fim - timedelta(days=dias - 1)
    mes = fim.month

    # ── Open-Meteo: precipitação + temperatura ────────────────────────────────
    precip_obs = temp_obs = None
    fonte_clima = "indisponível"
    try:
        r = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={"latitude": lat, "longitude": lon,
                    "start_date": ini.isoformat(), "end_date": fim.isoformat(),
                    "daily": ["precipitation_sum","temperature_2m_max","temperature_2m_min"],
                    "timezone": "America/Sao_Paulo"},
            timeout=15,
        )
        r.raise_for_status()
        daily  = r.json().get("daily", {})
        p_vals = [v for v in daily.get("precipitation_sum",  []) if v is not None]
        tmax   = [v for v in daily.get("temperature_2m_max", []) if v is not None]
        tmin   = [v for v in daily.get("temperature_2m_min", []) if v is not None]
        if p_vals:
            precip_obs  = round(sum(p_vals), 1)
            fonte_clima = "Open-Meteo/ERA5"
        if tmax and tmin:
            temp_obs = round(sum((a+b)/2 for a,b in zip(tmax, tmin)) / len(tmax), 2)
    except Exception:
        pass

    # ── Normais por UF ────────────────────────────────────────────────────────
    _nprec = NORMAIS_PRECIP_MM_UF.get(uf, [100]*12) if NORMAIS_PRECIP_MM_UF else [100]*12
    _ntemp = NORMAIS_TEMP_C_UF.get(uf,   [25]*12)   if NORMAIS_TEMP_C_UF    else [25]*12
    normal_precip = _nprec[mes - 1] * (dias / 30)
    normal_temp   = _ntemp[mes - 1]

    # ── Anomalias ─────────────────────────────────────────────────────────────
    anomalia_pct  = round((precip_obs - normal_precip) / max(normal_precip, 1) * 100, 1) \
                    if precip_obs is not None else None
    anomalia_temp = round(temp_obs - normal_temp, 2) if temp_obs is not None else None

    # ── Focos no raio de 50km ─────────────────────────────────────────────────
    q_path     = Path("data/queimadas.csv")
    _q_local   = pd.read_csv(q_path) if q_path.exists() else pd.DataFrame()
    focos_50km = focos_em_raio(_q_local, lat, lon, raio_km=50.0)

    # ── ONI mais recente ──────────────────────────────────────────────────────
    oni_path    = Path("data/oni_index.csv")
    _oni_local  = pd.read_csv(oni_path, parse_dates=["data"]) if oni_path.exists() else pd.DataFrame()
    oni_val     = float(_oni_local.dropna(subset=["ONI"]).iloc[-1]["ONI"]) \
                  if not _oni_local.empty else 0.0

    # ── Score das 4 componentes ───────────────────────────────────────────────
    s_prec   = _score_prec_app(anomalia_pct if anomalia_pct is not None else 0.0)
    s_enso   = _score_enso_app(oni_val, uf)
    # Log-scale: 0 focos→0, 50 focos→74, 100 focos→87, 200 focos→100 (ceiling)
    # Ceiling 200 focos/50km representa situação de incêndio severo no entorno imediato.
    # Log-scale captura melhor a distribuição assimétrica de focos do que escala linear.
    import math as _math
    s_queima = (0.0 if focos_50km == 0
                else min(100, round(_math.log1p(focos_50km) / _math.log1p(200) * 100, 1)))
    s_temp   = _score_temp_app(anomalia_temp if anomalia_temp is not None else 0.0, uf)

    score = round(s_prec*0.35 + s_enso*0.25 + s_queima*0.25 + s_temp*0.15, 1)
    nivel = "CRITICO" if score >= 70 else ("ATENCAO" if score >= 45 else "NORMAL")

    return {
        "score": score, "nivel": nivel,
        "comp_prec":      round(s_prec, 1),
        "comp_enso":      round(s_enso, 1),
        "comp_queimadas": round(s_queima, 1),
        "comp_temp":      round(s_temp, 1),
        "anomalia_pct":   anomalia_pct,
        "anomalia_temp":  anomalia_temp,
        "precip_obs":     precip_obs,
        "temp_obs":       temp_obs,
        "normal_precip":  round(normal_precip, 1),
        "normal_temp":    round(normal_temp, 1),
        "focos_50km":     focos_50km,
        "oni_val":        oni_val,
        "fonte_clima":    fonte_clima,
        "elapsed_s":      round(_time.time() - _t0, 1),
        "computed_at":    _dt.now().isoformat(),
    }

def refresh_data():
    with st.spinner("Atualizando dados…"):
        base = Path(__file__).parent
        for script in ["enso_noaa.py","queimadas_inpe.py","inmet_anomalia.py","score.py","score_ufs.py"]:
            subprocess.run([sys.executable, str(base/"scripts"/script)], cwd=str(base))
    st.cache_data.clear()
    st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
col_logo, col_refresh = st.columns([8,1])
with col_logo:
    html_card("""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px">
  <div style="background:#00B4A2;border-radius:10px;width:40px;height:40px;
              display:flex;align-items:center;justify-content:center;font-size:20px">🌿</div>
  <div>
    <span style="font-size:1.5rem;font-weight:800;color:#FFF">Clima<span style="color:#00B4A2">Credit</span></span>
    <span style="color:#555;font-size:.8rem;margin-left:10px">GAS Challenge 2026.1 · XP Inc.</span>
  </div>
</div>""")
with col_refresh:
    if st.button("↺ Atualizar", help="Rebaixa dados de todas as fontes"):
        refresh_data()

st.markdown("---")

oni_df        = load_oni()
score_df      = load_score()
anom_df       = load_anomalia()
q_df          = load_queimadas()
muni_df       = load_municipios()
score_ufs_df  = compute_uf_physical(load_score_ufs())

has_score     = not score_df.empty
has_oni       = not oni_df.empty
has_score_ufs = not score_ufs_df.empty

# ── Sanity check: detecta falha silenciosa nas componentes ────────────────────
if has_score_ufs:
    _zero_q = (score_ufs_df["comp_queimadas"] == 0).mean()
    _zero_p = (score_ufs_df["comp_prec"]      == 0).mean()
    if _zero_q > 0.80:
        st.warning(
            "⚠ **Componente Queimadas com cobertura suspeita** — "
            f"{_zero_q:.0%} dos estados com focos = 0. "
            "Clique em ↺ Atualizar para reprocessar os dados."
        )
    if _zero_p > 0.80:
        st.warning(
            "⚠ **Componente Precipitação com cobertura suspeita** — "
            f"{_zero_p:.0%} dos estados com score = 0. "
            "Verifique a conectividade com Open-Meteo/ERA5."
        )

t1, t2, t3, t4, t5, t6 = st.tabs([
    "📊 Dashboard", "🌱 Calendário Agrícola",
    "📈 ClimaRisk Score", "🚨 Alertas", "💰 Tradutor Financeiro",
    "🗺️ Mapa por Variável",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════
with t1:
    # ── Métricas / Cards de resumo Brasil ─────────────────────────────────────
    if has_oni:
        oni_row    = oni_df.dropna(subset=["ONI"]).iloc[-1]
        oni_val    = float(oni_row["ONI"])
        oni_per    = date.fromisoformat(str(oni_row["data"])[:10]).strftime("%b/%Y")
        enso_label = _enso_label(oni_val)
    else:
        oni_val, oni_per, enso_label = 0.0, "—", "Sem dados"

    total_focos = len(q_df[q_df["regiao"] != "Outro"]) if not q_df.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    if has_score_ufs and "precip_obs_mm" in score_ufs_df.columns:
        # Cards com valores físicos reais ponderados por área agrícola (IBGE 2017)
        _w       = score_ufs_df["uf"].map(
            lambda u: (AREA_AGRO_MIL_HA.get(u, 1000) if AREA_AGRO_MIL_HA else 1000))
        _wtot    = _w.sum()
        _anom_p  = score_ufs_df["anomalia_precip_pct"].fillna(0)
        _anom_t  = score_ufs_df["anomalia_temp_c"].fillna(0)
        _anom_p_wtd = float((_anom_p * _w).sum() / _wtot)
        _anom_t_wtd = float((_anom_t * _w).sum() / _wtot)
        _prec_avg   = float(score_ufs_df["precip_obs_mm"].mean())
        _temp_avg   = float(score_ufs_df["temp_obs_c"].mean())
        _n_alta     = sum(1 for u in score_ufs_df["uf"]
                          if abs((ENSO_SENS_UF or {}).get(u, 0)) >= 0.7)
        _p_dir = "Chuvoso" if _anom_p_wtd > 10 else ("Seco" if _anom_p_wtd < -10 else "Normal")
        _t_dir = ("Acima da normal" if _anom_t_wtd > 0.5
                  else ("Abaixo da normal" if _anom_t_wtd < -0.5 else "Próximo da normal"))
        c1.metric("🌧 Precipitação Brasil",
                  f"{_prec_avg:.0f} mm (30d)",
                  f"{_anom_p_wtd:+.1f}% vs. normal · {_p_dir}")
        c2.metric("🌡 Temperatura Brasil",
                  f"{_temp_avg:.1f}°C (30d)",
                  f"{_anom_t_wtd:+.1f}°C vs. normal · {_t_dir}")
        c3.metric("🔥 Queimadas (7d)",
                  f"{total_focos:,} focos",
                  "FIRMS/VIIRS · NASA")
        c4.metric(f"🌊 ENSO — {enso_label}",
                  f"ONI {oni_val:+.2f}°C",
                  f"{_n_alta} UFs em alta sensibilidade")
    else:
        # Fallback genérico quando score_ufs não disponível
        score_max = score_ufs_df["score"].max() if has_score_ufs else (score_df["score"].max() if has_score else 0)
        top_label = score_ufs_df.iloc[0]["uf"] if has_score_ufs else (score_df.iloc[0]["regiao"] if has_score else "—")
        med_anom  = anom_df["anomalia_pct"].mean() if not anom_df.empty else 0.0
        c1.metric("Índice ENSO (ONI)", f"{oni_val:+.2f} °C", enso_label)
        c2.metric("Score máx. de risco", f"{score_max:.0f}/100", top_label)
        c3.metric("Focos ativos (7d)", f"{total_focos:,}", "Brasil — FIRMS/VIIRS")
        c4.metric("Anomalia precip. média", f"{med_anom:+.1f}%",
                  "Chuvoso" if med_anom > 10 else ("Seco" if med_anom < -10 else "Normal"))

    st.markdown("---")

    col_map, col_gauge = st.columns([3, 2])

    with col_map:
        st.subheader("Mapa de Risco por UF")
        if has_score_ufs:
            _map_df = score_ufs_df.rename(columns={"uf":"estado"}).copy()
            # Colunas tooltip rico (pré-computadas por compute_uf_physical)
            _cd_cols = ["estado", "tt_regiao", "tt_precip", "tt_temp",
                        "tt_queimadas", "tt_enso", "tt_nivel"]
            for _c in _cd_cols:
                if _c not in _map_df.columns:
                    _map_df[_c] = "—"
            fig_map = px.choropleth(
                _map_df,
                geojson="https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson",
                locations="estado", featureidkey="properties.sigla",
                color="score",
                color_continuous_scale=[[0,"#00B4A2"],[0.45,"#F5A623"],[0.7,"#FF4444"],[1,"#8B0000"]],
                range_color=(0,100),
                custom_data=_cd_cols,
            )
            fig_map.update_traces(
                hovertemplate=(
                    "<b>%{customdata[0]}</b>  ·  %{customdata[1]}<br>"
                    "ClimaRisk Score: <b>%{z:.0f}/100</b>  ·  %{customdata[6]}<br>"
                    "──────────────────────────────<br>"
                    "🌧 Precip.: %{customdata[2]}<br>"
                    "🌡 Temp.: %{customdata[3]}<br>"
                    "🔥 Queimadas: %{customdata[4]}<br>"
                    "🌊 ENSO: %{customdata[5]}<br>"
                    "<extra></extra>"
                )
            )
            fig_map.update_geos(fitbounds="locations", visible=False, bgcolor="#0A0A0A")
            fig_map.update_layout(**PLOTLY_LAYOUT, height=420,
                coloraxis_colorbar=dict(title="Score",
                    tickfont=dict(color="#FFF"), titlefont=dict(color="#FFF")))
            st.plotly_chart(fig_map, use_container_width=True)
            _ufs_lim = score_ufs_df[score_ufs_df["dados_limitados"]==True]["uf"].tolist()
            if _ufs_lim:
                st.caption(f"⚠ Dados limitados: {', '.join(_ufs_lim)} — baixa cobertura agrícola/meteorológica")
        elif has_score:
            st.info("Score por UF indisponível — exibindo score regional. Clique em ↺ Atualizar.")
        else:
            st.info("Rode os módulos de dados para gerar o mapa.")

    with col_gauge:
        st.subheader("Status ENSO")
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=oni_val,
            delta={"reference":0,"valueformat":"+.2f"},
            title={"text":f"{enso_label} · {oni_per}","font":{"color":"#FFF","size":14}},
            number={"suffix":" °C","font":{"color":"#00B4A2","size":28}},
            gauge={
                "axis":{"range":[-3,3],"tickcolor":"#555","tickfont":{"color":"#AAA"}},
                "bar":{"color":"#00B4A2"}, "bgcolor":"#111111", "bordercolor":"#222",
                "steps":[
                    {"range":[-3,-1.5],"color":"#1a3a6b"},{"range":[-1.5,-0.5],"color":"#1a4a8a"},
                    {"range":[-0.5,0.5],"color":"#1a1a1a"},{"range":[0.5,1.5],"color":"#6b2a1a"},
                    {"range":[1.5,3],"color":"#8b0000"},
                ],
                "threshold":{"line":{"color":"#FFF","width":2},"value":oni_val},
            },
        ))
        fig_gauge.update_layout(**PLOTLY_LAYOUT, height=280)
        st.plotly_chart(fig_gauge, use_container_width=True)

        st.markdown("**Histórico ONI (12 meses)**")
        if has_oni:
            oni_hist = oni_df.tail(12)[["data","ONI"]].copy()
            fig_oni  = px.bar(oni_hist, x="data", y="ONI", color="ONI",
                              color_continuous_scale=[[0,"#1a3a6b"],[0.5,"#1a1a1a"],[1,"#8b0000"]],
                              range_color=(-2,2))
            fig_oni.add_hline(y=0.5,  line_dash="dot", line_color="#F5A623", annotation_text="El Niño")
            fig_oni.add_hline(y=-0.5, line_dash="dot", line_color="#4A90D9", annotation_text="La Niña")
            fig_oni.update_layout(**PLOTLY_LAYOUT, height=200, showlegend=False,
                                  coloraxis_showscale=False, xaxis_title="", yaxis_title="ONI (°C)")
            st.plotly_chart(fig_oni, use_container_width=True)

    # ── Anomalia precip regional ──────────────────────────────────────────────
    if not anom_df.empty:
        st.markdown("---")
        st.subheader("Anomalia de Precipitação por Região (últimos 30 dias)")
        fig_prec = px.bar(
            anom_df.sort_values("anomalia_pct"),
            x="anomalia_pct", y="regiao", orientation="h",
            color="anomalia_pct",
            color_continuous_scale=[[0,"#8b0000"],[0.3,"#F5A623"],[0.5,"#111"],[0.7,"#1a6b3a"],[1,"#00B4A2"]],
            range_color=(-80,80),
            text=anom_df.sort_values("anomalia_pct")["anomalia_pct"].apply(lambda x: f"{x:+.1f}%"),
            labels={"anomalia_pct":"Anomalia (%)","regiao":""},
        )
        fig_prec.update_layout(**PLOTLY_LAYOUT, height=260, coloraxis_showscale=False,
                               xaxis_title="Anomalia vs. Normal 1991-2020 (%)")
        fig_prec.add_vline(x=0, line_color="#555")
        st.plotly_chart(fig_prec, use_container_width=True)

    # ── M1 & M2 — Busca por município ─────────────────────────────────────────
    st.markdown("---")
    with st.expander("🔍 Busca por Município — Risco e Anomalia de Precipitação", expanded=False):
        st.caption(
            "Selecione um município para consultar o ClimaRisk Score da região e a anomalia de "
            "precipitação calculada com base nas coordenadas geográficas do município via Open-Meteo/ERA5."
        )

        if muni_df.empty:
            st.warning("Base de municípios não carregada. Verifique data/municipios_ibge.csv.")
        else:
            # Monta lista "Nome — UF" para o selectbox
            muni_df_sorted = muni_df.sort_values("nome").reset_index(drop=True)
            opcoes = (muni_df_sorted["nome"] + " — " + muni_df_sorted["uf"]).tolist()

            col_sel, col_btn = st.columns([4, 1])
            with col_sel:
                escolha = st.selectbox(
                    "Digite ou selecione o município",
                    opcoes,
                    index=None,
                    placeholder="Ex: Sorriso — MT",
                    key="muni_search",
                )
            with col_btn:
                st.markdown("<br>", unsafe_allow_html=True)
                buscar = st.button("Consultar", key="btn_muni")

            if escolha and buscar:
                nome_muni, uf = [s.strip() for s in escolha.split("—", 1)]
                row_muni = muni_df_sorted[
                    (muni_df_sorted["nome"] == nome_muni) &
                    (muni_df_sorted["uf"] == uf)
                ]
                if row_muni.empty:
                    st.error("Município não encontrado na base IBGE.")
                else:
                    regiao_muni = row_muni.iloc[0]["regiao"]
                    micro       = row_muni.iloc[0].get("microrregiao", "—")
                    ibge_code   = int(row_muni.iloc[0]["id"]) if "id" in row_muni.columns else 0

                    # Coordenadas: exato → BallTree vizinho mais próximo
                    coords = COORDS_MUNI.get(nome_muni)
                    aviso_vizinho = ""
                    if coords:
                        lat, lon   = coords
                        coord_nota = f"{lat:.2f}°, {lon:.2f}° (coordenada exata)"
                        precisao   = "municipal"
                    else:
                        lat_ref, lon_ref = CAPITAIS_UF.get(uf, (-15.0, -50.0))
                        viz_nome, lat, lon, dist_km = buscar_vizinho_mais_proximo(lat_ref, lon_ref)
                        coord_nota = f"{lat:.2f}°, {lon:.2f}° (vizinho mais próximo: {viz_nome})"
                        precisao   = "estimada"
                        aviso_vizinho = (
                            f"⚠ Dados estimados a partir de {viz_nome}, a {dist_km:.0f} km"
                            if dist_km < 100 else
                            f"⚠⚠ Aproximação grosseira — vizinho a {dist_km:.0f} km ({viz_nome})"
                        )

                    # Score on-demand com cache 24h
                    with st.spinner(f"Calculando ClimaRisk Score para {nome_muni}…"):
                        res = calcular_score_municipal_od(ibge_code, lat, lon, uf, dias=30)

                    # Indicador de cache
                    from datetime import datetime as _dt2
                    _computed = _dt2.fromisoformat(res["computed_at"])
                    _delta_s  = (_dt2.now() - _computed).total_seconds()
                    cache_lbl = f"✓ Cache 24h (calculado {_computed.strftime('%d/%m %H:%M')})" \
                                if _delta_s > 5 else f"🔄 Calculado agora ({res['elapsed_s']}s)"

                    # Comparação com UF
                    uf_score_str = "—"
                    uf_delta_str = ""
                    if has_score_ufs:
                        _row_uf = score_ufs_df[score_ufs_df["uf"] == uf]
                        if not _row_uf.empty:
                            _uf_score = float(_row_uf.iloc[0]["score"])
                            uf_score_str = f"{_uf_score:.0f}"
                            _delta = res["score"] - _uf_score
                            uf_delta_str = f"{'↑' if _delta>0 else '↓'} {abs(_delta):.0f} pts vs. {uf}"

                    render_card_municipio(
                        nome_muni=nome_muni, uf=uf, micro=micro,
                        regiao_muni=regiao_muni, coord_nota=coord_nota,
                        aviso_vizinho=aviso_vizinho, res=res,
                        uf_score_str=uf_score_str, uf_delta_str=uf_delta_str,
                        precisao=precisao, cache_lbl=cache_lbl,
                    )

    # ── Escopo e horizonte temporal ───────────────────────────────────────────
    with st.expander("ℹ️ Sobre o escopo e horizonte temporal da ferramenta", expanded=False):
        st.markdown("""
**Escopo de risco**

O ClimaCredit V1 endereça deliberadamente o **risco climático físico** no segmento de crédito agro brasileiro:

- **Risco físico agudo:** eventos climáticos extremos discretos (secas, inundações, ondas de calor, queimadas)
- **Risco físico crônico:** mudanças graduais de regime climático moduladas por ENSO

**Risco de transição** (precificação de carbono, CBAM, regulação de emissões agrícolas) está fora do escopo V1 e previsto para V2 do roadmap.

---

**Horizontes temporais**

A ferramenta opera em três horizontes complementares:

- **Monitoramento contínuo (quase-real):** focos de calor 7d (NASA FIRMS), precipitação e temperatura 30d (ERA5), ONI mensal (NOAA)
- **Stress test prospectivo (6–12 meses):** cenários hipotéticos El Niño Forte e La Niña Forte projetam o impacto na próxima safra
- **Projeção climática longa (V2+):** integração com cenários SSP/IPCC AR6 e NGFS, prevista para próxima versão

---

**Ancoragem em frameworks internacionais**

Convergente com **NGFS** (risco físico agudo + crônico), **TCFD** (pilar de métricas/metas) e **BCB Resolução 139/2021** (gerenciamento de risco climático em instituições financeiras).
        """)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — CALENDÁRIO AGRÍCOLA × RISCO
# ═══════════════════════════════════════════════════════════════════════════════
with t2:
    st.subheader("Calendário Agrícola × Risco Climático Atual")
    st.caption("P = Plantio · D = Desenvolvimento · C = Colheita · — = Entressafra · N/D = não cultivado em escala comercial  |  Fonte: CONAB/MAPA, EMBRAPA")

    # Fonte: CONAB Calendário de Plantio e Colheita; EMBRAPA Cultivos; IBGE PAM
    # N/D (não se aplica): Cana/Norte, Café/CO, Café/Sul, Algodão/Sul, Algodão/Sudeste,
    #                       Algodão/Norte, Arroz/Sudeste, Feijão/Norte
    # Entradas ausentes no dict = N/D → aparecem como NaN no heatmap (cinza no Plotly)
    CALENDARIO = {
        # ── Soja ──────────────────────────────────────────────────────────────
        ("Soja",    "Centro-Oeste"): {"P":[10,11],"D":[12,1,2],"C":[3,4]},
        ("Soja",    "Sul"):          {"P":[10,11],"D":[12,1,2],"C":[3,4]},
        ("Soja",    "Nordeste"):     {"P":[12,1], "D":[2,3],   "C":[4,5]},
        ("Soja",    "Sudeste"):      {"P":[10,11],"D":[12,1],  "C":[2,3]},
        ("Soja",    "Norte"):        {"P":[11,12],"D":[1,2,3], "C":[3,4,5]},
        # ── Milho 1ª ──────────────────────────────────────────────────────────
        ("Milho 1ª","Centro-Oeste"): {"P":[10,11],"D":[12,1,2],"C":[3,4]},
        ("Milho 1ª","Sul"):          {"P":[9,10], "D":[11,12,1],"C":[2,3]},
        ("Milho 1ª","Nordeste"):     {"P":[5,6],  "D":[7,8],   "C":[9,10]},
        ("Milho 1ª","Sudeste"):      {"P":[10,11],"D":[12,1],  "C":[2,3]},
        ("Milho 1ª","Norte"):        {"P":[11,12],"D":[1,2,3], "C":[3,4,5]},
        # ── Cana ──────────────────────────────────────────────────────────────
        ("Cana",    "Centro-Oeste"): {"P":[3,4,5],"D":[6,7,8,9,10,11],"C":[5,6,7,8,9,10,11]},
        ("Cana",    "Sul"):          {"P":[8,9],  "D":[10,11,12,1,2,3,4,5,6],"C":[7,8,9]},
        ("Cana",    "Nordeste"):     {"P":[9,10], "D":[11,12,1,2,3,4,5,6,7],"C":[8,9]},
        ("Cana",    "Sudeste"):      {"P":[8,9],  "D":[10,11,12,1,2,3,4,5,6],"C":[7,8,9]},
        # Cana/Norte — N/D (não cultivada em escala comercial na Amazônia)
        # ── Café ──────────────────────────────────────────────────────────────
        ("Café",    "Sudeste"):      {"P":[10,11],"D":[12,1,2,3,4,5,6],"C":[7,8,9]},
        ("Café",    "Nordeste"):     {"P":[11,12],"D":[1,2,3,4,5,6],"C":[7,8,9]},
        ("Café",    "Norte"):        {"P":[4,5],  "D":[6,7,8,9,10,11],"C":[7,8,9]},
        # Café/CO — marginal: polo emergente em GO (Sul goiano/Cristalina, altitude 900-1100m)
        #   e DF; crescimento acelerado na última década — CRA em GO já financia café.
        #   Fonte: IBGE PAM 2022 — GO produz ~1% da safra nacional, tendência crescente.
        ("Café",    "Centro-Oeste"): {"P":[10,11],"D":[12,1,2,3,4,5,6],"C":[7,8,9],
                                      "status": "marginal"},
        # Café/Sul — N/D: clima frio/geada incompatível com Coffea arabica comercial (RS, SC, PR)
        # ── Algodão ───────────────────────────────────────────────────────────
        ("Algodão", "Centro-Oeste"): {"P":[12,1], "D":[2,3,4],"C":[6,7,8]},
        ("Algodão", "Nordeste"):     {"P":[1,2],  "D":[3,4,5],"C":[7,8,9]},
        # Algodão/Sul, Algodão/Sudeste, Algodão/Norte — N/D
        # ── Arroz ─────────────────────────────────────────────────────────────
        ("Arroz",   "Sul"):          {"P":[9,10,11],"D":[12,1,2],"C":[2,3,4]},
        ("Arroz",   "Centro-Oeste"): {"P":[10,11,12],"D":[1,2],  "C":[3,4,5]},
        ("Arroz",   "Nordeste"):     {"P":[12,1,2],"D":[3,4],    "C":[5,6]},
        ("Arroz",   "Norte"):        {"P":[11,12,1],"D":[2,3],   "C":[4,5]},
        # Arroz/Sudeste — marginal: produção existe no Vale do Ribeira (SP — Registro/Eldorado)
        #   e em algumas microrregiões de MG, mas volume é < 1% da produção nacional.
        #   Relevante para monitorar tendência; insuficiente para garantias primárias em CRA.
        #   Fonte: IBGE PAM 2022 — SP contribui ~0,3% do arroz nacional.
        ("Arroz",   "Sudeste"):      {"P":[9,10,11],"D":[12,1,2],"C":[2,3,4],
                                      "status": "marginal"},
        # ── Feijão ────────────────────────────────────────────────────────────
        ("Feijão",  "Sul"):          {"P":[8,9,10],"D":[11,12], "C":[1,2]},
        ("Feijão",  "Sudeste"):      {"P":[10,11], "D":[12,1],  "C":[2,3]},
        ("Feijão",  "Centro-Oeste"): {"P":[1,2],   "D":[3,4],   "C":[5,6]},
        ("Feijão",  "Nordeste"):     {"P":[12,1],  "D":[2,3],   "C":[4,5]},
        # Feijão/Norte — N/D (produção insignificante para portfolio CRA/LCA)
        # ── Trigo ─────────────────────────────────────────────────────────────
        ("Trigo",   "Sul"):          {"P":[6,7],  "D":[8,9],    "C":[10,11]},   # PR/RS/SC — cultura de inverno
        ("Trigo",   "Centro-Oeste"): {"P":[4,5],  "D":[6,7],    "C":[8,9],
                                      "status": "marginal"},  # GO emergente (Cristalina); < 2% nacional
        # Trigo/Sudeste, Trigo/Nordeste, Trigo/Norte — N/D
    }
    CULTURAS = ["Soja","Milho 1ª","Cana","Café","Algodão","Arroz","Feijão","Trigo"]
    REGIOES  = ["Centro-Oeste","Sul","Nordeste","Sudeste","Norte"]

    col_fc, col_fr = st.columns([2,2])
    with col_fc: cult_sel = st.multiselect("Filtrar por cultura", CULTURAS, default=CULTURAS)
    with col_fr: reg_sel  = st.multiselect("Filtrar por região", REGIOES, default=REGIOES)

    score_map_cal = score_df.set_index("regiao")["score"].to_dict() if has_score else {}
    nivel_map_cal = score_df.set_index("regiao")["nivel"].to_dict() if has_score else {}
    mes_atual     = date.today().month

    rows_cal = []
    for cultura in cult_sel:
        for regiao in reg_sel:
            cal = CALENDARIO.get((cultura, regiao))
            if cal is None:
                # N/D: combinação não cultivada em escala comercial nesta região
                rows_cal.append({
                    "Cultura": cultura, "Região": regiao, "Fase Atual": "N/D",
                    "Score Risco": float("nan"),
                    "Nível": "N/D",
                })
                continue
            fase = ("Plantio" if mes_atual in cal.get("P",[]) else
                    "Desenvolvimento" if mes_atual in cal.get("D",[]) else
                    "Colheita" if mes_atual in cal.get("C",[]) else "—")
            _is_marginal = cal.get("status") == "marginal"
            rows_cal.append({
                "Cultura": cultura, "Região": regiao,
                "Fase Atual": f"{fase} ⊘" if _is_marginal else fase,
                "Score Risco": score_map_cal.get(regiao, 0),
                "Nível": nivel_map_cal.get(regiao, "—"),
            })

    if rows_cal:
        df_cal = pd.DataFrame(rows_cal)
        # Tabela: mostra todas as combinações incluindo N/D
        styled = (df_cal.style
            .map(lambda v: {"CRITICO":"background:#3a0f0f;color:#FF4444",
                                  "ATENCAO":"background:#3a2a0f;color:#F5A623",
                                  "NORMAL": "background:#0f2a20;color:#00B4A2",
                                  "N/D":    "color:#444"}.get(v,""), subset=["Nível"])
            .map(lambda v: {"Plantio":"color:#7B61FF","Desenvolvimento":"color:#4ADE80",
                                  "Colheita":"color:#F5A623","—":"color:#555",
                                  "N/D":"color:#444"}.get(v.replace(" ⊘",""),""), subset=["Fase Atual"])
            .background_gradient(subset=["Score Risco"], cmap="RdYlGn_r", vmin=0, vmax=100))
        st.dataframe(styled, use_container_width=True, height=400)

        st.markdown("---")
        st.markdown(
            "**Heatmap Score de Risco — Cultura × Região**&nbsp;&nbsp;"
            "<span style='color:#777;font-size:.8rem'>"
            "🟢→🟡→🔴 score baixo a alto &nbsp;·&nbsp; "
            "<b>⊘</b> cobertura baixa (produção marginal) &nbsp;·&nbsp; "
            "<span style='background:#2a2a2a;padding:0 5px;border-radius:2px'>▨</span> não cultivado"
            "</span>",
            unsafe_allow_html=True,
        )

        _cultures_h = [c for c in CULTURAS if c in cult_sel]
        _regions_h  = [r for r in REGIOES  if r in reg_sel]

        # Monta as matrizes z, texto em célula e tooltip por célula
        _z_h   = []
        _txt_h = []
        _hov_h = []
        for _cult in _cultures_h:
            _z_row, _txt_row, _hov_row = [], [], []
            for _reg in _regions_h:
                _e  = CALENDARIO.get((_cult, _reg))
                _sc = score_map_cal.get(_reg, 0) if score_map_cal else 50.0
                if _e is None:
                    # N/D total — célula será coberta por shape cinza hachurado
                    _z_row.append(float("nan"))
                    _txt_row.append("")
                    _hov_row.append(
                        f"{_cult} × {_reg}<br>"
                        "Não cultivado em escala comercial nesta região"
                    )
                elif _e.get("status") == "marginal":
                    _fase_h = ("Plantio"       if mes_atual in _e.get("P",[]) else
                               "Desenvolvimento" if mes_atual in _e.get("D",[]) else
                               "Colheita"       if mes_atual in _e.get("C",[]) else "—")
                    _z_row.append(_sc)
                    _txt_row.append(f"{_sc:.0f} ⊘")
                    _hov_row.append(
                        f"{_cult} × {_reg}<br>"
                        f"Score: {_sc:.0f}/100 · Fase: {_fase_h}<br>"
                        f"Cobertura baixa — produção marginal nesta região (IBGE PAM)"
                    )
                else:
                    _fase_h = ("Plantio"       if mes_atual in _e.get("P",[]) else
                               "Desenvolvimento" if mes_atual in _e.get("D",[]) else
                               "Colheita"       if mes_atual in _e.get("C",[]) else "—")
                    _z_row.append(_sc)
                    _txt_row.append(f"{_sc:.0f}")
                    _hov_row.append(
                        f"{_cult} × {_reg}<br>Score: {_sc:.0f}/100 · Fase: {_fase_h}"
                    )
            _z_h.append(_z_row)
            _txt_h.append(_txt_row)
            _hov_h.append(_hov_row)

        fig_heat = go.Figure(go.Heatmap(
            z=_z_h, x=_regions_h, y=_cultures_h,
            text=_txt_h, texttemplate="%{text}",
            hovertext=_hov_h,
            hovertemplate="%{hovertext}<extra></extra>",
            colorscale=[[0,"#00B4A2"],[0.45,"#F5A623"],[0.7,"#FF4444"],[1,"#8B0000"]],
            zmin=0, zmax=100,
            showscale=True,
            xgap=2, ygap=2,
            textfont=dict(size=11),
        ))

        # Overlay para células N/D: cinza hachurado + label
        for _i, _cult in enumerate(_cultures_h):
            for _j, _reg in enumerate(_regions_h):
                if CALENDARIO.get((_cult, _reg)) is None:
                    # Fundo cinza escuro
                    fig_heat.add_shape(
                        type="rect", layer="above",
                        x0=_j - 0.5, x1=_j + 0.5,
                        y0=_i - 0.5, y1=_i + 0.5,
                        fillcolor="#252525",
                        line=dict(color="#3a3a3a", width=1),
                    )
                    # Hachura diagonal (×) para distinção visual de "score baixo"
                    fig_heat.add_shape(
                        type="line", layer="above",
                        x0=_j - 0.42, y0=_i - 0.42,
                        x1=_j + 0.42, y1=_i + 0.42,
                        line=dict(color="#484848", width=1.2),
                    )
                    fig_heat.add_shape(
                        type="line", layer="above",
                        x0=_j - 0.42, y0=_i + 0.42,
                        x1=_j + 0.42, y1=_i - 0.42,
                        line=dict(color="#484848", width=1.2),
                    )
                    # Label N/D sobre a hachura
                    fig_heat.add_annotation(
                        x=_reg, y=_cult, text="N/D",
                        showarrow=False, xref="x", yref="y",
                        font=dict(color="#555", size=9),
                    )

        fig_heat.update_layout(
            **PLOTLY_LAYOUT,
            height=max(300, len(_cultures_h) * 50 + 80),
            xaxis_title="", yaxis_title="",
        )
        st.plotly_chart(fig_heat, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — CLIMARISK SCORE POR UF
# ═══════════════════════════════════════════════════════════════════════════════
with t3:
    st.subheader("ClimaRisk Score por UF")
    gran = st.radio("Granularidade", ["Por UF (estado)","Por Região (agregado)"],
                    horizontal=True, key="t3_gran")

    use_ufs = gran == "Por UF (estado)" and has_score_ufs
    use_reg = gran == "Por Região (agregado)" and has_score

    if not use_ufs and not use_reg:
        st.warning("Dados não disponíveis. Clique em ↺ Atualizar.")
    else:
        if use_ufs:
            df_t3   = score_ufs_df.copy()
            id_col  = "uf"
            n_items = "estados"
        else:
            df_t3   = score_df.rename(columns={
                "regiao":"uf", "anomalia_pct":"anomalia_precip_pct"})
            df_t3["dados_limitados"] = False
            id_col  = "uf"
            n_items = "regiões"

        col_rank, col_decom = st.columns([2, 3])

        with col_rank:
            st.markdown(f"**Ranking — {len(df_t3)} {n_items}**")
            for _, row in df_t3.iterrows():
                _cor  = NIVEL_COR.get(row["nivel"], "#555")
                _lim  = (' <span style="background:#2a2000;color:#F5A623;border-radius:4px;'
                         'padding:1px 6px;font-size:.66rem">dados limitados</span>'
                         if row.get("dados_limitados", False) else "")
                _ap   = row.get("anomalia_precip_pct", None)
                _albl = f"{_ap:+.1f}%" if pd.notna(_ap) else "—"
                _sc   = f"{row['score']:.0f}"
                _niv  = row['nivel'].lower()
                _oni  = f"{row['oni_ref']:+.2f}"
                _id   = row[id_col]
                html_card(f"""
<div style="background:#111;border-radius:10px;padding:12px 16px;margin:4px 0;
            display:flex;align-items:center;justify-content:space-between">
  <div>
    <b style="font-size:1rem">{_id}</b>{_lim}<br>
    <span style="color:#555;font-size:.78rem">
      🌧 {_albl} &nbsp;|&nbsp;
      🔥 {int(row['focos_7d'])} focos &nbsp;|&nbsp;
      🌊 ONI {_oni}
    </span>
  </div>
  <div style="text-align:right">
    <div style="font-size:1.8rem;font-weight:800;color:{_cor}">{_sc}</div>
    <span class="badge-{_niv}">{row['nivel']}</span>
  </div>
</div>""")

        with col_decom:
            st.markdown("**Decomposição do Score**")
            label = "Estado" if use_ufs else "Região"
            sel   = st.selectbox(label, df_t3[id_col].tolist(), key="score_uf_sel")
            row_s = df_t3[df_t3[id_col] == sel].iloc[0]
            comps = pd.DataFrame({
                "Componente": ["Precipitação (35%)","ENSO (25%)","Queimadas (25%)","Temperatura (15%)"],
                "Score":      [row_s["comp_prec"],row_s["comp_enso"],row_s["comp_queimadas"],row_s["comp_temp"]],
                "Peso":       [0.35, 0.25, 0.25, 0.15],
            })
            comps["Contribuição"] = (comps["Score"] * comps["Peso"]).round(1)
            fig_bar = px.bar(comps, x="Score", y="Componente", orientation="h", color="Score",
                             color_continuous_scale=[[0,"#00B4A2"],[0.5,"#F5A623"],[1,"#FF4444"]],
                             range_color=(0,100), text="Score")
            fig_bar.update_layout(**PLOTLY_LAYOUT, height=250,
                                  coloraxis_showscale=False, xaxis_range=[0,100])
            st.plotly_chart(fig_bar, use_container_width=True)
            st.dataframe(
                comps[["Componente","Score","Peso","Contribuição"]].style
                    .background_gradient(subset=["Score"], cmap="RdYlGn_r", vmin=0, vmax=100)
                    .format({"Score":"{:.1f}","Peso":"{:.0%}","Contribuição":"{:.1f}"}),
                use_container_width=True, hide_index=True)

            # Valores físicos observados — hierarquia: valor real > anomalia > score
            if use_ufs:
                lim_flag  = row_s.get("dados_limitados", False)
                _t3_ap    = row_s.get("anomalia_precip_pct", None)
                _t3_at    = row_s.get("anomalia_temp_c", None)
                _t3_focos = int(row_s["focos_7d"])
                _t3_oni   = float(row_s["oni_ref"])
                _t3_sens  = ENSO_SENS_UF.get(sel, 0.5) if ENSO_SENS_UF else 0.5

                st.markdown("**Valores físicos observados (30d · ERA5/FIRMS)**")
                _vc1, _vc2, _vc3, _vc4 = st.columns(4)
                _vc1.metric(
                    "🌧 Precip. vs. normal",
                    format_or_dash(_t3_ap, "+.1f") + "%",
                    help="Anomalia percentual de precipitação acumulada nos últimos 30 dias vs. normal INMET 1991-2020"
                )
                _vc2.metric(
                    "🌊 ONI / ENSO",
                    f"{_t3_oni:+.2f} °C",
                    _enso_label(_t3_oni),
                    help=f"Índice Oceânico Niño 3.4 (NOAA). Sensibilidade {sel}: {fmt_sensibilidade(_t3_sens)}"
                )
                _vc3.metric(
                    "🔥 Focos 7d (bbox UF)",
                    f"{_t3_focos:,}",
                    help="Focos de calor NASA FIRMS/VIIRS dentro do bounding box da UF nos últimos 7 dias"
                )
                _vc4.metric(
                    "🌡 Temp. vs. normal",
                    format_or_dash(_t3_at, "+.1f") + "°C",
                    help="Anomalia de temperatura média nos últimos 30 dias vs. normal INMET 1991-2020"
                )
                if lim_flag:
                    st.caption("⚠ Dados limitados para esta UF — baixa cobertura agrícola/meteorológica")

        st.markdown("---")
        st.markdown("**Evolução Histórica do ONI — Risco por UF**")
        if has_oni and ENSO_SENS_UF:
            _ufs_hist   = df_t3[id_col].tolist()
            _uf_hist    = st.selectbox("UF/Região (sensibilidade ENSO)", _ufs_hist, key="hist_uf")
            _sens       = ENSO_SENS_UF.get(_uf_hist, 0.5) if use_ufs else \
                          {"Centro-Oeste":+0.7,"Sul":-0.8,"Nordeste":+0.9,
                           "Sudeste":+0.4,"Norte":+0.6}.get(_uf_hist, 0.5)
            oni_h       = oni_df.tail(120).copy()
            oni_h["score_proxy"] = oni_h["ONI"].apply(
                lambda v: max(0, min(100, (v * _sens + 1.5) / 3.0 * 100)))
            # ── Mecanismo específico da UF ────────────────────────────────
            _mec = ENSO_MECANISMO_UF.get(_uf_hist, {}) if use_ufs else {}
            _el  = _mec.get("el_nino", {})
            _la  = _mec.get("la_nina", {})
            _sinal = (
                f"El Niño → {_el.get('tipo','seca')}" if _sens > 0
                else f"La Niña → {_la.get('tipo','seca')}"
            ) if _mec else ("El Niño → seca" if _sens > 0 else "La Niña → seca")
            fig_hist = go.Figure()
            fig_hist.add_trace(go.Scatter(
                x=oni_h["data"], y=oni_h["score_proxy"],
                fill="tozeroy", line_color="#00B4A2",
                fillcolor="rgba(0,180,162,0.15)", name="Score ENSO proxy"))
            fig_hist.add_hline(y=70, line_dash="dot", line_color="#FF4444",
                annotation_text="CRÍTICO", annotation_font_color="#FF4444")
            fig_hist.add_hline(y=45, line_dash="dot", line_color="#F5A623",
                annotation_text="ATENÇÃO", annotation_font_color="#F5A623")
            fig_hist.update_layout(**PLOTLY_LAYOUT, height=250,
                title=f"{_uf_hist}: sensibilidade {_sens:+.3f} ({_sinal})",
                xaxis_title="", yaxis_title="Score proxy (0-100)")
            st.plotly_chart(fig_hist, use_container_width=True)

            # ── Card interpretativo ENSO ──────────────────────────────────
            if _mec:
                _regiao    = _mec.get("regiao", "")
                _culturas  = ", ".join(_mec.get("culturas_afetadas", []))
                _coment    = _mec.get("comentario", "")
                _el_sinal  = _el.get("sinal", "")
                _el_tipo   = _el.get("tipo", "")
                _el_mag    = _el.get("magnitude", "")
                _la_sinal  = _la.get("sinal", "")
                _la_tipo   = _la.get("tipo", "")
                _la_mag    = _la.get("magnitude", "")
                _badge_el  = ("#FF7043" if "+" in _el_sinal else "#42A5F5")
                _badge_la  = ("#FF7043" if "+" in _la_sinal else "#42A5F5")
                _badge_sty = "padding:2px 8px;border-radius:4px;font-weight:600;color:#fff;font-size:0.85em"
                html_card(f"""
                    <div style="background:#1e2130;border-radius:8px;padding:14px 18px;margin-top:4px;border-left:4px solid #00B4A2">
                      <div style="font-size:1.0em;font-weight:700;color:#e0e0e0;margin-bottom:6px">
                        🌊 ENSO — {_uf_hist} &nbsp;<span style="color:#aaa;font-weight:400;font-size:0.88em">({_regiao})</span>
                      </div>
                      <div style="font-size:0.88em;color:#b0bec5;margin-bottom:8px">
                        Sensibilidade ao ONI: <b style="color:#e0e0e0">{_sens:+.3f}</b>
                        &nbsp;&nbsp;|&nbsp;&nbsp; Proxy de risco sobe <b style="color:#e0e0e0">{abs(_sens)*100:.0f}</b> pts por unidade de ONI
                      </div>
                      <div style="display:flex;gap:18px;margin-bottom:10px;flex-wrap:wrap">
                        <div>
                          <span style="background:{_badge_el};{_badge_sty}">El Niño {_el_sinal}</span>
                          &nbsp;<span style="color:#cfd8dc;font-size:0.88em">{_el_tipo} &nbsp;·&nbsp; <i>{_el_mag}</i></span>
                        </div>
                        <div>
                          <span style="background:{_badge_la};{_badge_sty}">La Niña {_la_sinal}</span>
                          &nbsp;<span style="color:#cfd8dc;font-size:0.88em">{_la_tipo} &nbsp;·&nbsp; <i>{_la_mag}</i></span>
                        </div>
                      </div>
                      <div style="font-size:0.85em;color:#90a4ae;margin-bottom:6px">
                        🌾 <b>Culturas afetadas:</b> {_culturas}
                      </div>
                      <div style="font-size:0.85em;color:#b0bec5;border-top:1px solid #2e3450;padding-top:8px;margin-top:4px">
                        {_coment}
                      </div>
                      <div style="font-size:0.75em;color:#546e7a;margin-top:6px">
                        [CALIBRAÇÃO PRELIMINAR — fontes: CPTEC/INPE, EMBRAPA, Cavalcanti (2009), Grimm (2000)]
                      </div>
                    </div>
                """)
            else:
                html_card(f"""
                    <div style="background:#1e2130;border-radius:8px;padding:12px 16px;margin-top:4px;border-left:4px solid #00B4A2">
                      <span style="color:#b0bec5;font-size:0.88em">
                        🌊 <b>{_uf_hist}</b> — Sensibilidade ONI: <b>{_sens:+.3f}</b> &nbsp;·&nbsp; {_sinal}
                      </span>
                    </div>
                """)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — PAINEL DE ALERTAS
# ═══════════════════════════════════════════════════════════════════════════════
with t4:
    st.subheader("Painel de Alertas Climáticos")
    if not has_score:
        st.warning("Dados de score não disponíveis.")
    else:
        oni_alerta = float(oni_df.dropna(subset=["ONI"]).iloc[-1]["ONI"]) if has_oni else 0.0

        # ── Mapeamentos auxiliares para textos diferenciados por perfil ──────
        # Commodities de maior peso por região (relevância para CRA/LCA e futuros B3/CBOT)
        _COMM_MAP = {
            "Centro-Oeste": ("Soja, Milho, Algodão", "SFI/CCM/ALF"),
            "Sul":          ("Soja, Milho, Trigo",   "SFI/CCM/TRF"),
            "Nordeste":     ("Cana, Algodão, Milho", "ACF/ALF/CCM"),
            "Sudeste":      ("Café, Cana",           "ICF/ACF"),
            "Norte":        ("Soja, Milho",          "SFI/CCM"),
        }
        # Tickers do EQUITY_DB com maior exposição por região (derivado dos relatórios anuais)
        _TICK_MAP = {
            "Centro-Oeste": "SLCE3 (55%), AGRO3 (45%), BEEF3 (35%)",
            "Sul":          "TTEN3 (80%), KLBN3 (65%), CAML3 (50%)",
            "Nordeste":     "MDIA3 (55%), AGRO3 (30%), SUZB3 (20%)",
            "Sudeste":      "SMTO3 (55%), RAIZ4 (55%), CSAN3 (55%)",
            "Norte":        "BEEF3 (10%), JBSS3 (5%) — exposição baixa na região",
        }
        # ENSO: commodities e tickers mais sensíveis por fase
        _ENSO_COMM = {
            "El Niño": ("Café (SE), Soja/Milho (CO/NE)", "ICF/SFI/CCM"),
            "La Niña": ("Soja/Milho (Sul), Trigo",       "SFI/CCM/TRF"),
        }
        _ENSO_TICK = {
            "El Niño": "SMTO3, SLCE3, AGRO3, RAIZ4",
            "La Niña": "TTEN3, CAML3, KLBN3, BRFS3",
        }
        _PD_BASE_ALERTA  = 0.03
        _FATOR_ALERTA    = {"NORMAL": 1.0, "ATENCAO": 1.4, "CRITICO": 2.2}

        ALERTAS_BASE = []
        for _, r in score_df.iterrows():
            regiao, score, nivel, anom, focos = (
                r["regiao"], r["score"], r["nivel"],
                r["anomalia_pct"], int(r["focos_7d"])
            )
            _comms, _futuros = _COMM_MAP.get(regiao, ("—", "—"))
            _ticks   = _TICK_MAP.get(regiao, "—")
            _fator   = _FATOR_ALERTA.get(nivel, 1.0)
            _pd_aj   = _PD_BASE_ALERTA * _fator
            _pd_delt = (_pd_aj - _PD_BASE_ALERTA) * 100

            if anom < -30:
                ALERTAS_BASE.append({
                    "regiao": regiao, "fenomeno": "Déficit hídrico",
                    "nivel": nivel, "score": score,
                    "descricao": f"Precipitação {anom:+.1f}% abaixo da normal 1991-2020.",
                    "categorias": ["Crédito Agro", "Equity Agro", "Commodities"],
                    # ── Crédito Agro: linguagem de gestão de carteira CRA/LCA ─
                    "impacto_credito": (
                        f"PD ajustada para exposições CRA/LCA na região estimada em {_pd_aj:.1%}/ano "
                        f"({_fator:.1f}× base setorial 3,0% — +{_pd_delt:.1f}pp). "
                        f"Lavouras temporárias com CPR físico têm maior risco de execução."
                    ),
                    "acao_credito": (
                        "Revisar provisões IFRS9 em operações com vencimento ≤18 meses na região. "
                        "Considerar colateral adicional em novas originações de CPR/CRA."
                    ),
                    # ── Equity Agro: linguagem de gestor de fundo de ações ────
                    "impacto_equity": (
                        f"Tickers com exposição relevante à região: {_ticks}. "
                        f"Seca {abs(anom):.0f}% abaixo da normal pressiona volume colhido "
                        f"e EBITDA no próximo trimestre. Risco de revisão do guidance de safra."
                    ),
                    "acao_equity": (
                        "Reduzir alocação tática nos tickers mais expostos. "
                        "Preferir empresas com diversificação geográfica (BRFS3, JBSS3). "
                        "Monitorar avisos de safra e calls de resultado."
                    ),
                    # ── Commodities: linguagem de trader de futuros agro ──────
                    "impacto_commodities": (
                        f"Pressão altista esperada em {_comms} no horizonte de 1-3 meses. "
                        f"Déficit hídrico de {abs(anom):.0f}% abaixo da normal reduz oferta regional."
                    ),
                    "acao_commodities": (
                        f"Avaliar posição long em contratos próximos ({_futuros}). "
                        "Revisar hedge ratio em operações físico-papel. "
                        "Cross-check com estoques CONAB/USDA antes de posicionar."
                    ),
                })

            if anom > 40:
                ALERTAS_BASE.append({
                    "regiao": regiao, "fenomeno": "Excesso hídrico",
                    "nivel": "ATENCAO", "score": score,
                    "descricao": f"Precipitação {anom:+.1f}% acima da normal.",
                    "categorias": ["Crédito Agro", "Commodities"],
                    # ── Crédito Agro ─────────────────────────────────────────
                    "impacto_credito": (
                        "Risco de perda de qualidade na colheita e atraso na entrega de CPR físico. "
                        "Pressão sobre garantias em operações de financiamento rural na região."
                    ),
                    "acao_credito": (
                        "Monitorar prazos de entrega em CPR físico com colheita prevista nos próximos 60 dias. "
                        "Acionar cláusula de vistoria de colateral se aplicável ao contrato."
                    ),
                    # ── Commodities ──────────────────────────────────────────
                    "impacto_commodities": (
                        f"Excesso hídrico pode reduzir qualidade e atrasar colheita de {_comms}. "
                        "Efeito de curto prazo no prêmio de base local (spread porto/interior)."
                    ),
                    "acao_commodities": (
                        f"Monitorar spread físico-futuro (basis local) em {_futuros}. "
                        "Cautela em contratos com entrega na janela afetada. "
                        "Acompanhar boletins meteorológicos de 10 dias."
                    ),
                })

            if focos > 200:
                ALERTAS_BASE.append({
                    "regiao": regiao, "fenomeno": "Focos de queimada elevados",
                    "nivel": nivel if focos > 500 else "ATENCAO", "score": score,
                    "descricao": f"{focos} focos de calor nos últimos 7 dias (NASA FIRMS/VIIRS).",
                    "categorias": ["Crédito Agro", "Equity Agro"],
                    # ── Crédito Agro ─────────────────────────────────────────
                    "impacto_credito": (
                        f"{focos} focos/7d elevam risco de sinistro em lavouras e pastagens. "
                        "Possível impacto em covenants ambientais de CRA com certificação ESG "
                        "emitidos na região."
                    ),
                    "acao_credito": (
                        "Verificar cláusulas ambientais em CRA/CPR emitidos na região. "
                        "Acionar due diligence ambiental em novas originações. "
                        "Avaliar risco de inadimplência por perda ou embargo de colateral produtivo."
                    ),
                    # ── Equity Agro ──────────────────────────────────────────
                    "impacto_equity": (
                        f"Tickers com exposição à região: {_ticks}. "
                        f"{focos} focos/7d — risco reputacional e regulatório (embargo IBAMA, "
                        "exclusão de índices ESG) pode impactar custo de dívida e acesso ao mercado de capitais."
                    ),
                    "acao_equity": (
                        "Monitorar comunicados das empresas expostas sobre áreas afetadas. "
                        "Verificar composição de fundos ESG — risco de exclusão. "
                        "Atenção a CRA/CRI com covenants ambientais vinculados a estas companhias."
                    ),
                })

        if abs(oni_alerta) >= 0.5:
            sinal       = "El Niño" if oni_alerta > 0 else "La Niña"
            _enso_comms, _enso_fut = _ENSO_COMM.get(sinal, ("—", "—"))
            _enso_ticks = _ENSO_TICK.get(sinal, "—")
            _nivel_enso = "ATENCAO" if abs(oni_alerta) < 1.5 else "CRITICO"
            ALERTAS_BASE.append({
                "regiao": "Brasil", "fenomeno": f"ENSO ativo — {sinal}",
                "nivel": _nivel_enso, "score": abs(oni_alerta) / 3 * 100,
                "descricao": f"ONI atual: {oni_alerta:+.2f} °C — {sinal}.",
                "categorias": ["Crédito Agro", "Equity Agro", "Commodities"],
                # ── Crédito Agro ─────────────────────────────────────────────
                "impacto_credito": (
                    f"{sinal} ativo (ONI={oni_alerta:+.2f}) historicamente eleva inadimplência "
                    f"agrícola nas regiões mais sensíveis. PD setorial ajustada estimada em "
                    f"4,2–6,6%/ano (vs. base 3,0%) — estimativa preliminar baseada em correlação histórica."
                ),
                "acao_credito": (
                    "Reavaliar scoring climático de carteiras CRA/LCA nas regiões mais expostas ao ENSO. "
                    "Priorizar colateral real em novas originações. "
                    "Revisar limites de concentração regional antes do próximo comitê de crédito."
                ),
                # ── Equity Agro ──────────────────────────────────────────────
                "impacto_equity": (
                    f"{sinal} ativo (ONI={oni_alerta:+.2f}). "
                    f"Tickers mais sensíveis: {_enso_ticks}. "
                    "Revisões de guidance de safra são esperadas nas próximas divulgações de resultado."
                ),
                "acao_equity": (
                    "Reduzir exposição tática ao setor agro de ciclo curto. "
                    "Preferir empresas integradas ou com hedge natural (exportadores com receita em USD). "
                    "Monitorar calls de resultado — focar em gestão de risco de produção declarada."
                ),
                # ── Commodities ──────────────────────────────────────────────
                "impacto_commodities": (
                    f"{sinal} ativo (ONI={oni_alerta:+.2f}). "
                    f"Commodities com maior sensibilidade histórica: {_enso_comms}. "
                    "Correlação ONI-preço sugere pressão direcional no horizonte de 1-6 meses."
                ),
                "acao_commodities": (
                    f"Rever estratégia de hedge em {_enso_fut}. "
                    "Monitorar USDA WASDE e CONAB mensais para ajuste de posição. "
                    "Spread soja-milho como posição direcional de menor volatilidade relativa."
                ),
            })

        ALERTAS_BASE.sort(key=lambda x: -x["score"])

        # Mapeamento perfil → campos do alerta
        _CAMPOS_ALERTA = {
            "Crédito Agro":  ("impacto_credito",     "acao_credito"),
            "Equity Agro":   ("impacto_equity",       "acao_equity"),
            "Commodities":   ("impacto_commodities",  "acao_commodities"),
        }

        def render_alertas(alertas, categoria):
            filtrados = [a for a in alertas if categoria in a["categorias"]]
            if not filtrados:
                st.info("Nenhum alerta ativo para esta categoria.")
                return
            _k_imp, _k_ac = _CAMPOS_ALERTA.get(categoria, ("impacto_credito", "acao_credito"))
            for a in filtrados:
                _cor  = NIVEL_COR.get(a["nivel"], "#555")
                _cls  = a["nivel"].lower()
                _sc   = f"{a['score']:.0f}"
                _imp  = a.get(_k_imp, "—")
                _acao = a.get(_k_ac,  "—")
                html_card(f"""
<div class="alert-card alert-{_cls}">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div style="flex:1;padding-right:12px">
      <b style="font-size:1rem;color:{_cor}">{a['fenomeno']}</b>
      <span style="color:#555;margin-left:10px;font-size:.8rem">{a['regiao']}</span><br>
      <span style="color:#CCC;font-size:.88rem">{a['descricao']}</span><br>
      <span style="color:#AAA;font-size:.82rem">⚠ {_imp}</span><br>
      <span style="color:#00B4A2;font-size:.82rem">→ {_acao}</span>
    </div>
    <div style="text-align:center;min-width:70px">
      <div style="font-size:1.6rem;font-weight:800;color:{_cor}">{_sc}</div>
      <div style="font-size:.7rem;color:#555">score</div>
    </div>
  </div>
</div>""")

        tab_cred, tab_equity, tab_comm = st.tabs(["🏦 Crédito Agro","📊 Equity Agro","🌽 Commodities"])
        with tab_cred:   render_alertas(ALERTAS_BASE, "Crédito Agro")
        with tab_equity: render_alertas(ALERTAS_BASE, "Equity Agro")
        with tab_comm:   render_alertas(ALERTAS_BASE, "Commodities")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — TRADUTOR FINANCEIRO
# ═══════════════════════════════════════════════════════════════════════════════
with t5:
    st.subheader("Tradutor Financeiro — Impacto Climático em Ativos")
    tab_cra, tab_eq, tab_comm5 = st.tabs(["📋 Crédito Agro (CRA/LCA)","🏢 Equity Agro","🌽 Commodities"])

    # ── M3 — Crédito Agro: simulador metodológico completo ───────────────────
    with tab_cra:
        st.markdown("#### Simulador de Carteira CRA/LCA")
        st.caption("Adicione e remova operações livremente. O risco total é recalculado dinamicamente.")

        # ── Constantes e calibração (sidebar avançada) ─────────────────────────
        # PD_BASE = 3,1%/ano
        # Fonte: Banco Central do Brasil — Sistema de Informações de Créditos (SCR),
        # inadimplência média do crédito rural 2019-2023.
        # Disponível em https://www3.bcb.gov.br/ifdata/
        PD_BASE_DEFAULT = 0.031

        # FATOR_AJUSTE climático
        # ATENÇÃO ×1.5 baseado em estudos de impacto de El Niño moderado na inadimplência
        # rural (~+50%). CRÍTICO ×2.5 baseado em eventos extremos históricos (seca 2020-22
        # no Sul, El Niño 2015-16) que aproximadamente dobraram a taxa de default em regiões
        # afetadas. [CALIBRAÇÃO PRELIMINAR — substituir por estudo formal de correlação
        # climática × default em V2]
        FATOR_NORMAL_DEFAULT  = 1.0
        FATOR_ATENCAO_DEFAULT = 1.5
        FATOR_CRITICO_DEFAULT = 2.5

        # LGD = 50% — faixa típica para crédito rural com garantia real (penhor agrícola,
        # alienação fiduciária de safra, FGO/PROAGRO Mais) conforme Basel III LGD framework
        # e estudos de recovery rate em CRA/LCA brasileiros.
        LGD_DEFAULT = 0.50

        # Sensibilidade climática por cultura
        # Café ×1.3: vulnerabilidade alta a geadas e veranicos no SE (ref. EMBRAPA Café).
        # Cana ×0.8: resiliência maior a stress hídrico moderado.
        # Arroz ×1.2: dependente de irrigação, vulnerável a secas no RS.
        # [CALIBRAÇÃO PRELIMINAR — referenciar boletins agroclimatológicos EMBRAPA por cultura em V2]
        SENSIBILIDADE_CULTURA = {
            "Soja": 1.0, "Milho": 1.1, "Café": 1.3, "Algodão": 0.9,
            "Cana": 0.8, "Arroz": 1.2, "Feijão": 1.1,
            "Boi Gordo": 1.0, "Laranja": 1.15, "Trigo": 1.05,
        }

        # Ajuste de concentração climática via HHI
        # Portfolios concentrados regionalmente sofrem default correlacionado em eventos ENSO.
        # Fator de stress = 1 + (HHI × 0.30). Carteira 100% concentrada → +30% sobre EL base.
        # [CALIBRAÇÃO PRELIMINAR baseada em literatura de risco sistêmico setorial]
        HHI_STRESS_COEF_DEFAULT = 0.30

        # ── Sidebar avançada ───────────────────────────────────────────────────
        with st.expander("⚙️ Parâmetros avançados de calibração"):
            st.caption(
                "Ajuste os parâmetros para refletir a inadimplência específica da carteira XP. "
                "Todos os cálculos recalculam dinamicamente."
            )
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                pd_base = st.slider(
                    "PD Base (%/ano)",
                    min_value=1.5, max_value=6.0, value=PD_BASE_DEFAULT*100,
                    step=0.1, format="%.1f%%",
                    help="PD base: 3,1%/ano. Fonte: BCB/SCR, inadimplência média crédito rural 2019-2023. https://www3.bcb.gov.br/ifdata/"
                ) / 100.0
                lgd = st.slider(
                    "LGD — Loss Given Default (%)",
                    min_value=30, max_value=80, value=int(LGD_DEFAULT*100),
                    step=5, format="%d%%",
                    help="50% = faixa típica para crédito rural com garantia real (Basel III + CRA/LCA brasileiros)."
                ) / 100.0
            with col_s2:
                fator_atencao = st.slider(
                    "Multiplicador ATENÇÃO",
                    min_value=1.0, max_value=3.0, value=float(FATOR_ATENCAO_DEFAULT),
                    step=0.1, format="%.1f×",
                    help="×1.5 baseado em El Niño moderado → ~+50% inadimplência rural. [CALIBRAÇÃO PRELIMINAR]"
                )
                fator_critico = st.slider(
                    "Multiplicador CRÍTICO",
                    min_value=1.5, max_value=5.0, value=float(FATOR_CRITICO_DEFAULT),
                    step=0.1, format="%.1f×",
                    help="×2.5 baseado em seca 2020-22/Sul e El Niño 2015-16 (≈dobro de default). [CALIBRAÇÃO PRELIMINAR]"
                )
            with col_s3:
                hhi_stress_coef = st.slider(
                    "Coef. stress de concentração (HHI)",
                    min_value=0.0, max_value=1.0, value=float(HHI_STRESS_COEF_DEFAULT),
                    step=0.05, format="%.2f",
                    help="Fator HHI × coef = % adicional de EL por concentração regional. [CALIBRAÇÃO PRELIMINAR]"
                )

        FATOR_AJUSTE = {"NORMAL": 1.0, "ATENCAO": fator_atencao, "CRITICO": fator_critico}

        # ── Adição de operações ────────────────────────────────────────────────
        if "operacoes" not in st.session_state:
            st.session_state.operacoes = [
                {"regiao":"Centro-Oeste","cultura":"Soja",    "valor_mi":50.0,"prazo_anos":1.0},
                {"regiao":"Sul",         "cultura":"Soja",    "valor_mi":30.0,"prazo_anos":2.0},
                {"regiao":"Nordeste",    "cultura":"Milho",   "valor_mi":20.0,"prazo_anos":1.0},
            ]

        col_add, col_csv = st.columns([1,1])
        with col_add:
            if st.button("➕ Adicionar operação"):
                st.session_state.operacoes.append(
                    {"regiao":"Centro-Oeste","cultura":"Soja","valor_mi":10.0,"prazo_anos":1.0}
                )
                st.rerun()
        with col_csv:
            uploaded = st.file_uploader(
                "Importar CSV (regiao, cultura, valor_mi, prazo_anos)",
                type="csv", key="csv_upload"
            )
            if uploaded:
                df_up = pd.read_csv(uploaded)
                cols_need = {"regiao","cultura","valor_mi","prazo_anos"}
                if cols_need.issubset(df_up.columns):
                    st.session_state.operacoes = df_up[list(cols_need)].to_dict("records")
                    st.success(f"{len(st.session_state.operacoes)} operações importadas.")
                    st.rerun()
                else:
                    st.error(f"CSV precisa das colunas: {cols_need}")

        REGIOES_OPS = ["Centro-Oeste","Sul","Nordeste","Sudeste","Norte"]
        CULTURAS_OPS = ["Soja","Milho","Cana","Café","Algodão","Arroz","Feijão","Boi Gordo","Laranja","Trigo"]

        ops_para_remover = []
        for i, op in enumerate(st.session_state.operacoes):
            with st.container():
                c1,c2,c3,c4,c5 = st.columns([2,2,1.5,1.2,0.5])
                op["regiao"]    = c1.selectbox("Região",    REGIOES_OPS,  index=REGIOES_OPS.index(op["regiao"])  if op["regiao"]  in REGIOES_OPS  else 0, key=f"reg_{i}")
                op["cultura"]   = c2.selectbox("Cultura",   CULTURAS_OPS, index=CULTURAS_OPS.index(op["cultura"]) if op["cultura"] in CULTURAS_OPS else 0, key=f"cul_{i}")
                op["valor_mi"]  = c3.number_input("Valor (R$ mi)", min_value=0.1, value=float(op["valor_mi"]), step=1.0, key=f"val_{i}")
                op["prazo_anos"]= c4.number_input("Prazo (anos)", min_value=0.5, max_value=10.0, value=float(op.get("prazo_anos",1.0)), step=0.5, key=f"prz_{i}")
                with c5:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("🗑", key=f"del_{i}", help="Remover operação"):
                        ops_para_remover.append(i)

        if ops_para_remover:
            st.session_state.operacoes = [
                op for j,op in enumerate(st.session_state.operacoes) if j not in ops_para_remover
            ]
            st.rerun()

        # ── Seletor de cenário ─────────────────────────────────────────────────
        st.markdown("---")
        cenario_sel = st.radio(
            "Cenário climático",
            ["Cenário base (clima atual)", "El Niño Forte", "La Niña Forte"],
            horizontal=True, key="cenario_cra",
        )

        # ── Cálculo dinâmico ───────────────────────────────────────────────────
        st.markdown("**Resultado da análise**")

        def _nivel_cenario(regiao: str, nivel_real: str, cenario: str) -> str:
            """Retorna o nível climático de uma região conforme o cenário selecionado."""
            if cenario == "Cenário base (clima atual)":
                return nivel_real
            elif cenario == "El Niño Forte":
                return "CRITICO"
            else:  # La Niña Forte
                if regiao in ("Sul",):
                    return "CRITICO"
                elif regiao in ("Sudeste", "Centro-Oeste"):
                    return "ATENCAO"
                else:
                    return "NORMAL"

        def _calc_carteira(operacoes, nivel_map, score_map, pd_base, lgd, fator_ajuste,
                           sensib_cultura, hhi_coef, cenario):
            """Calcula EL ajustada para a carteira completa. Retorna (df_res, métricas)."""
            rows = []
            for op in operacoes:
                nivel_real = nivel_map.get(op["regiao"], "NORMAL")
                nivel_ef   = _nivel_cenario(op["regiao"], nivel_real, cenario)
                sc         = score_map.get(op["regiao"], 0)
                fator      = fator_ajuste[nivel_ef]
                sens       = sensib_cultura.get(op["cultura"], 1.0)
                pd_ajust   = pd_base * fator * sens
                pd_acum    = round(1 - (1 - pd_ajust) ** op["prazo_anos"], 4)
                el_linha   = round(op["valor_mi"] * pd_acum * lgd, 4)

                # EL base (sem ajuste climático nem cultura) para referência
                pd_base_acum = round(1 - (1 - pd_base) ** op["prazo_anos"], 4)
                el_base_linha = round(op["valor_mi"] * pd_base_acum * lgd, 4)

                rows.append({
                    "Região": op["regiao"], "Cultura": op["cultura"],
                    "Valor (R$mi)": op["valor_mi"], "Prazo": f"{op['prazo_anos']:.1f}a",
                    "Risco": nivel_ef, "Score": sc,
                    "Sens.Cult.": f"{sens:.2f}×",
                    "PD ajust. (%)": round(pd_ajust * 100, 2),
                    "PD acum. (%)": round(pd_acum * 100, 2),
                    "EL (R$mi)": el_linha,
                    "_el_base": el_base_linha,
                    "_ead": op["valor_mi"],
                })
            df = pd.DataFrame(rows)
            return df

        if has_score and st.session_state.operacoes:
            nivel_map_cra = score_df.set_index("regiao")["nivel"].to_dict()
            score_map_cra = score_df.set_index("regiao")["score"].to_dict()

            df_res = _calc_carteira(
                st.session_state.operacoes,
                nivel_map_cra, score_map_cra,
                pd_base, lgd, FATOR_AJUSTE,
                SENSIBILIDADE_CULTURA, hhi_stress_coef,
                cenario_sel,
            )

            total_exp    = df_res["Valor (R$mi)"].sum()
            total_el     = df_res["EL (R$mi)"].sum()
            total_el_base = df_res["_el_base"].sum()
            pd_medio     = (total_el / total_exp / lgd * 100) if (total_exp > 0 and lgd > 0) else 0

            # ── HHI e stress de concentração ──────────────────────────────────
            exp_por_reg  = df_res.groupby("Região")["Valor (R$mi)"].sum()
            shares       = exp_por_reg / exp_por_reg.sum() if exp_por_reg.sum() > 0 else exp_por_reg
            hhi          = float((shares ** 2).sum())
            stress_factor = 1 + (hhi * hhi_stress_coef)
            total_el_stress = total_el * stress_factor
            ecl          = total_el_stress - total_el_base  # Exposição Climática Líquida

            # ── Métricas principais ────────────────────────────────────────────
            m1,m2,m3,m4,m5 = st.columns(5)
            m1.metric("Operações",          f"{len(df_res)}")
            m2.metric("Exposição total",    f"R$ {total_exp:.1f} mi")
            m3.metric("EL bruta",           f"R$ {total_el:.3f} mi",
                      help="EL = EAD × PD_acum × LGD. Inclui ajuste climático e sensibilidade de cultura.")
            m4.metric("EL ajustada (stress)",f"R$ {total_el_stress:.3f} mi",
                      help=f"EL bruta × stress de concentração ({stress_factor:.3f}×)")
            m5.metric("Exposição Climática Líquida",
                      f"R$ {ecl:.3f} mi",
                      f"{ecl/total_el_base*100:+.1f}% vs. cenário neutro" if total_el_base > 0 else "",
                      help="EL_ajustada − EL_base (cenário sem clima). Quanto da perda esperada vem do clima atual.")

            # ── Sensibilidade LGD ─────────────────────────────────────────────
            lgd_delta_el = (total_exp * pd_medio/100 * 0.01)  # R$mi por 1pp de LGD adicional
            st.caption(
                f"Cada ponto percentual de LGD a mais = R$ {lgd_delta_el:.3f} mi de EL adicional na carteira atual."
            )

            # ── Decomposição EL ───────────────────────────────────────────────
            hhi_label = ("Diversificada" if hhi < 0.15 else
                         ("Moderadamente concentrada" if hhi < 0.25 else "Altamente concentrada"))
            stress_pct = (stress_factor - 1) * 100
            html_card(f"""
<div style="background:#111;border:1px solid #1E1E1E;border-radius:10px;padding:14px 18px;margin:8px 0">
  <div style="font-size:.78rem;color:#888;margin-bottom:6px">DECOMPOSIÇÃO DA PERDA ESPERADA</div>
  <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center">
    <div><span style="color:#555;font-size:.75rem">EL bruta</span><br>
      <b style="font-size:1.1rem">R$ {total_el:.3f} mi</b></div>
    <div style="color:#555">·</div>
    <div><span style="color:#555;font-size:.75rem">HHI</span><br>
      <b style="font-size:1.1rem;color:#F5A623">{hhi:.3f}</b>
      <span style="color:#555;font-size:.7rem"> ({hhi_label})</span></div>
    <div style="color:#555">·</div>
    <div><span style="color:#555;font-size:.75rem">Stress concentração</span><br>
      <b style="font-size:1.1rem;color:#FF4444">+{stress_pct:.1f}%</b></div>
    <div style="color:#555">→</div>
    <div><span style="color:#555;font-size:.75rem">EL ajustada</span><br>
      <b style="font-size:1.1rem;color:#00B4A2">R$ {total_el_stress:.3f} mi</b></div>
  </div>
  <div style="margin-top:10px;padding-top:10px;border-top:1px solid #1E1E1E">
    <span style="color:#555;font-size:.75rem">Exposição Climática Líquida</span>
    <b style="font-size:1.25rem;color:#00B4A2;margin-left:12px">R$ {ecl:.3f} mi</b>
    <span style="color:#888;font-size:.75rem;margin-left:8px">— quanto da perda esperada vem do clima atual vs. cenário neutro</span>
  </div>
</div>""")

            # ── Tabela de operações ────────────────────────────────────────────
            cols_show = ["Região","Cultura","Valor (R$mi)","Prazo","Risco","Score",
                         "Sens.Cult.","PD ajust. (%)","PD acum. (%)","EL (R$mi)"]
            st.dataframe(
                df_res[cols_show].style.map(
                    lambda v: f"color:{NIVEL_COR.get(v,'#FFF')}",
                    subset=["Risco"]
                ).background_gradient(subset=["Score"], cmap="RdYlGn_r", vmin=0, vmax=100),
                use_container_width=True, hide_index=True,
            )
            st.caption(
                f"PD base: 3,1%/ano (BCB/SCR 2019-2023). "
                f"Fator climático: Normal ×1.0 · Atenção ×{fator_atencao:.1f} · Crítico ×{fator_critico:.1f}. "
                f"LGD: {lgd*100:.0f}%. "
                f"PD ajustada = PD_base × Fator_climático × Sensibilidade_cultura. "
                f"EL = EAD × PD_acum × LGD."
            )

            # ── Cards HHI e Top-3 regiões ──────────────────────────────────────
            st.markdown("---")
            col_hhi, col_top3 = st.columns([1,2])
            with col_hhi:
                hhi_cor = "#00B4A2" if hhi < 0.15 else ("#F5A623" if hhi < 0.25 else "#FF4444")
                html_card(f"""
<div style="background:#111;border:1px solid #1E1E1E;border-radius:10px;padding:14px;text-align:center">
  <div style="color:#888;font-size:.75rem;margin-bottom:6px">HHI — Concentração Regional</div>
  <div style="font-size:2rem;font-weight:800;color:{hhi_cor}">{hhi:.3f}</div>
  <div style="color:{hhi_cor};font-size:.8rem;margin-top:4px">{hhi_label}</div>
  <div style="color:#555;font-size:.7rem;margin-top:6px">0 = diversificada · 1 = concentrada</div>
</div>""")
            with col_top3:
                top3 = exp_por_reg.sort_values(ascending=False).head(3)
                top3_total = exp_por_reg.sum()
                top3_str = " + ".join(
                    f"{reg} {val/top3_total:.0%}" for reg, val in top3.items()
                )
                html_card(f"""
<div style="background:#111;border:1px solid #1E1E1E;border-radius:10px;padding:14px">
  <div style="color:#888;font-size:.75rem;margin-bottom:6px">TOP-3 REGIÕES (por exposição)</div>
  <div style="font-size:.95rem;font-weight:600;color:#FFF">{top3_str}</div>
  <div style="color:#555;font-size:.7rem;margin-top:6px">= {top3.sum()/top3_total:.0%} da carteira</div>
</div>""")

            # ── Gráfico: contribuição de cada região para EL total ─────────────
            el_por_reg = df_res.groupby("Região")["EL (R$mi)"].sum().reset_index()
            el_por_reg.columns = ["Região", "EL (R$mi)"]
            el_por_reg = el_por_reg.sort_values("EL (R$mi)", ascending=True)

            fig_el_reg = go.Figure(go.Bar(
                x=el_por_reg["EL (R$mi)"], y=el_por_reg["Região"],
                orientation="h",
                marker_color=["#00B4A2","#F5A623","#FF4444","#7B61FF","#4ADE80"][:len(el_por_reg)],
                text=[f"R$ {v:.3f} mi" for v in el_por_reg["EL (R$mi)"]],
                textposition="outside",
            ))
            fig_el_reg.update_layout(
                **PLOTLY_LAYOUT, height=220,
                title="Contribuição por região — EL bruta (dor financeira esperada)",
                xaxis_title="EL (R$ mi)", yaxis_title="",
            )
            st.plotly_chart(fig_el_reg, use_container_width=True)

            # ── Gráfico de pizza (exposição, descritivo) ───────────────────────
            fig_pie = px.pie(df_res, values="Valor (R$mi)", names="Região",
                             color_discrete_sequence=["#00B4A2","#F5A623","#FF4444","#7B61FF","#4ADE80"],
                             title="Concentração da carteira por região (exposição)")
            fig_pie.update_layout(**PLOTLY_LAYOUT, height=260)
            st.plotly_chart(fig_pie, use_container_width=True)

            # ── Cenários comparativos ──────────────────────────────────────────
            st.markdown("---")
            st.markdown("**Comparativo de cenários hipotéticos**")
            cenarios_list = ["Cenário base (clima atual)", "El Niño Forte", "La Niña Forte"]
            cols_cen = st.columns(3)
            for idx_c, cen in enumerate(cenarios_list):
                df_cen = _calc_carteira(
                    st.session_state.operacoes,
                    nivel_map_cra, score_map_cra,
                    pd_base, lgd, FATOR_AJUSTE,
                    SENSIBILIDADE_CULTURA, hhi_stress_coef, cen,
                )
                el_cen      = df_cen["EL (R$mi)"].sum()
                el_base_cen = df_cen["_el_base"].sum()
                el_adj_cen  = el_cen * stress_factor
                ecl_cen     = el_adj_cen - el_base_cen
                _cor = ("#00B4A2" if cen == "Cenário base (clima atual)"
                        else ("#FF4444" if "Niño" in cen else "#4A90D9"))
                with cols_cen[idx_c]:
                    html_card(f"""
<div style="background:#111;border:1px solid {_cor};border-radius:10px;padding:14px;text-align:center">
  <div style="color:{_cor};font-size:.78rem;font-weight:700;margin-bottom:8px">{cen.upper()}</div>
  <div style="color:#888;font-size:.7rem">EL ajustada</div>
  <div style="font-size:1.4rem;font-weight:800;color:#FFF">R$ {el_adj_cen:.3f} mi</div>
  <div style="color:#888;font-size:.7rem;margin-top:6px">Exposição Climática Líquida</div>
  <div style="font-size:1.1rem;font-weight:700;color:{_cor}">R$ {ecl_cen:.3f} mi</div>
</div>""")

        elif not has_score:
            st.info("Dados de score não disponíveis. Clique em ↺ Atualizar.")

    # ── M4 — Equity: banco expandido + busca livre ────────────────────────────
    with tab_eq:
        st.markdown("#### Exposição Climática — Empresas Listadas Agro")
        st.caption("Score climático = média ponderada do ClimaRisk Score por região, usando exposição geográfica de cada empresa.")

        # Banco interno: 15 empresas com exposição geográfica documentada
        # Fonte: Relatórios Anuais / ITRs das companhias
        EQUITY_DB = pd.DataFrame([
            # ticker, empresa, setor, exp_CO, exp_NE, exp_SE, exp_S, exp_N, notas
            ("AGRO3","Brasilagro",        "Produção agro",       0.45,0.30,0.25,0.00,0.00,"Fazendas MT,MS,BA,PI"),
            ("SLCE3","SLC Agrícola",      "Produção grãos",      0.55,0.10,0.15,0.20,0.00,"Maior produtora soja/milho BR"),
            ("TTEN3","3Tentos",           "Insumos/grãos Sul",   0.10,0.00,0.10,0.80,0.00,"Base RS/SC/PR"),
            ("SMTO3","São Martinho",      "Cana/açúcar/etanol",  0.35,0.00,0.55,0.10,0.00,"Usinas SP e GO"),
            ("CAML3","Camil",             "Arroz/feijão",        0.05,0.30,0.15,0.50,0.00,"Arrozeiro RS, op. NE"),
            ("RAIZ4","Raízen",            "Cana/etanol/combust", 0.30,0.05,0.55,0.10,0.00,"Usinas SP,GO; rede posto BR"),
            ("BEEF3","Minerva Foods",     "Proteína bovina",     0.35,0.10,0.15,0.30,0.10,"Frigoríficos GO,MT,RS,RO"),
            ("JBSS3","JBS",               "Proteína diversific.", 0.25,0.08,0.20,0.30,0.05,"Exposição global; BR=40% receita"),
            ("BRFS3","BRF",               "Aves/suínos",         0.10,0.05,0.15,0.60,0.00,"Concentrado SC/PR; importa grãos"),
            ("MRFG3","Marfrig",           "Proteína bovina",     0.30,0.08,0.18,0.35,0.08,"Frigoríficos MT,RS e exterior"),
            ("MDIA3","M. Dias Branco",    "Moagem trigo/massas", 0.05,0.55,0.20,0.15,0.05,"HQ CE; plantas NE e SE"),
            ("CSAN3","Cosan",             "Cana/logística/dists",0.25,0.03,0.55,0.12,0.05,"Raízen + Compass + Moove"),
            ("SUZB3","Suzano",            "Celulose/eucalipto",  0.15,0.20,0.40,0.10,0.15,"Plantios BA,MA,MS,ES"),
            ("KLBN3","Klabin",            "Papel/celulose",      0.10,0.05,0.20,0.65,0.00,"Plantios PR dominante"),
            ("VBBR3","Vibra Energia",     "Distribuição combust",0.20,0.15,0.35,0.20,0.10,"Distribuição nacional"),
        ], columns=["ticker","empresa","setor","exp_CO","exp_NE","exp_SE","exp_S","exp_N","notas"])

        # Calcula score climático para cada empresa
        if has_score:
            sr = score_df.set_index("regiao")["score"].to_dict()
            EQUITY_DB["score_clima"] = (
                EQUITY_DB["exp_CO"] * sr.get("Centro-Oeste",50) +
                EQUITY_DB["exp_NE"] * sr.get("Nordeste",50) +
                EQUITY_DB["exp_SE"] * sr.get("Sudeste",50) +
                EQUITY_DB["exp_S"]  * sr.get("Sul",50) +
                EQUITY_DB["exp_N"]  * sr.get("Norte",50)
            ).round(1)
            EQUITY_DB["nivel"] = EQUITY_DB["score_clima"].apply(
                lambda s: "CRITICO" if s>=70 else ("ATENCAO" if s>=45 else "NORMAL")
            )
        else:
            EQUITY_DB["score_clima"] = 50.0
            EQUITY_DB["nivel"] = "—"

        # ── Busca livre por ticker ou nome ─────────────────────────────────
        st.markdown("---")
        col_busca, col_limpar = st.columns([4,1])
        with col_busca:
            busca_eq = st.text_input(
                "Buscar empresa por ticker ou nome",
                placeholder="Ex: SLCE3 ou SLC ou arroz",
                key="equity_search",
            ).strip().upper()
        with col_limpar:
            st.markdown("<br>", unsafe_allow_html=True)
            st.button("Limpar", key="limpar_eq",
                      on_click=fazer_limpar_callback("equity_search"))

        if busca_eq:
            mask = (
                EQUITY_DB["ticker"].str.upper().str.contains(busca_eq, na=False) |
                EQUITY_DB["empresa"].str.upper().str.contains(busca_eq, na=False) |
                EQUITY_DB["setor"].str.upper().str.contains(busca_eq, na=False)
            )
            resultado_eq = EQUITY_DB[mask]
            if resultado_eq.empty:
                html_card(f"""
<div style="background:#1a1a0f;border:1px solid #F5A623;border-radius:8px;padding:14px 16px;margin:8px 0">
  <b style="color:#F5A623">"{busca_eq}" não encontrado no banco de exposição agro mapeada.</b><br>
  <span style="color:#888;font-size:.85rem">
    Score de exposição climática não disponível para este ticker.<br>
    O banco cobre empresas com exposição primária à produção agropecuária brasileira.<br>
    Empresas como VALE3, ITUB4, PETR4 têm exposição indireta ao clima agro e não estão mapeadas.
  </span>
</div>""")
            else:
                df_show = resultado_eq
        else:
            df_show = EQUITY_DB

        # Gráfico
        fig_eq = px.bar(
            df_show.sort_values("score_clima", ascending=False) if has_score else df_show,
            x="ticker", y="score_clima" if has_score else "exp_CO",
            color="score_clima" if has_score else "exp_CO",
            color_continuous_scale=[[0,"#00B4A2"],[0.45,"#F5A623"],[0.7,"#FF4444"],[1,"#8B0000"]],
            range_color=(0,100), text="score_clima" if has_score else None,
            hover_data={"empresa":True,"setor":True,"notas":True},
            labels={"score_clima":"Score Climático","ticker":""},
        )
        fig_eq.update_layout(**PLOTLY_LAYOUT, height=320, coloraxis_showscale=False)
        st.plotly_chart(fig_eq, use_container_width=True)

        # Tabela detalhada
        cols_show = ["ticker","empresa","setor","score_clima","nivel","notas"] if has_score else ["ticker","empresa","setor","notas"]
        st.dataframe(
            df_show[cols_show].style.map(
                lambda v: f"color:{NIVEL_COR.get(v,'#FFF')}", subset=["nivel"] if has_score else []
            ),
            use_container_width=True, hide_index=True,
        )

        with st.expander("📊 Detalhamento de exposição geográfica por empresa"):
            exp_cols = ["ticker","empresa","exp_CO","exp_NE","exp_SE","exp_S","exp_N"]
            st.dataframe(
                df_show[exp_cols].rename(columns={
                    "exp_CO":"Centro-Oeste","exp_NE":"Nordeste",
                    "exp_SE":"Sudeste","exp_S":"Sul","exp_N":"Norte"
                }).style.format({c:"{:.0%}" for c in ["Centro-Oeste","Nordeste","Sudeste","Sul","Norte"]}),
                use_container_width=True, hide_index=True,
            )
            st.caption("Exposição geográfica baseada em Relatórios Anuais e ITRs das companhias. Atualização manual necessária após cada resultado.")

    # ── Commodities ───────────────────────────────────────────────────────────
    with tab_comm5:
        st.markdown("#### Impacto Esperado em Preços — ENSO × Commodities")

        # ── Configuração de commodities ────────────────────────────────────────
        # Coef. ENSO → Iizumi et al. 2014 (yield impact) × elasticidade simplificada preço/yield.
        # Ponderações: ENSO / anomalia regional / câmbio.
        # [CALIBRAÇÃO PRELIMINAR — ponderação a calibrar com modelo econométrico em V2]
        # [CALIBRAÇÃO PRELIMINAR — coeficientes a calibrar com modelo econométrico em V2]
        # Fontes base: Iizumi et al. 2014 (yield × ENSO), CEPEA/ESALQ, IBGE PAM 2022.
        COMM_CONFIG = {
            "Soja": {
                "coef_enso": +0.06,
                "regiao_dom": "Centro-Oeste",      # MT = maior produtor ~28% safra nacional
                "peso_enso": 0.30, "peso_reg": 0.30, "peso_fx": 0.40,
                "vol_anual": 0.25,                 # volatilidade histórica anualizada
                "horizonte": "1-3 meses",
                "ticker_yf": "ZS=F",               # soja CBOT
                "logica": "El Niño → seca CO → menor oferta BR → alta de preço",
            },
            "Milho": {
                "coef_enso": +0.04,
                "regiao_dom": "Centro-Oeste",      # MT 1ª safra, PR/RS 2ª safra
                "peso_enso": 0.35, "peso_reg": 0.40, "peso_fx": 0.25,
                "vol_anual": 0.28,
                "horizonte": "1-3 meses",
                "ticker_yf": "ZC=F",               # milho CBOT
                "logica": "El Niño → seca CO/NE → menor produção BR",
            },
            "Café": {
                "coef_enso": +0.08,
                "regiao_dom": "Sudeste",           # MG ~50% produção nacional
                "peso_enso": 0.30, "peso_reg": 0.50, "peso_fx": 0.20,
                "vol_anual": 0.35,
                "horizonte": "3-6 meses",
                "ticker_yf": "KC=F",               # café arábica ICE
                "logica": "El Niño → veranico SE → forte impacto em MG/SP",
            },
            "Cana-de-açúcar": {
                "coef_enso": +0.03,
                "regiao_dom": "Sudeste",           # SP ~55% produção nacional
                "peso_enso": 0.20, "peso_reg": 0.55, "peso_fx": 0.25,
                "vol_anual": 0.22,
                "horizonte": "3-6 meses",
                "ticker_yf": "SB=F",               # açúcar bruto ICE (proxy)
                "logica": "El Niño → chuva excessiva em SP no início da safra → diluição de sacarose → queda de ATR",
            },
            "Algodão": {
                "coef_enso": +0.05,
                "regiao_dom": "Centro-Oeste",      # MT ~65% produção nacional
                "peso_enso": 0.35, "peso_reg": 0.45, "peso_fx": 0.20,
                "vol_anual": 0.30,
                "horizonte": "1-3 meses",
                "ticker_yf": "CT=F",               # algodão ICE
                "logica": "El Niño → seca CO → impacto na floração e abertura de maçãs em MT/BA",
            },
            "Arroz": {
                "coef_enso": +0.07,
                "regiao_dom": "Sul",               # RS ~65% produção nacional (irrigado)
                "peso_enso": 0.40, "peso_reg": 0.40, "peso_fx": 0.20,
                "vol_anual": 0.20,
                "horizonte": "1-3 meses",
                "ticker_yf": "ZR=F",               # arroz bruto CBOT
                "logica": "El Niño → excesso de chuva no Sul → alagamento e doenças em lavouras irrigadas RS",
            },
            "Feijão": {
                "coef_enso": +0.06,
                "regiao_dom": "Sudeste",           # MG/GO/SP maiores produtores
                "peso_enso": 0.30, "peso_reg": 0.45, "peso_fx": 0.25,
                "vol_anual": 0.35,
                "horizonte": "1-3 meses",
                "ticker_yf": "N/A",                # mercado doméstico; sem futuro ICE/CBOT equivalente
                "logica": "El Niño → seca irregular CO/SE → queda 1ª e 2ª safra; 3ª safra pode compensar parcialmente",
            },
            "Trigo": {
                "coef_enso": +0.08,
                "regiao_dom": "Sul",               # PR/RS ~90% produção nacional
                "peso_enso": 0.35, "peso_reg": 0.45, "peso_fx": 0.20,
                "vol_anual": 0.30,
                "horizonte": "3-6 meses",
                "ticker_yf": "ZW=F",               # trigo CBOT
                "logica": "El Niño → excesso de chuva no Sul no florescimento → fusariose → queda de qualidade e volume",
            },
            "Laranja": {
                "coef_enso": +0.09,
                "regiao_dom": "Sudeste",           # SP ~75% produção nacional
                "peso_enso": 0.35, "peso_reg": 0.50, "peso_fx": 0.15,
                "vol_anual": 0.40,
                "horizonte": "3-6 meses",
                "ticker_yf": "OJ=F",               # suco de laranja ICE
                "logica": "El Niño → veranico severo no Sudeste → estresse hídrico na floração → queda de produção em SP",
            },
            "Boi Gordo": {
                "coef_enso": +0.02,
                "regiao_dom": "Centro-Oeste",      # MT/GO/MS ~35% rebanho nacional
                "peso_enso": 0.15, "peso_reg": 0.45, "peso_fx": 0.40,
                "vol_anual": 0.18,
                "horizonte": "1-3 meses",
                "ticker_yf": "GF=F",               # feeder cattle CME (proxy)
                "logica": "El Niño → seca CO → queda de pastagem → pressão de custo de arroba; efeito moderado vs. grãos",
            },
        }

        # Períodos ENSO históricos para marcação no gráfico
        # Datas como strings ISO — add_shape/add_annotation aceitam strings no eixo datetime.
        # NÃO usar add_vline com datas: Plotly chama sum([x,x]) internamente, e Python sum()
        # começa com 0, causando "0 + string" ou "0 + Timestamp" → TypeError em pandas 2.x.
        ENSO_PERIODOS = [
            {"label":"El Niño 2015-16","ini":"2015-05-01","fim":"2016-04-30","cor":"#FF4444"},
            {"label":"La Niña 2020-22","ini":"2020-09-01","fim":"2023-01-31","cor":"#4A90D9"},
            {"label":"El Niño 2023-24","ini":"2023-06-01","fim":"2024-06-30","cor":"#FF4444"},
        ]

        # ── Funções de fetch com cache ─────────────────────────────────────────
        @st.cache_data(ttl=86400, show_spinner=False)
        def _fetch_precos_yfinance(ticker: str, anos: int = 5) -> pd.Series:
            """
            Tenta buscar série histórica via yfinance (futuros CBOT).
            Retorna pd.Series indexada por data, ou Series vazia em falha.
            Limitação: preços em USD/bushel (CBOT) — proxy de preço real.
            V2: substituir por CEPEA/ESALQ em R$/saca para preço doméstico real.
            """
            try:
                import yfinance as yf
                end   = pd.Timestamp.today()
                start = end - pd.DateOffset(years=anos)
                df_yf = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                                    end=end.strftime("%Y-%m-%d"),
                                    progress=False, auto_adjust=True)
                if df_yf.empty:
                    return pd.Series(dtype=float)
                close = df_yf["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                close.index = pd.to_datetime(close.index)
                return close.resample("ME").last().dropna()
            except Exception:
                return pd.Series(dtype=float)

        @st.cache_data(ttl=3600, show_spinner=False)
        def _fetch_usd_brl() -> tuple[float, float]:
            """
            Busca USD/BRL atual e média 12 meses via BCB PTAX API.
            Retorna (cotacao_atual, media_12m). Fallback: (5.20, 5.20).
            Fonte: https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/
            """
            try:
                hoje = pd.Timestamp.today()
                inicio = (hoje - pd.DateOffset(months=12)).strftime("%m-%d-%Y")
                fim_str = hoje.strftime("%m-%d-%Y")
                url = (
                    f"https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
                    f"CotacaoDolarPeriodo(dataInicial='{inicio}',dataFinalCotacao='{fim_str}')"
                    f"?$format=json&$select=cotacaoVenda,dataHoraCotacao"
                )
                r = requests.get(url, timeout=6)
                if r.status_code != 200:
                    return 5.20, 5.20
                data_bcb = r.json().get("value", [])
                if not data_bcb:
                    return 5.20, 5.20
                valores = [float(x["cotacaoVenda"]) for x in data_bcb if x.get("cotacaoVenda")]
                if not valores:
                    return 5.20, 5.20
                return valores[-1], float(np.mean(valores))
            except Exception:
                return 5.20, 5.20

        # ── Carrega dados ──────────────────────────────────────────────────────
        oni_comm = float(oni_df.dropna(subset=["ONI"]).iloc[-1]["ONI"]) if has_oni else 0.0

        usd_atual, usd_media12m = _fetch_usd_brl()
        fx_desv_pct = (usd_atual / usd_media12m - 1.0) if usd_media12m > 0 else 0.0
        fx_ok = abs(usd_atual - 5.20) > 0.001  # True se API funcionou (não é fallback)

        # Anomalia regional por região (do score_df)
        anom_reg_map: dict[str, float] = {}
        if has_score and "anomalia_pct" in score_df.columns:
            anom_reg_map = score_df.set_index("regiao")["anomalia_pct"].to_dict()

        # ── Tabela principal: decomposição em 3 componentes ───────────────────
        st.markdown(f"**ONI atual: {oni_comm:+.2f} °C** ({_enso_label(oni_comm)})  ·  "
                    f"USD/BRL: {usd_atual:.3f} {'(BCB/PTAX)' if fx_ok else '(fallback estimado)'}")

        if not fx_ok:
            st.warning("⚠ API BCB/PTAX indisponível — câmbio usando valor estimado (5,20). Componente FX pode estar impreciso.")

        # Convicção baseada em ONI
        def _convicao(oni: float) -> str:
            a = abs(oni)
            if a >= 1.5: return "Alta"
            if a >= 0.5: return "Média"
            return "Baixa"

        rows_c = []
        for comm, cfg in COMM_CONFIG.items():
            anom_reg = anom_reg_map.get(cfg["regiao_dom"], 0.0) or 0.0

            # Componente ENSO (já existe): ONI × coef × 100 = %
            comp_enso_pct   = oni_comm * cfg["coef_enso"] * 100

            # Componente anomalia regional: desvio de precipitação → impacto proporcional
            # anomalia_pct da região → fator de impacto reduzido (anomalia/100 * coef)
            # Secas (anom<0) → oferta cai → preço sobe → sinal positivo p/ comprador
            comp_reg_pct    = -(anom_reg / 100) * cfg["coef_enso"] * 100 * 1.5

            # Componente câmbio: BRL depreciado vs. média → amplifica preço doméstico em R$
            # Peso câmbio só na componente FX; BRL depreciado → preço R$ sobe → positivo
            comp_fx_pct     = fx_desv_pct * 100

            # Impacto composto ponderado
            ip_total = (
                cfg["peso_enso"] * comp_enso_pct +
                cfg["peso_reg"]  * comp_reg_pct  +
                cfg["peso_fx"]   * comp_fx_pct
            )

            # IC 80% baseado em vol histórica
            # IC = ±(1.28 × vol_anual × |ONI_atual| / 2.0)
            oni_mag = max(abs(oni_comm) / 2.0, 0.10)
            ic_halfwidth = 1.28 * cfg["vol_anual"] * oni_mag * abs(cfg["coef_enso"]) * 100
            ip_lo = ip_total - ic_halfwidth
            ip_hi = ip_total + ic_halfwidth

            rows_c.append({
                "Commodity":         comm,
                "ONI":               f"{oni_comm:+.2f}",
                "Comp. ENSO (%)":    f"{comp_enso_pct:+.2f}%",
                "Comp. Regional (%)":f"{comp_reg_pct:+.2f}%",
                "Comp. Câmbio (%)":  f"{comp_fx_pct:+.2f}%",
                "Impacto total (%)": f"{ip_total:+.2f}%",
                "IC 80%":            f"[{ip_lo:+.2f}%, {ip_hi:+.2f}%]",
                "Horizonte":         cfg["horizonte"],
                "Convicção":         _convicao(oni_comm),
                "Direção":           "Alta" if ip_total > 0 else ("Baixa" if ip_total < 0 else "Neutro"),
                "_ip_total":         ip_total,
                "_ip_lo":            ip_lo,
                "_ip_hi":            ip_hi,
                "_comp_enso":        comp_enso_pct,
                "_comp_reg":         comp_reg_pct,
                "_comp_fx":          comp_fx_pct,
                "_logica":           cfg["logica"],
            })

        df_c = pd.DataFrame(rows_c)

        # Tabela display (sem cols internas)
        cols_tab = ["Commodity","ONI","Comp. ENSO (%)","Comp. Regional (%)","Comp. Câmbio (%)",
                    "Impacto total (%)","IC 80%","Horizonte","Convicção","Direção"]
        st.dataframe(
            df_c[cols_tab].style.map(
                lambda v: "color:#00B4A2" if v=="Alta" else ("color:#FF4444" if v=="Baixa" else "color:#AAA"),
                subset=["Direção"]
            ).map(
                lambda v: "color:#F5A623" if v=="Média" else ("color:#4ADE80" if v=="Alta" else "color:#888"),
                subset=["Convicção"]
            ),
            use_container_width=True, hide_index=True,
        )
        st.caption(
            "Decomposição: ENSO global (Iizumi 2014 × ONI) + Anomalia regional (precipitação da região produtora dominante) + "
            "Câmbio (desvio USD/BRL atual vs. média 12m, BCB/PTAX). "
            "IC 80% derivado de vol. histórica anualizada × magnitude relativa ONI. "
            "[CALIBRAÇÃO PRELIMINAR — ponderação a calibrar com modelo econométrico em V2]"
        )

        # ── Gráfico histórico com eixo duplo e marcadores ENSO ────────────────
        if has_oni:
            st.markdown("---")
            comm_sel = st.selectbox("Ver série histórica", list(COMM_CONFIG.keys()), key="comm_hist_sel")
            cfg_sel  = COMM_CONFIG[comm_sel]

            # Impacto proxy histórico (eixo direito)
            oni_c = oni_df.tail(60).copy()
            oni_c["data"] = pd.to_datetime(oni_c["data"])
            oni_c["impacto_proxy_%"] = (oni_c["ONI"] * cfg_sel["coef_enso"] * 100).round(2)

            # Tenta preço real via yfinance
            preco_serie = _fetch_precos_yfinance(cfg_sel["ticker_yf"], anos=5)
            tem_preco_real = len(preco_serie) >= 12

            fig_c = go.Figure()

            # Linha de preço real (eixo esquerdo), se disponível
            if tem_preco_real:
                fig_c.add_trace(go.Scatter(
                    x=preco_serie.index, y=preco_serie.values,
                    name=f"Preço CBOT {comm_sel} (USD/bushel — proxy)",
                    line=dict(color="#AAAAAA", width=1.5),
                    yaxis="y1",
                    hovertemplate="<b>%{x|%b/%Y}</b><br>Preço: %{y:.2f} USD/bu<extra></extra>",
                ))

            # Barras de impacto proxy ONI (eixo direito)
            fig_c.add_trace(go.Bar(
                x=oni_c["data"], y=oni_c["impacto_proxy_%"],
                name="Impacto proxy ENSO (%)",
                marker_color=["#FF4444" if v > 0 else "#4A90D9" for v in oni_c["impacto_proxy_%"]],
                yaxis="y2" if tem_preco_real else "y1",
                hovertemplate="<b>%{x|%b/%Y}</b><br>Impacto proxy: %{y:+.2f}%<extra></extra>",
            ))

            # Marcadores de períodos ENSO.
            # Usamos add_shape em vez de add_vline/add_vrect: o Plotly chama sum([x,x])
            # internamente em add_vline, e Python sum() começa com 0, causando TypeError
            # ao tentar "0 + string" ou "0 + Timestamp" no pandas 2.x.
            # add_shape + add_annotation não passam por esse caminho e aceitam strings ISO.
            for ep in ENSO_PERIODOS:
                _cor_ep = ep["cor"]
                # fundo sombreado (retângulo)
                fig_c.add_shape(
                    type="rect",
                    xref="x", yref="paper",
                    x0=ep["ini"], x1=ep["fim"],
                    y0=0, y1=1,
                    fillcolor=_cor_ep, opacity=0.08,
                    layer="below", line_width=0,
                )
                # linha pontilhada vertical no início do período
                fig_c.add_shape(
                    type="line",
                    xref="x", yref="paper",
                    x0=ep["ini"], x1=ep["ini"],
                    y0=0, y1=1,
                    line=dict(dash="dot", color=_cor_ep, width=1),
                )
                # anotação de texto no topo da linha
                fig_c.add_annotation(
                    xref="x", yref="paper",
                    x=ep["ini"], y=0.98,
                    text=ep["label"],
                    showarrow=False,
                    font=dict(size=9, color=_cor_ep),
                    xanchor="left", yanchor="top",
                )

            # Layout com eixo duplo
            layout_c = {**PLOTLY_LAYOUT, "height": 320}
            if tem_preco_real:
                layout_c.update({
                    "yaxis":  dict(title=f"Preço CBOT (USD/bushel)", color="#AAAAAA",
                                   gridcolor="#1E1E1E"),
                    "yaxis2": dict(title="Impacto proxy ENSO (%)", overlaying="y",
                                   side="right", color="#00B4A2", gridcolor="#1E1E1E"),
                })
            else:
                layout_c["yaxis"] = dict(title="Impacto proxy ENSO (%)", gridcolor="#1E1E1E")

            fig_c.update_layout(**layout_c, barmode="overlay",
                                legend=dict(orientation="h", y=-0.18))
            st.plotly_chart(fig_c, use_container_width=True)

            if tem_preco_real:
                st.caption(
                    f"Linha cinza: preço futuro CBOT {comm_sel} em USD/bushel (yfinance). "
                    "V2: substituir por CEPEA/ESALQ em R$/saca para preço doméstico real."
                )
            else:
                st.warning(
                    f"⚠ Série de preço real não disponível (yfinance sem dados para {cfg_sel['ticker_yf']}) — "
                    "exibindo apenas proxy de impacto ENSO. "
                    "Para versão de produção, conectar API CEPEA/ESALQ ou reprocessar tickers CBOT."
                )

            # ── Cards de decomposição por commodity ───────────────────────────
            st.markdown("---")
            st.markdown("**Decomposição do impacto por componente**")
            _df_c_rows = list(df_c.iterrows())
            for _ci in range(0, len(_df_c_rows), 5):
                _chunk = _df_c_rows[_ci:_ci+5]
                cols_cards = st.columns(len(_chunk))
                for _col, (idx_c2, row) in zip(cols_cards, _chunk):
                    with _col:
                        _dir_cor = "#00B4A2" if row["_ip_total"] > 0 else "#FF4444"
                        html_card(f"""
<div style="background:#111;border:1px solid #1E1E1E;border-radius:10px;padding:14px;text-align:center">
  <div style="color:#888;font-size:.78rem;font-weight:700;margin-bottom:6px">{row['Commodity'].upper()}</div>
  <div style="font-size:1.6rem;font-weight:800;color:{_dir_cor}">{row['_ip_total']:+.2f}%</div>
  <div style="font-size:.7rem;color:#555;margin-bottom:8px">{row['IC 80%']} (IC 80%)</div>
  <div style="text-align:left;font-size:.72rem;color:#888">
    <span style="color:#555">ENSO global:</span> {row['_comp_enso']:+.2f}%<br>
    <span style="color:#555">Anomalia regional:</span> {row['_comp_reg']:+.2f}%<br>
    <span style="color:#555">Câmbio USD/BRL:</span> {row['_comp_fx']:+.2f}%
  </div>
  <div style="margin-top:8px;font-size:.7rem;color:#555">Horizonte: {row['Horizonte']}</div>
  <div style="font-size:.7rem;color:{'#4ADE80' if row['Convicção']=='Alta' else ('#F5A623' if row['Convicção']=='Média' else '#888')}">
    Convicção: {row['Convicção']}
  </div>
</div>""")

            st.caption(
                "[CALIBRAÇÃO PRELIMINAR — coeficientes ENSO a calibrar com modelo econométrico em V2. "
                "Fontes: Iizumi et al. 2014, CEPEA/ESALQ, IBGE PAM 2022.]"
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — MAPA POR VARIÁVEL
# ═══════════════════════════════════════════════════════════════════════════════
with t6:
    st.subheader("Análise Climática Isolada por Variável")
    st.caption(
        "Selecione uma variável climática para ver o mapa do Brasil pintado conforme esse indicador, "
        "com escala de cor e classificação NORMAL/ATENÇÃO/CRÍTICO próprias de cada variável."
    )

    if not has_score_ufs:
        st.warning("Dados de score por UF não disponíveis. Clique em ↺ Atualizar.")
    else:
        # ── Seletor de variável ───────────────────────────────────────────────
        var_sel = st.radio(
            "Variável",
            ["Score Composto", "Precipitação", "Temperatura", "Queimadas", "ENSO"],
            horizontal=True, key="var_map_sel",
        )

        # ── Prepara dataframe enriquecido para a variável selecionada ─────────
        def _build_var_df(var: str) -> pd.DataFrame:
            """
            Retorna score_ufs_df enriquecido com colunas z_val, z_nivel e tt_* para a variável.
            Thresholds documentados inline — marcados [CALIBRAÇÃO PRELIMINAR] onde aplicável.
            """
            df = score_ufs_df.copy()

            if var == "Score Composto":
                df["z_val"]   = df["score"]
                df["z_nivel"] = df["nivel"]
                _med = df["z_val"].mean()
                df["tt_val"]       = df["score"].map(lambda s: f"{s:.0f}/100")
                df["tt_normal"]    = "NORMAL 0–45 · ATENÇÃO 45–70 · CRÍTICO ≥70"
                df["tt_desvio"]    = (df["z_val"] - _med).map(lambda d: f"{d:+.1f} pts vs. média Brasil")
                df["tt_classif"]   = df["nivel"].map(
                    lambda n: {"CRITICO":"CRÍTICO (≥70)","ATENCAO":"ATENÇÃO (45–70)","NORMAL":"NORMAL (<45)"}.get(n, n))
                df["tt_vs_brasil"] = (df["z_val"] - _med).map(
                    lambda d: f"vs. média Brasil ({_med:.0f} pts): {d:+.1f} pts")

            elif var == "Precipitação":
                df["z_val"] = df["anomalia_precip_pct"].fillna(0)
                # Thresholds [CALIBRAÇÃO PRELIMINAR — refinar com INMET/EMBRAPA em V2]:
                # NORMAL [-20% a +30%] · ATENÇÃO [-40%/+60%] · CRÍTICO [<-40% ou >+60%]
                def _cl_p(v):
                    return ("CRITICO" if (v < -40 or v > 60)
                            else ("ATENCAO" if (v < -20 or v > 30) else "NORMAL"))
                df["z_nivel"] = df["z_val"].map(_cl_p)
                _med = df["z_val"].mean()
                df["tt_val"] = df.apply(
                    lambda r: f"{r['precip_obs_mm']:.0f} mm acumulados (30d)"
                    if pd.notna(r.get("precip_obs_mm")) else "—", axis=1)
                df["tt_normal"] = df.apply(
                    lambda r: f"Normal 1991-2020: {r['normal_precip_mm']:.0f} mm"
                    if pd.notna(r.get("normal_precip_mm")) else "—", axis=1)
                df["tt_desvio"] = df["z_val"].map(
                    lambda v: f"{'▼' if v < 0 else '▲'} {abs(v):.1f}% vs. normal")
                df["tt_classif"] = df["z_nivel"].map(
                    lambda n: {"CRITICO":"CRÍTICO em precipitação","ATENCAO":"ATENÇÃO em precipitação",
                               "NORMAL":"NORMAL em precipitação"}.get(n, n))
                df["tt_vs_brasil"] = (df["z_val"] - _med).map(
                    lambda d: f"vs. média Brasil ({_med:+.1f}%): {d:+.1f}pp")

            elif var == "Temperatura":
                df["z_val"] = df["anomalia_temp_c"].fillna(0)
                # Thresholds [CALIBRAÇÃO PRELIMINAR — refinar com INMET/EMBRAPA em V2]:
                # NORMAL [-1°C a +1.5°C] · ATENÇÃO [-2°C/+3°C] · CRÍTICO [<-2°C ou >+3°C]
                def _cl_t(v):
                    return ("CRITICO" if (v < -2 or v > 3)
                            else ("ATENCAO" if (v < -1 or v > 1.5) else "NORMAL"))
                df["z_nivel"] = df["z_val"].map(_cl_t)
                _med = df["z_val"].mean()
                df["tt_val"] = df.apply(
                    lambda r: f"{r['temp_obs_c']:.1f}°C (30d)"
                    if pd.notna(r.get("temp_obs_c")) else "—", axis=1)
                df["tt_normal"] = df.apply(
                    lambda r: f"Normal 1991-2020: {r['normal_temp_c']:.1f}°C"
                    if pd.notna(r.get("normal_temp_c")) else "—", axis=1)
                df["tt_desvio"] = df["z_val"].map(
                    lambda v: f"{'▼' if v < 0 else '▲'} {abs(v):.1f}°C vs. normal")
                df["tt_classif"] = df["z_nivel"].map(
                    lambda n: {"CRITICO":"CRÍTICO em temperatura","ATENCAO":"ATENÇÃO em temperatura",
                               "NORMAL":"NORMAL em temperatura"}.get(n, n))
                df["tt_vs_brasil"] = (df["z_val"] - _med).map(
                    lambda d: f"vs. média Brasil ({_med:+.1f}°C): {d:+.1f}°C")

            elif var == "Queimadas":
                df["z_val"] = df["focos_7d"].astype(float)
                # Percentis do dataset atual (27 UFs)
                # [CALIBRAÇÃO PRELIMINAR — refinar com série histórica INPE em V2]
                _p75 = df["z_val"].quantile(0.75)
                _p90 = df["z_val"].quantile(0.90)
                def _cl_q(v):
                    return ("CRITICO" if v > _p90 else ("ATENCAO" if v > _p75 else "NORMAL"))
                df["z_nivel"] = df["z_val"].map(_cl_q)
                _med = df["z_val"].mean()
                df["tt_val"]    = df["focos_7d"].map(lambda f: f"{int(f):,} focos (7d · bbox UF)")
                df["tt_normal"] = f"P75 atual: {_p75:.0f} focos  ·  P90 atual: {_p90:.0f} focos"
                df["tt_desvio"] = df["z_val"].map(
                    lambda v: (f"Acima do P90 ({v - _med:+.0f} vs. média)" if v > _p90
                               else (f"Acima do P75 ({v - _med:+.0f} vs. média)" if v > _p75
                                     else f"Abaixo do P75 ({v - _med:+.0f} vs. média)")))
                df["tt_classif"] = df["z_nivel"].map(
                    lambda n: {
                        "CRITICO": f"CRÍTICO em queimadas (>P90={_p90:.0f})",
                        "ATENCAO": f"ATENÇÃO em queimadas (>P75={_p75:.0f})",
                        "NORMAL":  f"NORMAL em queimadas (≤P75={_p75:.0f})",
                    }.get(n, n))
                df["tt_vs_brasil"] = (df["z_val"] - _med).map(
                    lambda d: f"vs. média Brasil ({_med:.0f} focos): {d:+.0f} focos")

            elif var == "ENSO":
                # Impacto regional = ONI × sensibilidade_UF (valor assinado)
                # [CALIBRAÇÃO PRELIMINAR — thresholds por magnitude absoluta, refinar com CPTEC/INPE em V2]
                df["z_val"] = df.apply(
                    lambda r: float(r["oni_ref"]) * (ENSO_SENS_UF or {}).get(r["uf"], 0.5), axis=1)
                # NORMAL |imp| < 0.5 · ATENÇÃO 0.5–1.5 · CRÍTICO > 1.5
                def _cl_e(v):
                    return ("CRITICO" if abs(v) > 1.5 else ("ATENCAO" if abs(v) > 0.5 else "NORMAL"))
                df["z_nivel"] = df["z_val"].map(_cl_e)
                _med = df["z_val"].mean()
                df["tt_val"] = df.apply(
                    lambda r: (f"ONI {r['oni_ref']:+.2f}°C × sensib. {r['uf']} "
                               f"({(ENSO_SENS_UF or {}).get(r['uf'], 0.5):+.3f})"), axis=1)
                df["tt_normal"]    = "Impacto neutro = 0.0  ·  |impacto| < 0.5 = NORMAL"
                df["tt_desvio"]    = df["z_val"].map(lambda v: f"Impacto ENSO regional: {v:+.3f}")
                df["tt_classif"]   = df["z_nivel"].map(
                    lambda n: {"CRITICO":"CRÍTICO em ENSO (|imp.|>1.5)","ATENCAO":"ATENÇÃO em ENSO (|imp.|>0.5)",
                               "NORMAL":"NORMAL em ENSO (|imp.|<0.5)"}.get(n, n))
                df["tt_vs_brasil"] = (df["z_val"] - _med).map(
                    lambda d: f"vs. média Brasil ({_med:+.3f}): {d:+.3f}")

            return df

        _var_df = _build_var_df(var_sel)

        # ── Config visual por variável ────────────────────────────────────────
        # Escalas de cor seguem padrão climatológico internacional (WMO/IPCC):
        # azul = úmido/frio · branco = normal · vermelho = seco/quente
        _VAR_VIZ = {
            "Score Composto": {
                "cs":    [[0,"#00B4A2"],[0.45,"#F5A623"],[0.7,"#FF4444"],[1,"#8B0000"]],
                "range": (0, 100),
                "cbar":  "Score",
                "leg":   "0 → NORMAL  ·  45 → ATENÇÃO  ·  70 → CRÍTICO",
            },
            "Precipitação": {
                # Vermelho = déficit/seca · Branco = normal · Azul = excesso hídrico
                "cs":    [[0,"#8B0000"],[0.2,"#FF4444"],[0.3,"#FFA07A"],
                          [0.5,"#F0F0F0"],[0.65,"#7BB8E8"],[0.8,"#4A90D9"],[1,"#003080"]],
                "range": (-100, 100),
                "cbar":  "Anomalia (%)",
                "leg":   "Vermelho = déficit/seca  ·  Branco = normal  ·  Azul = excesso hídrico",
            },
            "Temperatura": {
                # Azul = frio · Branco = normal · Vermelho = calor extremo
                "cs":    [[0,"#003080"],[0.25,"#4A90D9"],[0.4,"#C8E0F0"],
                          [0.5,"#F0F0F0"],[0.65,"#FFA07A"],[0.8,"#FF4444"],[1,"#8B0000"]],
                "range": (-4, 4),
                "cbar":  "Anomalia (°C)",
                "leg":   "Azul = frio abaixo da normal  ·  Branco = normal  ·  Vermelho = calor extremo",
            },
            "Queimadas": {
                # Verde = poucos focos (NORMAL) · Amarelo = moderado · Vermelho = muitos (CRÍTICO)
                "cs":    [[0,"#00B4A2"],[0.6,"#F5A623"],[0.85,"#FF4444"],[1,"#8B0000"]],
                "range": (0, max(float(_var_df["z_val"].max()), 1.0)),
                "cbar":  "Focos (7d)",
                "leg":   "Verde = poucos focos (NORMAL)  ·  Amarelo = moderado (ATENÇÃO)  ·  Vermelho = muitos (CRÍTICO)",
            },
            "ENSO": {
                # Azul = influência La Niña · Branco = neutro · Laranja/Vermelho = influência El Niño
                "cs":    [[0,"#003080"],[0.3,"#4A90D9"],[0.5,"#F0F0F0"],
                          [0.7,"#F5A623"],[1,"#8B0000"]],
                "range": (-2, 2),
                "cbar":  "Impacto ENSO",
                "leg":   "Azul = influência La Niña  ·  Branco = neutro  ·  Laranja/Vermelho = influência El Niño",
            },
        }
        _viz = _VAR_VIZ[var_sel]

        _n_crit = int((_var_df["z_nivel"] == "CRITICO").sum())
        _n_aten = int((_var_df["z_nivel"] == "ATENCAO").sum())
        _n_norm = int((_var_df["z_nivel"] == "NORMAL").sum())

        col_vm, col_vp = st.columns([3, 1])

        with col_vm:
            st.markdown(f"**{var_sel}** — distribuição entre as 27 UFs")

            _mdf_var = _var_df.rename(columns={"uf": "estado"}).copy()
            _cd_var  = ["estado", "tt_val", "tt_normal", "tt_desvio",
                        "tt_classif", "tt_vs_brasil", "z_nivel"]
            for _c in _cd_var:
                if _c not in _mdf_var.columns:
                    _mdf_var[_c] = "—"

            fig_var = px.choropleth(
                _mdf_var,
                geojson="https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson",
                locations="estado", featureidkey="properties.sigla",
                color="z_val",
                color_continuous_scale=_viz["cs"],
                range_color=_viz["range"],
                custom_data=_cd_var,
            )
            fig_var.update_traces(
                hovertemplate=(
                    "<b>%{customdata[0]}</b>  ·  %{customdata[6]}<br>"
                    "──────────────────────────────<br>"
                    "%{customdata[1]}<br>"
                    "%{customdata[2]}<br>"
                    "%{customdata[3]}<br>"
                    "%{customdata[4]}<br>"
                    "%{customdata[5]}<br>"
                    "<extra></extra>"
                )
            )
            fig_var.update_geos(fitbounds="locations", visible=False, bgcolor="#0A0A0A")
            fig_var.update_layout(
                **PLOTLY_LAYOUT, height=460,
                coloraxis_colorbar=dict(
                    title=_viz["cbar"],
                    tickfont=dict(color="#FFF"),
                ),
            )
            st.plotly_chart(fig_var, use_container_width=True)

            # Legenda da escala de cor
            html_card(f"""
<div style="background:#111;border:1px solid #1E1E1E;border-radius:8px;
            padding:8px 14px;font-size:.75rem;color:#888;margin-top:-10px">
  <b style="color:#CCC">Escala de cor:</b> {_viz['leg']}
</div>""")

            # Thresholds documentados
            _thresh_doc = {
                "Score Composto": "Thresholds: NORMAL 0–45 · ATENÇÃO 45–70 · CRÍTICO ≥70",
                "Precipitação":   ("Thresholds: NORMAL −20% a +30% · ATENÇÃO −40%/+60% · CRÍTICO <−40% ou >+60%  "
                                   "[CALIBRAÇÃO PRELIMINAR — refinar com INMET/EMBRAPA em V2]"),
                "Temperatura":    ("Thresholds: NORMAL −1°C a +1,5°C · ATENÇÃO −2°C/+3°C · CRÍTICO <−2°C ou >+3°C  "
                                   "[CALIBRAÇÃO PRELIMINAR — refinar com INMET/EMBRAPA em V2]"),
                "Queimadas":      (f"Thresholds: NORMAL ≤P75 ({_var_df['z_val'].quantile(0.75):.0f} focos) · "
                                   f"ATENÇÃO P75–P90 · CRÍTICO >P90 ({_var_df['z_val'].quantile(0.90):.0f} focos)  "
                                   "[CALIBRAÇÃO PRELIMINAR — percentis do dataset atual, refinar com série histórica INPE em V2]"),
                "ENSO":           ("Thresholds por |ONI × sensib. UF|: NORMAL <0,5 · ATENÇÃO 0,5–1,5 · CRÍTICO >1,5  "
                                   "[CALIBRAÇÃO PRELIMINAR — refinar com CPTEC/INPE em V2]"),
            }
            st.caption(_thresh_doc.get(var_sel, ""))

        with col_vp:
            # Resumo Brasil
            st.markdown("**Resumo Brasil**")
            html_card(f"""
<div style="background:#111;border:1px solid #1E1E1E;border-radius:10px;padding:12px 14px;margin-bottom:8px">
  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
    <span class="badge-critico">{_n_crit} CRÍTICO</span>
    <span class="badge-atencao">{_n_aten} ATENÇÃO</span>
    <span class="badge-normal">{_n_norm} NORMAL</span>
  </div>
  <div style="font-size:.75rem;color:#888">
    27 UFs · variável: <b style="color:#CCC">{var_sel}</b>
  </div>
</div>""")

            # Top 5 CRÍTICO por severidade
            st.markdown("**Top 5 — CRÍTICO**")
            _crit_df = _var_df[_var_df["z_nivel"] == "CRITICO"].copy()
            if var_sel in ("Precipitação", "Temperatura", "ENSO"):
                # ordena por magnitude absoluta (déficit e excesso igualmente severos)
                _crit_df = (_crit_df.assign(_sev=_crit_df["z_val"].abs())
                             .nlargest(5, "_sev"))
            else:
                _crit_df = _crit_df.nlargest(5, "z_val")

            if _crit_df.empty:
                html_card(
                    '<div style="color:#555;font-size:.8rem;padding:8px 0">'
                    'Nenhuma UF em CRÍTICO para esta variável.</div>')
            else:
                for _, _rc in _crit_df.iterrows():
                    html_card(f"""
<div style="background:#111;border-left:3px solid #FF4444;border-radius:6px;
            padding:7px 10px;margin-bottom:4px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <b style="font-size:.92rem">{_rc['uf']}</b>
    <span style="font-size:.78rem;color:#FF4444;font-weight:700">{_rc['tt_val']}</span>
  </div>
  <div style="font-size:.70rem;color:#888;margin-top:1px">{_rc['tt_desvio']}</div>
</div>""")

            st.markdown("---")

            # Distribuição entre as 27 UFs (mini bar chart)
            st.markdown("**Distribuição — 27 UFs**")
            _dist = _var_df[["uf", "z_val", "z_nivel"]].sort_values("z_val", ascending=False).copy()
            # Pré-formatar os valores numéricos ANTES de passar ao Plotly.
            # round() não basta (preserva imprecisão de float). f-string na camada de exibição
            # garante que -0.6999999999999998 → '-0.700' para TODOS os estados sem exceção.
            _fmt_y = ":.3f" if var_sel == "ENSO" else ":.1f"
            _dist["_y_fmt"] = _dist["z_val"].apply(
                lambda v: f"{v:.3f}" if var_sel == "ENSO" else f"{v:.1f}")
            fig_dist = go.Figure(go.Bar(
                x=_dist["uf"].tolist(),
                y=_dist["z_val"].tolist(),
                text=_dist["_y_fmt"].tolist(),
                textposition="none",          # texto só no hover, não sobre as barras
                marker_color=[NIVEL_COR.get(n, "#555") for n in _dist["z_nivel"].tolist()],
                hovertemplate=f"<b>%{{x}}</b>: %{{text}}<extra></extra>",
            ))
            fig_dist.update_layout(
                **{**PLOTLY_LAYOUT, "margin": dict(l=0, r=0, t=8, b=30)},
                height=200,
                xaxis=dict(tickfont=dict(size=8)),
                yaxis_title="",
                showlegend=False,
            )
            st.plotly_chart(fig_dist, use_container_width=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    f"<div style='text-align:center;color:#333;font-size:.75rem'>"
    f"ClimaCredit · GAS Challenge 2026.1 · XP Inc. · "
    f"Dados atualizados: {date.today().strftime('%d/%m/%Y')} · "
    f"Fontes: NOAA PSL · NASA FIRMS · Open-Meteo/ERA5 · IBGE"
    f"</div>",
    unsafe_allow_html=True,
)
