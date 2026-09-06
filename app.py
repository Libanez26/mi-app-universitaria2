import streamlit as st
import extra_streamlit_components as st_cookie
from supabase import create_client
from views import pensum, horario, asistente, pomodoro, escala

st.set_page_config(page_title="App Universitaria", page_icon="🎓", layout="wide")

# Inicialización de Supabase y Cookies de sesión...
# (Aquí mantienes tu lógica de autenticación)

if st.session_state["usuario"] is not None:
    st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")
    
    # Navegación por vistas modulares
    menu = st.sidebar.radio("Navegación", [
        "Pensum y Calificaciones", 
        "Horario de Clases", 
        "Asistente Virtual", 
        "Pomodoro", 
        "Escala Evaluativa"
    ])
    
    if menu == "Pensum y Calificaciones":
        pensum.render()
    elif menu == "Horario de Clases":
        horario.render()
    elif menu == "Asistente Virtual":
        asistente.render()
    elif menu == "Pomodoro":
        pomodoro.render()
    elif menu == "Escala Evaluativa":
        escala.render()
