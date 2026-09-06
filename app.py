import streamlit as st
import extra_streamlit_components as st_cookie
from database import inicializar_supabase, cargar_datos_usuario

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="App Universitaria",
    page_icon="🎓",
    layout="wide",
)

# --- 2. INICIALIZACIÓN DE SERVICIOS ---
cookie_manager = st_cookie.CookieManager()
supabase = inicializar_supabase()

# --- 3. ESTADO DE SESIÓN ---
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

# --- 4. IMPORTACIÓN DE VISTAS Y MÓDULOS ---
from auth import gestionar_autenticacion
from views import pensum, horario, escala, asistente, pomodoro

# --- 5. CONTROL DE ACCESO Y ENRUTAMIENTO ---
device_token_cookie = cookie_manager.get(cookie="dispositivo_confiable_token")

if st.session_state["usuario"] is None:
    gestionar_autenticacion(supabase, cookie_manager)
else:
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
        st.session_state["pensum_df"] = None
        st.session_state["evaluaciones"] = {}
        st.session_state["horario_df"] = None
        st.session_state["escala_df"] = None
        st.rerun()

    # Enrutamiento de vistas
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
