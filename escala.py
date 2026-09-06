import streamlit as st
import pandas as pd
from database import guardar_datos_usuario

def render(supabase):
    st.title("📊 Escala de Notas")
    st.write("Configura los rangos de tu escala de calificaciones.")

    # Si no hay datos, creamos una tabla por defecto (escala típica del 1 al 20)
    if st.session_state["escala_df"] is None or st.session_state["escala_df"].empty:
        data_inicial = {
            "Nota Mínima": [0, 10, 14, 17, 19],
            "Nota Máxima": [9.99, 13.99, 16.99, 18.99, 20],
            "Equivalencia": ["Reprobado", "Regular", "Bueno", "Muy Bueno", "Excelente"]
        }
        st.session_state["escala_df"] = pd.DataFrame(data_inicial)

    # Tabla editable para que puedas personalizar tus rangos
    df_editado = st.data_editor(
        st.session_state["escala_df"],
        num_rows="dynamic",
        use_container_width=True,
        key="editor_escala"
    )

    if st.button("Guardar Cambios de Escala"):
        st.session_state["escala_df"] = df_editado
        guardar_datos_usuario(supabase)
        st.success("¡Escala de notas actualizada correctamente!")
