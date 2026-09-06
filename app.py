import streamlit as st
import extra_streamlit_components as st_cookie
from supabase import create_client, Client

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="App Universitaria - Gestión de Materias",
    page_icon="🎓",
    layout="wide",
)

# --- 2. GESTOR DE COOKIES Y SUPABASE ---
cookie_manager = st_cookie.CookieManager()

@st.cache_resource
def init_supabase() -> Client:
    raw_url = str(st.secrets["SUPABASE_URL"]).strip()
    if "/rest/v1" in raw_url:
        raw_url = raw_url.split("/rest/v1")[0]
    key = str(st.secrets["SUPABASE_KEY"]).strip()
    return create_client(raw_url.rstrip("/"), key)

supabase = init_supabase()

# --- 3. INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
if "usuario" not in st.session_state:
    st.session_state["usuario"] = None
if "pensum_df" not in st.session_state:
    st.session_state["pensum_df"] = None
if "evaluaciones" not in st.session_state:
    st.session_state["evaluaciones"] = {}
if "horario_df" not in st.session_state:
    st.session_state["horario_df"] = None
if "escala_df" not in st.session_state:
    st.session_state["escala_df"] = None

# --- 4. ENRUTAMIENTO Y VISTAS ---
from auth import gestionar_autenticacion
from views import pensum, horario, escala, asistente, pomodoro

if st.session_state["usuario"] is None:
    gestionar_autenticacion(supabase, cookie_manager)
else:
    # Barra lateral de navegación ultraligera
    st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")
    
    with st.sidebar.expander("⚙️ Configuración de IA"):
        st.session_state["modelo_seleccionado"] = st.selectbox(
            "Modelo", ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash"], index=0
        )

    st.sidebar.markdown("---")
    vista = st.sidebar.radio("Navegación", [
        "📚 Pensum y Calificaciones",
        "📅 Horario de Clases",
        "📊 Escala de Notas",
        "🤖 Asistente Virtual IA",
        "⏱️ Pomodoro de Estudio"
    ])

    if st.sidebar.button("Cerrar Sesión"):
        supabase.auth.sign_out()
        st.session_state["usuario"] = None
        st.rerun()

    # Enrutador de vistas
    if vista == "📚 Pensum y Calificaciones":
        pensum.render(supabase)
    elif vista == "📅 Horario de Clases":
        horario.render(supabase)
    elif vista == "📊 Escala de Notas":
        escala.render(supabase)
    elif vista == "🤖 Asistente Virtual IA":
        asistente.render()
    elif vista == "⏱️ Pomodoro de Estudio":
        pomodoro.render()
