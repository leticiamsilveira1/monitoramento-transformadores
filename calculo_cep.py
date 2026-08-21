"""
calculo_cep.py

Reimplementação da lógica de Controle Estatístico de Processo (CEP) usada no TCC
para análise de gases dissolvidos (DGA) em transformadores.

Métodos:
- Gráfico de indivíduos X-MR (Shewhart)
- EWMA (Média Móvel Exponencialmente Ponderada)
- CUSUM tabular
- Regressão de tendência (linear)
- Sinal IEC/IEEE (limiar típico de concentração por gás)

IMPORTANTE — parâmetros reconstruídos por engenharia reversa a partir das bases
originais (base_motor.csv, base_xmr.csv, base_ewma.csv, base_cusum.csv,
base_tendencia.csv). A maioria dos parâmetros foi validada e reproduz os valores
originais com precisão. Dois pontos NÃO puderam ser confirmados com 100% de
certeza porque as bases não continham exemplos suficientes perto da fronteira:

  1. LIMIAR_H_CUSUM (limite de disparo do CUSUM): nas bases originais o CUSUM
     nunca ultrapassou ~3,9, então não há como saber se o limite era 4 ou 5.
     Usei 5 (par clássico k=0,5 / h=5, Montgomery). Ajuste em LIMIAR_H_CUSUM
     se você souber o valor exato usado no TCC.

  2. Limiares de sinal_iec para Acetileno e Etileno: as bases tinham um "salto"
     nos dados (ex.: Etileno com 0 sinal em 24 ppm e sinal em 168 ppm, sem
     nenhum valor intermediário para calibrar o limite exato). Usei os valores
     típicos mais citados na literatura (IEC 60599 / IEEE C57.104) dentro
     dessas faixas. Os demais gases (H2, CH4, C2H6, CO, CO2) foram confirmados
     com precisão exata contra as bases originais.

Todos os limiares ficam no dicionário LIMIARES_IEC abaixo — ajuste livremente.
"""

import numpy as np
import pandas as pd
from scipy import stats

# ============================================================
# PARÂMETROS DO MODELO
# ============================================================

# X-MR (gráfico de indivíduos e amplitude móvel, subgrupo n=2)
D2_XMR = 1.128       # constante para converter MR-barra em sigma estimado
D3_MR = 0.0          # limite inferior do gráfico de MR
D4_MR = 3.267        # limite superior do gráfico de MR
L_XMR = 3            # nº de desvios-padrão para os limites de controle (3-sigma)

# EWMA
LAMBDA_EWMA = 0.2     # peso do valor mais recente
L_EWMA = 3            # nº de desvios-padrão para os limites de controle

# CUSUM tabular (em unidades de desvio-padrão)
K_CUSUM = 0.5         # valor de referência (metade do deslocamento a detectar)
LIMIAR_H_CUSUM = 5    # limite de disparo — ver nota acima

# Tendência: abaixo desse |slope| (ppm por amostra), considera-se "Estável"
LIMIAR_SLOPE_ESTAVEL = 0.01

# Limiares típicos de concentração por gás (ppm) — sinal_iec = 1 se x > limiar
# Confirmados com precisão contra a base original: Hidrogênio, Metano, Etano,
# Monóxido de Carbono, Dióxido de Carbono.
# Assumidos (dentro da faixa observada, sem dado exato disponível): Acetileno, Etileno.
LIMIARES_IEC = {
    "Hidrogênio": 150,
    "Metano": 130,
    "Acetileno": 3,        # ⚠️ assumido (faixa observada: 1–5 ppm)
    "Etileno": 150,        # ⚠️ assumido (faixa observada: 24–168 ppm)
    "Etano": 90,
    "Monóxido de Carbono": 350,
    "Dióxido de Carbono": 2500,
}


# ============================================================
# CÁLCULO POR SÉRIE (1 transformador + 1 gás, ordenado por data)
# ============================================================
def calcular_serie(serie: pd.DataFrame, gas: str) -> pd.DataFrame:
    """
    Recebe as leituras de UM gás de UM transformador (colunas: data_amostragem,
    valor_ppm), ordenadas por data crescente, e retorna o DataFrame com todas
    as colunas estatísticas calculadas (X-MR, EWMA, CUSUM, tendência, sinais,
    classificação final).
    """
    serie = serie.sort_values("data_amostragem").reset_index(drop=True)
    x = serie["valor_ppm"].astype(float).values
    n = len(x)

    # ---------- X-MR ----------
    media_x = x.mean()
    mr = np.abs(np.diff(x))
    mr = np.insert(mr, 0, np.nan)  # primeiro ponto não tem MR
    media_mr = np.nanmean(mr) if n > 1 else 0.0
    sigma_xmr = media_mr / D2_XMR if media_mr else 0.0

    ucl_x = media_x + L_XMR * sigma_xmr
    lcl_x = media_x - L_XMR * sigma_xmr
    ucl_mr = D4_MR * media_mr
    lcl_mr = D3_MR * media_mr
    sinal_cep = ((x > ucl_x) | (x < lcl_x)).astype(int)

    # ---------- EWMA ----------
    ewma = np.zeros(n)
    ewma[0] = x[0]
    for i in range(1, n):
        ewma[i] = LAMBDA_EWMA * x[i] + (1 - LAMBDA_EWMA) * ewma[i - 1]

    sigma_amostral = x.std(ddof=1) if n > 1 else 0.0
    idx = np.arange(1, n + 1)
    fator = np.sqrt(
        (LAMBDA_EWMA / (2 - LAMBDA_EWMA)) * (1 - (1 - LAMBDA_EWMA) ** (2 * idx))
    )
    ucl_ewma = media_x + L_EWMA * sigma_amostral * fator
    lcl_ewma = media_x - L_EWMA * sigma_amostral * fator
    sinal_ewma = ((ewma > ucl_ewma) | (ewma < lcl_ewma)).astype(int)

    # ---------- CUSUM tabular ----------
    z = (x - media_x) / sigma_amostral if sigma_amostral else np.zeros(n)
    cusum_pos = np.zeros(n)
    cusum_neg = np.zeros(n)
    for i in range(1, n):
        cusum_pos[i] = max(0.0, cusum_pos[i - 1] + z[i] - K_CUSUM)
        cusum_neg[i] = max(0.0, cusum_neg[i - 1] - z[i] - K_CUSUM)
    sinal_cusum = ((cusum_pos > LIMIAR_H_CUSUM) | (cusum_neg > LIMIAR_H_CUSUM)).astype(int)

    # ---------- Tendência (regressão linear) ----------
    if n > 1:
        t = np.arange(n)
        reg = stats.linregress(t, x)
        slope, intercept, r2, p_value = reg.slope, reg.intercept, reg.rvalue ** 2, reg.pvalue
    else:
        slope = intercept = r2 = p_value = np.nan

    if pd.isna(slope) or abs(slope) < LIMIAR_SLOPE_ESTAVEL:
        classificacao_tendencia = "Estável"
    elif slope > 0:
        classificacao_tendencia = "Crescente"
    else:
        classificacao_tendencia = "Decrescente"

    # ---------- Sinal IEC ----------
    limiar = LIMIARES_IEC.get(gas)
    sinal_iec = (x > limiar).astype(int) if limiar is not None else np.zeros(n, dtype=int)

    # ---------- Consolidação ----------
    total_sinais = sinal_cep + sinal_ewma + sinal_cusum + sinal_iec

    def classifica(total):
        if total == 0:
            return "Estável"
        elif total <= 2:
            return "Atenção"
        else:
            return "Crítico"

    def prioridade(total):
        if total == 0:
            return "Monitoramento rotineiro"
        elif total <= 2:
            return "Aumentar frequência de coleta"
        else:
            return "Intervenção imediata"

    saida = serie.copy()
    saida["x"] = x
    saida["media_x"] = media_x
    saida["sigma_xmr"] = sigma_xmr
    saida["ucl_x"] = ucl_x
    saida["lcl_x"] = lcl_x
    saida["mr"] = mr
    saida["media_mr"] = media_mr
    saida["ucl_mr"] = ucl_mr
    saida["lcl_mr"] = lcl_mr
    saida["sinal_cep"] = sinal_cep
    saida["ewma"] = ewma
    saida["ucl_ewma"] = ucl_ewma
    saida["lcl_ewma"] = lcl_ewma
    saida["sinal_ewma"] = sinal_ewma
    saida["cusum_pos"] = cusum_pos
    saida["cusum_neg"] = cusum_neg
    saida["sinal_cusum"] = sinal_cusum
    saida["slope"] = slope
    saida["intercept"] = intercept
    saida["r2"] = r2
    saida["p_value"] = p_value
    saida["classificacao_tendencia"] = classificacao_tendencia
    saida["sinal_iec"] = sinal_iec
    saida["total_sinais"] = total_sinais
    saida["classificacao_final"] = [classifica(t) for t in total_sinais]
    saida["prioridade_acao"] = [prioridade(t) for t in total_sinais]

    return saida


def calcular_base_completa(leituras: pd.DataFrame) -> pd.DataFrame:
    """
    Recebe TODAS as leituras (todas as colunas: id_transformador, data_amostragem,
    condicao_operacao, gas, valor_ppm) e retorna a base com todas as estatísticas
    calculadas, agrupando por transformador + gás.
    """
    resultado = []
    for (tr, gas), grupo in leituras.groupby(["id_transformador", "gas"]):
        resultado.append(calcular_serie(grupo, gas))
    return pd.concat(resultado, ignore_index=True)
