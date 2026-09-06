import streamlit as st
from database import obtener_datos_pensum, actualizar_calificacion

def render():
    st.subheader("Gestión de Pensum y Calificaciones")
    
    # Obtener datos usando la capa de base de datos
    datos = obtener_datos_pensum()
    
    if datos:
        for item in datos:
            st.write(f"Materia: {item.get('nombre')} - Nota: {item.get('calificacion')}")
    else:
        st.info("No hay registros en el pensum.")
