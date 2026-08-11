import json
import pandas as pd
import streamlit as st
from pypdf import PdfReader
from google import genai
from google.genai import types
from supabase import create_client, Client

# MUST BE THE FIRST STREAMLIT COMMAND
st.set_page_config(
    page_title="App Universitaria - Gestión de Materias",
    page_icon="🎓",
    layout="wide"
)

# --- INICIALIZACIÓN DE SERVICIOS ---
@st.cache_resource
def init_supabase() -> Client:
    raw_url = str(st.secrets["SUPABASE_URL"]).strip()
    if "/rest/v1" in raw_url:
        raw_url = raw_url.split("/rest/v1")[0]
    raw_url = raw_url.rstrip("/")
    
    key = str(st.secrets["SUPABASE_KEY"]).strip()
    return create_client(raw_url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Error al conectar con Supabase: {e}")

# --- ESTADO DE SESIÓN ---
if "usuario" not in st.session_state:
    st.session_state["usuario"] = None
if "pensum_df" not in st.session_state:
    st.session_state["pensum_df"] = None
if "evaluaciones" not in st.session_state:
    st.session_state["evaluaciones"] = {}

# --- FUNCIONES DE BASE DE DATOS ---
def cargar_datos_usuario(user_id):
    try:
        res = supabase.table("perfiles_usuario").select("*").eq("id", user_id).execute()
        if res.data:
            datos = res.data[0]
            if datos.get("pensum_data"):
                st.session_state["pensum_df"] = pd.DataFrame(datos["pensum_data"])
            if datos.get("evaluaciones_data"):
                st.session_state["evaluaciones"] = datos["evaluaciones_data"]
    except Exception as e:
        st.error(f"Error cargando datos de la base de datos: {e}")

def guardar_datos_usuario():
    if not st.session_state["usuario"]:
        return
    
    user_id = st.session_state["usuario"].id
    correo = st.session_state["usuario"].email
    
    pensum_json = st.session_state["pensum_df"].to_dict("records") if st.session_state["pensum_df"] is not None else None
    evals_json = st.session_state["evaluaciones"]
    
    data = {
        "id": user_id,
        "correo": correo,
        "pensum_data": pensum_json,
        "evaluaciones_data": evals_json
    }
    
    try:
        supabase.table("perfiles_usuario").upsert(data).execute()
        st.toast("💾 Cambios guardados automáticamente", icon="☁️")
    except Exception as e:
        st.error(f"Error al guardar datos: {e}")

# --- LÓGICA DE CONTROL DE PRELACIONES ---
def verificar_disponibilidad(row, df_completo):
    prelaciones_raw = str(row.get("prelaciones", "Ninguna")).strip()
    
    if prelaciones_raw.lower() in ["ninguna", "ninguno", "-", "", "none", "sin prelación"]:
        return True, "Disponible"
    
    codigos_aprobados = df_completo[df_completo["estado"] == "Aprobada"]["codigo"].tolist()
    materias_pre = [p.strip() for p in prelaciones_raw.replace("/", ",").split(",") if p.strip()]
    faltantes = []
    
    for pre in materias_pre:
        if pre not in codigos_aprobados and pre.lower() not in ["ninguna", ""]:
            faltantes.append(pre)
            
    if len(faltantes) > 0:
        return False, f"🔒 Bloqueada (Requiere aprobar: {', '.join(faltantes)})"
    
    return True, "Disponible"

# --- CÁLCULO DE PROMEDIO GLOBAL / ÍNDICE ACADÉMICO ---
def calcular_indice_academico(df_pensum, evaluaciones):
    total_creditos = 0
    puntos_acumulados = 0.0
    
    for _, row in df_pensum.iterrows():
        cod = row["codigo"]
        cred = row.get("creditos", 0)
        
        if cod in evaluaciones:
            plan = evaluaciones[cod].get("plan", [])
            if plan:
                df_plan = pd.DataFrame(plan)
                if "Nota" in df_plan.columns and "Valor (%)" in df_plan.columns:
                    nota_mat = ((df_plan["Nota"] / 20.0) * (df_plan["Valor (%)"] / 100.0) * 20.0).sum()
                    if row["estado"] in ["Aprobada", "Reprobada", "En Curso"]:
                        puntos_acumulados += nota_mat * cred
                        total_creditos += cred

    if total_creditos > 0:
        return puntos_acumulados / total_creditos
    return 0.0

# --- PANTALLA DE AUTENTICACIÓN ---
if st.session_state["usuario"] is None:
    st.title("🎓 Bienvenido a Mi App Universitaria")
    st.subheader("Inicia sesión o regístrate para gestionar tu pensum e historial académico")

    tab_login, tab_registro = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])

    with tab_login:
        with st.form("form_login"):
            email_login = st.text_input("Correo electrónico")
            pass_login = st.text_input("Contraseña", type="password")
            submit_login = st.form_submit_button("Ingresar")

            if submit_login:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email_login.strip(), "password": pass_login.strip()})
                    st.session_state["usuario"] = res.user
                    cargar_datos_usuario(res.user.id)
                    st.success("¡Sesión iniciada con éxito!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al iniciar sesión: {e}")

    with tab_registro:
        with st.form("form_registro"):
            email_reg = st.text_input("Correo electrónico para el registro")
            pass_reg = st.text_input("Contraseña", type="password")
            submit_reg = st.form_submit_button("Crear Cuenta")

            if submit_reg:
                try:
                    res = supabase.auth.sign_up({"email": email_reg.strip(), "password": pass_reg.strip()})
                    if res.user:
                        st.success("¡Cuenta creada exitosamente! Ahora puedes iniciar sesión.")
                except Exception as e:
                    st.error(f"Error al registrarse: {e}")

# --- APLICACIÓN PRINCIPAL (USUARIO LOGUEADO) ---
else:
    # BARRA LATERAL
    st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")
    
    # --- SELECTOR DINÁMICO DE MODELOS DE GEMINI ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Configuración de IA")
    modelo_seleccionado = st.sidebar.selectbox(
        "Selecciona el Modelo",
        [
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.6-flash",
            "gemini-2.5-flash"
        ],
        index=0,
        help="Elige un modelo alternativo si alcanzas el límite de solicitudes por minuto (RPM)."
    )
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Cerrar Sesión", key="btn_logout"):
        supabase.auth.sign_out()
        st.session_state["usuario"] = None
        st.session_state["pensum_df"] = None
        st.session_state["evaluaciones"] = {}
        st.rerun()

    st.title("🎓 Mi App Universitaria")

    # CREACIÓN DE PESTAÑAS PRINCIPALES
    tab_pensum, tab_horario, tab_chat = st.tabs([
        "📚 Pensum y Calificaciones", 
        "📅 Horario de Clases", 
        "🤖 Chat con Gemini"
    ])

    # ==========================================
    # PESTAÑA 1: PENSUM Y CALIFICACIONES
    # ==========================================
    with tab_pensum:
        st.subheader("📋 Pensum Estructurado por Niveles")

        if st.session_state["pensum_df"] is None:
            st.info("👋 Carga tu pensum en formato PDF para organizar tus niveles académicos.")
            uploaded_file = st.file_uploader("Sube el PDF de tu pensum universitario", type=["pdf"])

            if uploaded_file and st.button("📊 Organizar Pensum en Tabla"):
                with st.spinner("Procesando pensum con Gemini..."):
                    try:
                        api_key = st.secrets["GEMINI_API_KEY"]
                        client = genai.Client(api_key=api_key)

                        pdf_bytes = uploaded_file.read()
                        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

                        prompt = """
                        Actúa como un extractor de datos profesional. Analiza el documento PDF y extrae todas las materias.
                        Tu respuesta DEBE ser ÚNICAMENTE un array JSON válido, sin texto introductorio, 
                        sin explicaciones y sin formato Markdown (nada de ```json).
                        
                        Formato requerido:
                        [
                          {"semestre": "Semestre I", "codigo": "MAT-101", "materia": "Matemática I", "creditos": 4, "prelaciones": "Ninguna"}
                        ]
                        Si falta un dato, usa "N/A" o 0 según corresponda.
                        """

                        response = client.models.generate_content(
                            model=modelo_seleccionado,
                            contents=[prompt, pdf_part]
                        )

                        raw_text = response.text.strip()
                        clean_text = raw_text.replace("
