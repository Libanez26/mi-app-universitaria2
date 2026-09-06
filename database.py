import streamlit as st
import pandas as pd
import datetime
from supabase import create_client, Client

@st.cache_resource
def inicializar_supabase() -> Client:
    raw_url = str(st.secrets["SUPABASE_URL"]).strip()
    if "/rest/v1" in raw_url:
        raw_url = raw_url.split("/rest/v1")[0]
    key = str(st.secrets["SUPABASE_KEY"]).strip()
    return create_client(raw_url.rstrip("/"), key)

def cargar_datos_usuario(supabase: Client, user_id: str):
    try:
        res = supabase.table("perfiles_usuario").select("*").eq("id", user_id).execute()
        if res.data and len(res.data) > 0:
            datos = res.data[0]
            if datos.get("pensum_data"):
                st.session_state["pensum_df"] = pd.DataFrame(datos["pensum_data"])
            
            if datos.get("evaluaciones_data"):
                evals_cargadas = datos["evaluaciones_data"]
                for cod, info in evals_cargadas.items():
                    if "plan" in info:
                        for item in info["plan"]:
                            if "Fecha" in item and isinstance(item["Fecha"], str):
                                try:
                                    item["Fecha"] = datetime.datetime.strptime(item["Fecha"], "%Y-%m-%d").date()
                                except ValueError:
                                    item["Fecha"] = datetime.date.today()
                st.session_state["evaluaciones"] = evals_cargadas

            if datos.get("horario_data"):
                st.session_state["horario_df"] = pd.DataFrame(datos["horario_data"])

            if datos.get("escala_data"):
                st.session_state["escala_df"] = pd.DataFrame(datos["escala_data"])
    except Exception as e:
        st.error(f"Error cargando datos de la base de datos: {e}")

def guardar_datos_usuario(supabase: Client):
    if not st.session_state.get("usuario"):
        return

    user_id = st.session_state["usuario"].id
    correo = st.session_state["usuario"].email

    pensum_json = (
        st.session_state["pensum_df"].to_dict("records")
        if st.session_state["pensum_df"] is not None
        else None
    )
    
    evals_json = {}
    for cod, info in st.session_state["evaluaciones"].items():
        evals_json[cod] = {
            "estado": info.get("estado", "No Inscrita"),
            "plan": []
        }
        for item in info.get("plan", []):
            item_copia = item.copy()
            if "Fecha" in item_copia and isinstance(item_copia["Fecha"], (datetime.date, datetime.datetime)):
                item_copia["Fecha"] = item_copia["Fecha"].strftime("%Y-%m-%d")
            evals_json[cod]["plan"].append(item_copia)

    horario_json = (
        st.session_state["horario_df"].to_dict("records")
        if st.session_state["horario_df"] is not None
        else None
    )

    escala_json = (
        st.session_state["escala_df"].to_dict("records")
        if st.session_state["escala_df"] is not None
        else None
    )

    data = {
        "id": user_id,
        "correo": correo,
        "pensum_data": pensum_json,
        "evaluaciones_data": evals_json,
        "horario_data": horario_json,
        "escala_data": escala_json,
    }

    try:
        supabase.table("perfiles_usuario").upsert(data).execute()
        st.toast("💾 Cambios guardados automáticamente", icon="☁️")
    except Exception as e:
        st.error(f"Error al guardar datos: {e}")
