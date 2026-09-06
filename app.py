import streamlit as st
from views import pensum

st.set_page_config(
    page_title="Sistema de Gestión",
    page_icon="📚",
    layout="wide"
)

# Menú lateral simple
st.sidebar.title("Navegación")
modulo = st.sidebar.selectbox("Selecciona un módulo", ["Pensum y Notas", "Rutas de Despacho"])

if modulo == "Pensum y Notas":
    pensum.render()
elif modulo == "Rutas de Despacho":
    st.subheader("Módulo de Rutas")
    # Aquí llamarías a views/rutas.py en el futuro
