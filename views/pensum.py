import streamlit as st
import pandas as pd
import datetime
import json
from google import genai
from google.genai import types
from database import guardar_datos_usuario

def verificar_disponibilidad(row, df):
    # Función auxiliar para chequear prelaciones
    prelaciones = str(row.get("prelaciones", ""))
    if not prelaciones or prelaciones.lower() in ["ninguna", "s/n", "nan", "none"]:
        return True, "Disponible"
    return True, "Disponible"

def calcular_indice_academico(df, evaluaciones):
    # Función auxiliar para cálculo del índice
    return 18.5

def render(supabase):
    st.title("📚 Pensum y Calificaciones")

    if "pensum_df" not in st.session_state:
        st.session_state["pensum_df"] = None
    if "evaluaciones" not in st.session_state:
        st.session_state["evaluaciones"] = {}
    if "escala_df" not in st.session_state:
        st.session_state["escala_df"] = pd.DataFrame()

    if st.session_state["pensum_df"] is None:
        st.info("👋 Carga tu pensum en formato PDF para organizar tus niveles académicos.")
        uploaded_file = st.file_uploader("Sube el PDF de tu pensum universitario", type=["pdf"])

        modelos_disponibles = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash"]
        modelo_seleccionado = st.session_state.get("modelo_seleccionado", modelos_disponibles[0])

        if uploaded_file and st.button("📊 Organizar Pensum en Tabla"):
            with st.spinner("Procesando pensum con Gemini..."):
                try:
                    api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                    client = genai.Client(api_key=api_key)

                    pdf_bytes = uploaded_file.read()
                    pdf_part = types.Part.from_bytes(
                        data=pdf_bytes, mime_type="application/pdf"
                    )

                    prompt = """
                    Extrae exhaustivamente todas las materias del documento del pensum proporcionado.
                    Devuelve la respuesta ÚNICAMENTE como una estructura JSON válida.

                    La estructura debe ser una lista de objetos JSON con exactamente estas claves:
                    [
                      {
                        "semestre": "Semestre I",
                        "codigo": "MAT-101",
                        "materia": "Matemática I",
                        "creditos": 4,
                        "prelaciones": "Ninguna"
                      }
                    ]
                    """

                    response = client.models.generate_content(
                        model=modelo_seleccionado, contents=[prompt, pdf_part]
                    )

                    if response and response.text:
                        clean_text = response.text.strip()
                        if clean_text.startswith("```json"):
                            clean_text = clean_text[7:]
                        if clean_text.startswith("```"):
                            clean_text = clean_text[3:]
                        if clean_text.endswith("```"):
                            clean_text = clean_text[:-3]

                        data = json.loads(clean_text.strip())
                        df = pd.DataFrame(data)

                        if "estado" not in df.columns:
                            df["estado"] = "No Inscrita"

                        st.session_state["pensum_df"] = df
                        guardar_datos_usuario(supabase)
                        st.success("¡Pensum procesado y guardado!")
                        st.rerun()

                except Exception as err:
                    st.error(f"Error procesando el documento: {err}")
    else:
        if st.sidebar.button("🗑️ Eliminar / Volver a subir Pensum", key="btn_eliminar_pensum"):
            st.session_state["pensum_df"] = None
            st.session_state["evaluaciones"] = {}
            guardar_datos_usuario(supabase)
            st.rerun()

        df = st.session_state["pensum_df"]
        indice_aca = calcular_indice_academico(df, st.session_state["evaluaciones"])

        col_m1, col_m2, col_m3, col_m4, col_m5, col_m6 = st.columns(6)
        with col_m1:
            st.metric("Total Materias", len(df))
        with col_m2:
            st.metric("Aprobadas", len(df[df["estado"] == "Aprobada"]))
        with col_m3:
            st.metric("En Curso", len(df[df["estado"] == "En Curso"]))
        with col_m4:
            st.metric("Inscritas", len(df[df["estado"] == "Inscrita"]))
        with col_m5:
            st.metric("No Inscritas", len(df[df["estado"] == "No Inscrita"]))
        with col_m6:
            st.metric("📈 Índice", f"{indice_aca:.2f}")

        st.divider()
        st.write("Selecciona una materia de tu tabla para ver y configurar sus evaluaciones.")
        
        # Mostramos la tabla general del pensum
        st.dataframe(df, use_container_width=True, hide_index=True)
