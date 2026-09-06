import streamlit as st
import pandas as pd
from database import guardar_datos_usuario

def render(supabase):
    st.subheader("⚖️ Escala Evaluativa y Ponderaciones")
    
    if "escala_df" not in st.session_state:
        st.session_state["escala_df"] = pd.DataFrame(
            columns=["Calificación", "Nota Mínima", "Nota Máxima", "Equivalencia"]
        )

    st.write("Configura o visualiza la escala de notas y ponderaciones de tu institución.")

    df_escala = st.session_state["escala_df"]
    
    df_editado = st.data_editor(
        df_escala,
        use_container_width=True,
        num_rows="dynamic",
        key="editor_escala",
    )
    st.session_state["escala_df"] = df_editado

    if st.button("💾 Guardar Escala", key="btn_guardar_escala"):
        guardar_datos_usuario(supabase)
        st.success("¡Escala guardada con éxito!")
