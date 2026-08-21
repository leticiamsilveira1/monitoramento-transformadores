import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date
import os
import requests

from calculo_cep import calcular_base_completa, LIMIARES_IEC

# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================
st.set_page_config(page_title="Monitoramento de Transformadores", page_icon="⚡", layout="wide")

DATA_DIR = "data"
ARQ_EQUIP = os.path.join(DATA_DIR, "equipamentos.csv")
ARQ_LEIT = os.path.join(DATA_DIR, "leituras.csv")
GASES_PADRAO = ["Hidrogênio", "Metano", "Acetileno", "Etileno", "Etano", "Monóxido de Carbono", "Dióxido de Carbono"]

# ============================================================
# SUPABASE — PERSISTÊNCIA DOS DADOS
# ============================================================
def obter_config_supabase():
    try:
        return st.secrets.get("SUPABASE_URL", "").strip(), st.secrets.get("SUPABASE_ANON_KEY", "").strip()
    except Exception:
        return "", ""

SUPABASE_URL, SUPABASE_ANON_KEY = obter_config_supabase()
SUPABASE_TABELA_LEITURAS = "leituras_dga"
SUPABASE_TABELA_EQUIPAMENTOS = "equipamentos"

def supabase_configurado():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)

def supabase_headers():
    return {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}", "Content-Type": "application/json"}

def supabase_endpoint(tabela):
    return f"{SUPABASE_URL.rstrip('/')}/rest/v1/{tabela}"

# ------------------------- EQUIPAMENTOS ----------------------
def supabase_obter_equipamentos():
    resposta = requests.get(supabase_endpoint(SUPABASE_TABELA_EQUIPAMENTOS), headers=supabase_headers(), params={"select": "*", "order": "id.asc", "limit": 1000}, timeout=20)
    resposta.raise_for_status()
    df = pd.DataFrame(resposta.json())
    if df.empty:
        return pd.DataFrame(columns=["id", "created_at", "id_transformador", "fabricante", "ano_fabricacao", "potencia_kva", "tensao_kv", "volume_oleo", "ativo"])
    if "ativo" not in df.columns:
        df["ativo"] = True
    df["ativo"] = df["ativo"].fillna(True).astype(bool)
    return df

def supabase_inserir_equipamento(registro):
    dados = {"id_transformador": str(registro["id_transformador"]), "fabricante": str(registro["fabricante"]), "ano_fabricacao": int(registro["ano_fabricacao"]), "potencia_kva": float(registro["potencia_kva"]), "tensao_kv": float(registro["tensao_kv"]), "volume_oleo": float(registro["volume_oleo"]), "ativo": bool(registro.get("ativo", True))}
    resposta = requests.post(supabase_endpoint(SUPABASE_TABELA_EQUIPAMENTOS), headers={**supabase_headers(), "Prefer": "return=representation"}, json=dados, timeout=30)
    resposta.raise_for_status()
    return resposta.json()

def supabase_atualizar_equipamento(equipamento_id, ativo):
    resposta = requests.patch(supabase_endpoint(SUPABASE_TABELA_EQUIPAMENTOS), headers={**supabase_headers(), "Prefer": "return=representation"}, params={"id": f"eq.{int(equipamento_id)}"}, json={"ativo": bool(ativo)}, timeout=20)
    resposta.raise_for_status()
    return resposta.json()

def carregar_equipamentos():
    if supabase_configurado():
        try:
            return supabase_obter_equipamentos()
        except requests.RequestException as erro:
            st.error(f"Não foi possível acessar os equipamentos no Supabase: {erro}")
            return pd.DataFrame()
    try:
        df = pd.read_csv(ARQ_EQUIP)
        if "ativo" not in df.columns:
            df["ativo"] = True
        return df
    except FileNotFoundError:
        return pd.DataFrame()

# --------------------------- LEITURAS ------------------------
def supabase_obter_leituras():
    todos = []
    limite = 1000
    offset = 0
    while True:
        resposta = requests.get(supabase_endpoint(SUPABASE_TABELA_LEITURAS), headers=supabase_headers(), params={"select": "*", "order": "id.asc", "limit": limite, "offset": offset}, timeout=20)
        resposta.raise_for_status()
        pagina = resposta.json()
        if not pagina:
            break
        todos.extend(pagina)
        if len(pagina) < limite:
            break
        offset += limite
    df = pd.DataFrame(todos)
    if df.empty:
        return pd.DataFrame(columns=["id", "created_at", "id_transformador", "data_amostragem", "condicao_operacao", "gas", "valor_ppm"])
    df["data_amostragem"] = pd.to_datetime(df["data_amostragem"])
    df["valor_ppm"] = pd.to_numeric(df["valor_ppm"], errors="coerce")
    return df

def supabase_inserir(registros):
    dados = registros.copy()
    dados["data_amostragem"] = pd.to_datetime(dados["data_amostragem"]).dt.strftime("%Y-%m-%d")
    dados = dados[["id_transformador", "data_amostragem", "condicao_operacao", "gas", "valor_ppm"]].to_dict(orient="records")
    resposta = requests.post(supabase_endpoint(SUPABASE_TABELA_LEITURAS), headers={**supabase_headers(), "Prefer": "return=representation"}, json=dados, timeout=30)
    resposta.raise_for_status()
    return resposta.json()

def supabase_excluir(ids):
    for registro_id in ids:
        resposta = requests.delete(supabase_endpoint(SUPABASE_TABELA_LEITURAS), headers=supabase_headers(), params={"id": f"eq.{int(registro_id)}"}, timeout=20)
        resposta.raise_for_status()

def chave_registro(linha):
    return (str(linha["id_transformador"]), pd.to_datetime(linha["data_amostragem"]).date().isoformat(), str(linha["gas"]))

def importar_historico_csv():
    historico = pd.read_csv(ARQ_LEIT, parse_dates=["data_amostragem"])
    atual = supabase_obter_leituras()
    existentes = set(atual.apply(chave_registro, axis=1)) if not atual.empty else set()
    historico["_chave"] = historico.apply(chave_registro, axis=1)
    faltantes = historico[~historico["_chave"].isin(existentes)].drop(columns="_chave")
    if faltantes.empty:
        return 0
    supabase_inserir(faltantes)
    return len(faltantes)

# ============================================================
# CARREGA AS BASES
# ============================================================
def carregar_leituras():
    if supabase_configurado():
        try:
            return supabase_obter_leituras()
        except requests.RequestException as erro:
            st.error(f"Não foi possível acessar o Supabase: {erro}")
            return pd.DataFrame()
    return pd.read_csv(ARQ_LEIT, parse_dates=["data_amostragem"])

@st.cache_data
def calcular(assinatura_dados, leituras: pd.DataFrame):
    return calcular_base_completa(leituras)

def get_base_calculada():
    leituras = carregar_leituras()
    if leituras.empty:
        return pd.DataFrame()
    assinatura = hash(pd.util.hash_pandas_object(leituras, index=True).values.tobytes())
    return calcular(assinatura, leituras)

# ============================================================
# NAVEGAÇÃO
# ============================================================
pagina = st.sidebar.radio("Navegação", ["📊 Dashboard", "➕ Cadastrar Dados"])
if supabase_configurado():
    st.sidebar.success("☁️ Dados persistidos no Supabase")
else:
    st.sidebar.warning("⚠️ Supabase ainda não configurado. O app está usando o CSV local.")

# ============================================================
# PÁGINA: CADASTRAR DADOS
# ============================================================
if pagina == "➕ Cadastrar Dados":
    st.title("➕ Cadastrar Novos Dados")
    equipamentos = carregar_equipamentos()
    aba_equip, aba_leitura, aba_exclusao = st.tabs(["Novo Equipamento", "Nova Leitura de Gás", "🗑️ Gerenciar / Excluir"])
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
                ids_existentes = equipamentos["id_transformador"].astype(str).str.upper().values if not equipamentos.empty and "id_transformador" in equipamentos.columns else []
                if not novo_id:
                    st.error("Informe o ID do Transformador.")
                elif novo_id in ids_existentes:
                    st.error(f"O ID '{novo_id}' já existe. Escolha outro identificador.")
                else:
                    registro = {"id_transformador": novo_id, "fabricante": fabricante.strip(), "ano_fabricacao": ano_fab, "potencia_kva": potencia, "tensao_kv": tensao, "volume_oleo": volume_oleo, "ativo": True}
                    try:
                        if supabase_configurado():
                            supabase_inserir_equipamento(registro)
                        else:
                            nova_linha = pd.DataFrame([{"id_transformador": novo_id, "Fabricante": fabricante, "Ano de Fabricação": ano_fab, "Potência KVA": potencia, "Tensão KV": tensao, "Volume de Óleo": volume_oleo, "ativo": True}])
                            equipamentos = pd.concat([equipamentos, nova_linha], ignore_index=True)
                            equipamentos.to_csv(ARQ_EQUIP, index=False)
                        st.success(f"Equipamento {novo_id} cadastrado com sucesso!")
                        st.rerun()
                    except requests.RequestException as erro:
                        st.error(f"Erro ao salvar o equipamento no Supabase: {erro}")
        st.markdown("---")
        st.caption("Equipamentos cadastrados atualmente:")
        if equipamentos.empty:
            st.info("Nenhum equipamento cadastrado.")
        else:
            colunas_tabela = [c for c in ["id_transformador", "fabricante", "Fabricante", "ano_fabricacao", "Ano de Fabricação", "potencia_kva", "Potência KVA", "tensao_kv", "Tensão KV", "volume_oleo", "Volume de Óleo", "ativo"] if c in equipamentos.columns]
            st.dataframe(equipamentos[colunas_tabela], use_container_width=True, hide_index=True)
            st.download_button("⬇️ Baixar equipamentos.csv atualizado", data=equipamentos.to_csv(index=False).encode("utf-8"), file_name="equipamentos.csv", mime="text/csv")
            if supabase_configurado() and "id" in equipamentos.columns:
                st.markdown("---")
                st.subheader("Ativar / Inativar equipamento")
                equipamento_sel = st.selectbox("Equipamento", equipamentos["id_transformador"].astype(str).tolist(), key="equipamento_status")
                linha_sel = equipamentos[equipamentos["id_transformador"].astype(str) == equipamento_sel].iloc[0]
                ativo_atual = bool(linha_sel.get("ativo", True))
                novo_status = st.toggle("Equipamento ativo", value=ativo_atual, key=f"toggle_ativo_{equipamento_sel}")
                if novo_status != ativo_atual:
                    try:
                        supabase_atualizar_equipamento(int(linha_sel["id"]), novo_status)
                        st.success(f"{equipamento_sel} {'ativado' if novo_status else 'inativado'} com sucesso.")
                        st.rerun()
                    except requests.RequestException as erro:
                        st.error(f"Erro ao atualizar o status do equipamento: {erro}")
    with aba_leitura:
        st.subheader("Registrar novo resultado de gás (DGA)")
        equipamentos_ativos = equipamentos[equipamentos["ativo"] == True].copy() if not equipamentos.empty and "ativo" in equipamentos.columns else equipamentos
        if equipamentos_ativos.empty:
            st.warning("Cadastre um equipamento ativo antes de lançar leituras.")
        else:
            with st.form("form_leitura", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    transformador = st.selectbox("Transformador", sorted(equipamentos_ativos["id_transformador"].astype(str).unique()))
                    data_amostra = st.date_input("Data de Amostragem", value=date.today())
                    condicao = st.selectbox("Condição de Operação", ["Normal", "Sobrecarga", "Manutenção", "Outra"])
                with col2:
                    gas = st.selectbox("Gás", GASES_PADRAO)
                    valor_ppm = st.number_input("Valor (ppm)", min_value=0.0, step=0.1)
                enviar_leitura = st.form_submit_button("Registrar Leitura")
                if enviar_leitura:
                    nova_leitura = pd.DataFrame([{"id_transformador": transformador, "data_amostragem": pd.Timestamp(data_amostra), "condicao_operacao": condicao, "gas": gas, "valor_ppm": valor_ppm}])
                    existentes = carregar_leituras()
                    duplicado = existentes[(existentes["id_transformador"] == transformador) & (pd.to_datetime(existentes["data_amostragem"]).dt.date == data_amostra) & (existentes["gas"] == gas)]
                    if not duplicado.empty:
                        st.error(f"Já existe um resultado para {gas} no transformador {transformador} em {data_amostra}.")
                    else:
                        try:
                            if supabase_configurado():
                                supabase_inserir(nova_leitura)
                            else:
                                pd.concat([existentes, nova_leitura], ignore_index=True).to_csv(ARQ_LEIT, index=False)
                            st.success(f"Leitura registrada: {transformador} — {gas} = {valor_ppm} ppm em {data_amostra}")
                            st.cache_data.clear()
                            st.rerun()
                        except requests.RequestException as erro:
                            st.error(f"Erro ao salvar no Supabase: {erro}")
        st.markdown("---")
        leituras_atual = carregar_leituras()
        st.download_button("⬇️ Baixar backup da base DGA", data=leituras_atual.to_csv(index=False).encode("utf-8"), file_name="leituras.csv", mime="text/csv")
        st.info("A base operacional está no Supabase. O CSV acima funciona como backup e não como fonte principal dos dados." if supabase_configurado() else "⚠️ O Supabase ainda não está configurado. Neste momento o app está gravando no CSV local.")
        st.markdown("---")
        st.caption("Limiares de referência (IEC/IEEE) usados no sinal de alerta por gás:")
        st.dataframe(pd.DataFrame([{"Gás": g, "Limiar (ppm)": v} for g, v in LIMIARES_IEC.items()]), use_container_width=True)
    with aba_exclusao:
        st.subheader("Gerenciar registros DGA")
        if not supabase_configurado():
            st.warning("Configure o Supabase para habilitar a exclusão persistente de registros.")
        else:
            leituras = carregar_leituras()
            if leituras.empty:
                st.info("Não há registros DGA no Supabase.")
            else:
                transformadores = sorted(leituras["id_transformador"].unique())
                tr_excluir = st.selectbox("Transformador", transformadores, key="tr_excluir")
                datas = sorted(pd.to_datetime(leituras.loc[leituras["id_transformador"] == tr_excluir, "data_amostragem"]).dt.date.unique(), reverse=True)
                data_excluir = st.selectbox("Data da análise", datas, key="data_excluir")
                registros_data = leituras[(leituras["id_transformador"] == tr_excluir) & (pd.to_datetime(leituras["data_amostragem"]).dt.date == data_excluir)].copy()
                st.write("**Resultados encontrados:**")
                st.dataframe(registros_data[["id", "gas", "valor_ppm", "condicao_operacao"]].sort_values("gas"), use_container_width=True, hide_index=True)
                st.warning("A exclusão abaixo remove permanentemente do Supabase todos os resultados dessa análise para o transformador e a data escolhidos.")
                confirmar = st.checkbox("Confirmo que quero excluir esta análise completa.", key="confirmar_exclusao")
                if st.button("🗑️ Excluir análise DGA", type="primary", disabled=not confirmar):
                    try:
                        ids = registros_data["id"].tolist()
                        supabase_excluir(ids)
                        st.cache_data.clear()
                        st.success(f"Análise de {tr_excluir} em {data_excluir} excluída com sucesso. {len(ids)} registro(s) removido(s).")
                        st.rerun()
                    except requests.RequestException as erro:
                        st.error(f"Erro ao excluir no Supabase: {erro}")
                st.markdown("---")
                st.caption("Registros atuais no banco:")
                st.dataframe(leituras.sort_values(["id_transformador", "data_amostragem", "gas"]), use_container_width=True, hide_index=True)
                st.markdown("---")
                st.subheader("Importar histórico do CSV")
                st.caption("Use esta função quando quiser trazer para o Supabase os registros que ainda estiverem no CSV e não existirem no banco. Registros apagados não voltam automaticamente.")
                if st.button("☁️ Importar registros ausentes do leituras.csv"):
                    try:
                        quantidade = importar_historico_csv()
                        st.cache_data.clear()
                        st.success(f"{quantidade} registro(s) histórico(s) importado(s)." if quantidade else "Nenhum registro novo para importar.")
                        st.rerun()
                    except requests.RequestException as erro:
                        st.error(f"Erro ao importar para o Supabase: {erro}")

# ============================================================
# PÁGINA: DASHBOARD
# ============================================================
else:
    df = get_base_calculada()
    st.title("⚡ Monitoramento de Gases em Transformadores")
    st.markdown("---")
    if df.empty:
        st.warning("Não há dados DGA disponíveis. Se o Supabase foi configurado agora, vá em **Cadastrar Dados → Gerenciar / Excluir** e importe o histórico do CSV.")
        st.stop()
    st.sidebar.header("Filtros")
    equipamentos = carregar_equipamentos()
    if not equipamentos.empty and "ativo" in equipamentos.columns:
        ativos = set(equipamentos.loc[equipamentos["ativo"] == True, "id_transformador"].astype(str))
        transformadores = sorted(ativos)
    elif not equipamentos.empty and "id_transformador" in equipamentos.columns:
        transformadores = sorted(equipamentos["id_transformador"].astype(str).unique())
    else:
        transformadores = sorted(df["id_transformador"].astype(str).unique())
    if not transformadores:
        st.warning("Não há equipamentos cadastrados para exibição.")
        st.stop()
    transformador_sel = st.sidebar.selectbox("Transformador", transformadores)
    df_tr = df[df["id_transformador"].astype(str) == str(transformador_sel)]
    gases_disponiveis = sorted(df_tr["gas"].unique()) if not df_tr.empty else []
    gas_sel = st.sidebar.selectbox("Gás", ["(Todos)"] + gases_disponiveis)
    df_filtrado = df_tr[df_tr["gas"] == gas_sel] if gas_sel != "(Todos)" else df_tr
    st.subheader(f"Transformador: {transformador_sel}")
    if df_tr.empty:
        st.info("Este equipamento está cadastrado e ativo, mas ainda não possui resultados DGA registrados.")
        st.markdown("---")
        st.subheader("Informações do equipamento")
        equipamento_info = equipamentos[equipamentos["id_transformador"].astype(str) == str(transformador_sel)] if not equipamentos.empty and "id_transformador" in equipamentos.columns else pd.DataFrame()
        if not equipamento_info.empty:
            colunas_info = [c for c in ["id_transformador", "fabricante", "ano_fabricacao", "potencia_kva", "tensao_kv", "volume_oleo", "ativo"] if c in equipamento_info.columns]
            st.dataframe(equipamento_info[colunas_info], use_container_width=True, hide_index=True)
        st.stop()
    col1, col2, col3 = st.columns(3)
    total = len(df_filtrado)
    criticos = (df_filtrado["classificacao_final"] == "Crítico").sum()
    atencao = (df_filtrado["classificacao_final"] == "Atenção").sum()
    col1.metric("Total de Registros", total)
    col2.metric("⚠️ Atenção", int(atencao))
    col3.metric("🔴 Crítico", int(criticos))
    st.markdown("---")
    st.subheader("Evolução dos Gases ao Longo do Tempo")
    def plot_gas(df_gas, gas_nome, height):
        df_gas = df_gas.sort_values("data_amostragem")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_gas["data_amostragem"], y=df_gas["x"], mode="lines+markers", name=gas_nome, line=dict(color="royalblue")))
        if "ucl_x" in df_gas.columns:
            fig.add_trace(go.Scatter(x=df_gas["data_amostragem"], y=df_gas["ucl_x"], mode="lines", name="UCL", line=dict(color="red", dash="dash")))
            fig.add_trace(go.Scatter(x=df_gas["data_amostragem"], y=df_gas["lcl_x"], mode="lines", name="LCL", line=dict(color="red", dash="dash")))
        if height > 350 and "ewma" in df_gas.columns:
            fig.add_trace(go.Scatter(x=df_gas["data_amostragem"], y=df_gas["ewma"], mode="lines", name="EWMA", line=dict(color="orange", dash="dot")))
        fig.update_layout(title=f"Gás: {gas_nome}", xaxis_title="Data", yaxis_title="Concentração (ppm)", height=height)
        return fig
    if gas_sel == "(Todos)":
        for gas in gases_disponiveis:
            df_gas = df_tr[df_tr["gas"] == gas]
            if not df_gas.empty:
                st.plotly_chart(plot_gas(df_gas, gas, 350), use_container_width=True)
    else:
        st.plotly_chart(plot_gas(df_filtrado, gas_sel, 450), use_container_width=True)
    st.markdown("---")
    st.subheader("Classificação Final por Gás")
    resumo = df_tr.groupby(["gas", "classificacao_final"]).size().reset_index(name="count")
    fig_class = px.bar(resumo, x="gas", y="count", color="classificacao_final", color_discrete_map={"Estável": "green", "Atenção": "orange", "Crítico": "red"}, barmode="group", title="Distribuição das Classificações por Gás", labels={"gas": "Gás", "count": "Quantidade", "classificacao_final": "Classificação"})
    fig_class.update_layout(height=400)
    st.plotly_chart(fig_class, use_container_width=True)
    st.markdown("---")
    st.subheader("Dados Detalhados")
    colunas_exibir = ["id_transformador", "data_amostragem", "gas", "x", "classificacao_final", "prioridade_acao", "sinal_cep", "sinal_ewma", "sinal_cusum", "sinal_iec", "total_sinais", "classificacao_tendencia"]
    colunas_validas = [c for c in colunas_exibir if c in df_filtrado.columns]
    st.dataframe(df_filtrado[colunas_validas].sort_values("data_amostragem"), use_container_width=True)