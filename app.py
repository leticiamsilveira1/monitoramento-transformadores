import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date
import os

from calculo_cep import calcular_base_completa, LIMIARES_IEC

# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================
st.set_page_config(
    page_title="Monitoramento de Transformadores",
    page_icon="⚡",
    layout="wide"
)

DATA_DIR = "data"
ARQ_EQUIP = os.path.join(DATA_DIR, "equipamentos.csv")
ARQ_LEIT = os.path.join(DATA_DIR, "leituras.csv")

GASES_PADRAO = [
    "Hidrogênio", "Metano", "Acetileno", "Etileno",
    "Etano", "Monóxido de Carbono", "Dióxido de Carbono",
]

# ============================================================
# CARREGA AS BASES
# ============================================================
def carregar_equipamentos():
    return pd.read_csv(ARQ_EQUIP)


def carregar_leituras():
    return pd.read_csv(ARQ_LEIT, parse_dates=["data_amostragem"])


@st.cache_data
def calcular(leituras_csv_mtime, leituras: pd.DataFrame):
    # o argumento leituras_csv_mtime só existe para invalidar o cache
    # quando o arquivo de leituras muda
    return calcular_base_completa(leituras)


def get_base_calculada():
    leituras = carregar_leituras()
    mtime = os.path.getmtime(ARQ_LEIT)
    return calcular(mtime, leituras)


# ============================================================
# NAVEGAÇÃO
# ============================================================
pagina = st.sidebar.radio("Navegação", ["📊 Dashboard", "➕ Cadastrar Dados"])

# ============================================================
# PÁGINA: CADASTRAR DADOS
# ============================================================
if pagina == "➕ Cadastrar Dados":
    st.title("➕ Cadastrar Novos Dados")

    equipamentos = carregar_equipamentos()

    aba_equip, aba_leitura = st.tabs(["Novo Equipamento", "Nova Leitura de Gás"])

    # -------- NOVO EQUIPAMENTO --------
    with aba_equip:
        st.subheader("Cadastrar novo transformador")
        with st.form("form_equipamento", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                novo_id = st.text_input("ID do Transformador (ex: TR31)")
                fabricante = st.text_input("Fabricante")
                ano_fab = st.number_input("Ano de Fabricação", min_value=1950, max_value=date.today().year, step=1)
            with col2:
                potencia = st.number_input("Potência (KVA)", min_value=0.0, step=1.0)
                tensao = st.number_input("Tensão (KV)", min_value=0.0, step=1.0)
                volume_oleo = st.number_input("Volume de Óleo (L)", min_value=0.0, step=1.0)

            enviar_equip = st.form_submit_button("Cadastrar Equipamento")

            if enviar_equip:
                novo_id = novo_id.strip().upper()
                if not novo_id:
                    st.error("Informe o ID do Transformador.")
                elif novo_id in equipamentos["id_transformador"].values:
                    st.error(f"O ID '{novo_id}' já existe. Escolha outro identificador.")
                else:
                    nova_linha = pd.DataFrame([{
                        "id_transformador": novo_id,
                        "Fabricante": fabricante,
                        "Ano de Fabricação": ano_fab,
                        "Potência KVA": potencia,
                        "Tensão KV": tensao,
                        "Volume de Óleo": volume_oleo,
                    }])
                    equipamentos = pd.concat([equipamentos, nova_linha], ignore_index=True)
                    equipamentos.to_csv(ARQ_EQUIP, index=False)
                    st.success(f"Equipamento {novo_id} cadastrado com sucesso!")
                    st.rerun()

        st.markdown("---")
        st.caption("Equipamentos cadastrados atualmente:")
        st.dataframe(equipamentos, use_container_width=True)
        st.download_button(
            "⬇️ Baixar equipamentos.csv atualizado",
            data=equipamentos.to_csv(index=False).encode("utf-8"),
            file_name="equipamentos.csv",
            mime="text/csv",
        )

    # -------- NOVA LEITURA --------
    with aba_leitura:
        st.subheader("Registrar novo resultado de gás (DGA)")

        if equipamentos.empty:
            st.warning("Cadastre um equipamento antes de lançar leituras.")
        else:
            with st.form("form_leitura", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    transformador = st.selectbox(
                        "Transformador", sorted(equipamentos["id_transformador"].unique())
                    )
                    data_amostra = st.date_input("Data de Amostragem", value=date.today())
                    condicao = st.selectbox("Condição de Operação", ["Normal", "Sobrecarga", "Manutenção", "Outra"])
                with col2:
                    gas = st.selectbox("Gás", GASES_PADRAO)
                    valor_ppm = st.number_input("Valor (ppm)", min_value=0.0, step=0.1)

                enviar_leitura = st.form_submit_button("Registrar Leitura")

                if enviar_leitura:
                    leituras = carregar_leituras()
                    nova_leitura = pd.DataFrame([{
                        "id_transformador": transformador,
                        "data_amostragem": pd.Timestamp(data_amostra),
                        "condicao_operacao": condicao,
                        "gas": gas,
                        "valor_ppm": valor_ppm,
                    }])
                    leituras = pd.concat([leituras, nova_leitura], ignore_index=True)
                    leituras.to_csv(ARQ_LEIT, index=False)
                    st.success(
                        f"Leitura registrada: {transformador} — {gas} = {valor_ppm} ppm em {data_amostra}"
                    )
                    st.cache_data.clear()
                    st.rerun()

        st.markdown("---")
        leituras_atual = carregar_leituras()
        st.download_button(
            "⬇️ Baixar leituras.csv atualizado",
            data=leituras_atual.to_csv(index=False).encode("utf-8"),
            file_name="leituras.csv",
            mime="text/csv",
        )
        st.caption(
            "⚠️ Se o app estiver rodando no Streamlit Cloud, baixe esses arquivos de "
            "tempos em tempos e suba-os de volta no GitHub — assim os dados novos "
            "não se perdem se o app reiniciar."
        )

        st.markdown("---")
        st.caption("Limiares de referência (IEC/IEEE) usados no sinal de alerta por gás:")
        st.dataframe(
            pd.DataFrame(
                [{"Gás": g, "Limiar (ppm)": v} for g, v in LIMIARES_IEC.items()]
            ),
            use_container_width=True,
        )

# ============================================================
# PÁGINA: DASHBOARD
# ============================================================
else:
    df = get_base_calculada()

    st.title("⚡ Monitoramento de Gases em Transformadores")
    st.markdown("---")

    # -------- SIDEBAR — FILTROS --------
    st.sidebar.header("Filtros")

    transformadores = sorted(df["id_transformador"].unique())
    transformador_sel = st.sidebar.selectbox("Transformador", transformadores)

    df_tr = df[df["id_transformador"] == transformador_sel]

    gases_disponiveis = sorted(df_tr["gas"].unique())
    gas_sel = st.sidebar.selectbox("Gás", ["(Todos)"] + gases_disponiveis)

    if gas_sel != "(Todos)":
        df_filtrado = df_tr[df_tr["gas"] == gas_sel]
    else:
        df_filtrado = df_tr

    # -------- MÉTRICAS RESUMO --------
    st.subheader(f"Transformador: {transformador_sel}")

    col1, col2, col3 = st.columns(3)

    total = len(df_filtrado)
    criticos = (df_filtrado["classificacao_final"] == "Crítico").sum()
    atencao = (df_filtrado["classificacao_final"] == "Atenção").sum()

    col1.metric("Total de Registros", total)
    col2.metric("⚠️ Atenção", int(atencao))
    col3.metric("🔴 Crítico", int(criticos))

    st.markdown("---")

    # -------- GRÁFICO — EVOLUÇÃO DO GÁS AO LONGO DO TEMPO --------
    st.subheader("Evolução dos Gases ao Longo do Tempo")

    def plot_gas(df_gas, gas_nome, height):
        df_gas = df_gas.sort_values("data_amostragem")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_gas["data_amostragem"], y=df_gas["x"],
            mode="lines+markers", name=gas_nome, line=dict(color="royalblue")
        ))
        if "ucl_x" in df_gas.columns:
            fig.add_trace(go.Scatter(
                x=df_gas["data_amostragem"], y=df_gas["ucl_x"],
                mode="lines", name="UCL", line=dict(color="red", dash="dash")
            ))
            fig.add_trace(go.Scatter(
                x=df_gas["data_amostragem"], y=df_gas["lcl_x"],
                mode="lines", name="LCL", line=dict(color="red", dash="dash")
            ))
        if height > 350 and "ewma" in df_gas.columns:
            fig.add_trace(go.Scatter(
                x=df_gas["data_amostragem"], y=df_gas["ewma"],
                mode="lines", name="EWMA", line=dict(color="orange", dash="dot")
            ))
        fig.update_layout(title=f"Gás: {gas_nome}", xaxis_title="Data",
                           yaxis_title="Concentração (ppm)", height=height)
        return fig

    if gas_sel == "(Todos)":
        for gas in gases_disponiveis:
            df_gas = df_tr[df_tr["gas"] == gas]
            if df_gas.empty:
                continue
            st.plotly_chart(plot_gas(df_gas, gas, 350), use_container_width=True)
    else:
        st.plotly_chart(plot_gas(df_filtrado, gas_sel, 450), use_container_width=True)

    st.markdown("---")

    # -------- CLASSIFICAÇÃO FINAL --------
    st.subheader("Classificação Final por Gás")

    resumo = (
        df_tr.groupby(["gas", "classificacao_final"])
        .size()
        .reset_index(name="count")
    )

    fig_class = px.bar(
        resumo, x="gas", y="count", color="classificacao_final",
        color_discrete_map={"Estável": "green", "Atenção": "orange", "Crítico": "red"},
        barmode="group", title="Distribuição das Classificações por Gás",
        labels={"gas": "Gás", "count": "Quantidade", "classificacao_final": "Classificação"}
    )
    fig_class.update_layout(height=400)
    st.plotly_chart(fig_class, use_container_width=True)

    st.markdown("---")

    # -------- TABELA DE DADOS --------
    st.subheader("Dados Detalhados")

    colunas_exibir = [
        "id_transformador", "data_amostragem", "gas", "x",
        "classificacao_final", "prioridade_acao",
        "sinal_cep", "sinal_ewma", "sinal_cusum", "sinal_iec",
        "total_sinais", "classificacao_tendencia"
    ]
    colunas_validas = [c for c in colunas_exibir if c in df_filtrado.columns]
    st.dataframe(
        df_filtrado[colunas_validas].sort_values("data_amostragem"),
        use_container_width=True
    )
