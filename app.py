import streamlit as st
import extra_streamlit_components as st_cookie
from database import inicializar_supabase
from views.auth import gestionar_autenticacion
from views import pensum, horario, escala, asistente, pomodoro

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
if "horario_df" not in st.session_state:
    st.session_state["horario_df"] = None
if "escala_df" not in st.session_state:
    st.session_state["escala_df"] = None

# --- 4. CONTROL DE ACCESO ---
if st.session_state["usuario"] is None:
    gestionar_autenticacion(supabase, cookie_manager)
else:
    st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")
    
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
