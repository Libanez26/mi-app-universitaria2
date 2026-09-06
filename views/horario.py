import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
from google import genai
from google.genai import types
from database import guardar_datos_usuario

def render(supabase):
    st.subheader("📅 Gestión de Horario de Clases")

    modelos_disponibles = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash"]
    modelo_seleccionado = st.session_state.get("modelo_seleccionado", modelos_disponibles[0])

    components.html(
        """
        <div style="background-color: #1e1e1e; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #333; margin-bottom: 20px;">
            <span style="color: #a0a0a0; font-size: 14px; font-family: sans-serif;">🕒 Hora Actual del Sistema: </span>
            <span id="reloj-digital" style="color: #00ffcc; font-size: 20px; font-weight: bold; font-family: monospace;">--:--:--</span>
            <span id="fecha-digital" style="color: #ffffff; font-size: 14px; margin-left: 15px; font-family: sans-serif;">---</span>
        </div>
        <script>
            function actualizarReloj() {
                const ahora = new Date();
                const hora = ahora.toLocaleTimeString();
                const opciones = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
                const fecha = ahora.toLocaleDateString('es-ES', opciones);
                
                document.getElementById('reloj-digital').innerText = hora;
                document.getElementById('fecha-digital').innerText = fecha;
            }
            setInterval(actualizarReloj, 1000);
            actualizarReloj();
        </script>
        """,
        height=70,
    )

    if st.session_state.get("horario_df") is None:
        st.info("👋 Sube tu horario de clases en formato PDF para organizarlo automáticamente.")
        uploaded_horario = st.file_uploader(
            "Sube el PDF de tu horario", type=["pdf"], key="file_uploader_horario"
        )

        if uploaded_horario and st.button("📊 Procesar y Organizar Horario", key="btn_procesar_horario"):
            with st.spinner("Procesando horario con Gemini..."):
                try:
                    api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                    client = genai.Client(api_key=api_key)

                    pdf_bytes = uploaded_horario.read()
                    pdf_part = types.Part.from_bytes(
                        data=pdf_bytes, mime_type="application/pdf"
                    )

                    prompt = """
                    Extrae exhaustivamente todas las clases del documento de horario proporcionado.
                    Devuelve la respuesta ÚNICAMENTE como una estructura JSON válida, que sea una lista de objetos con exactamente estas claves y ordenadas exactamente de esta forma:
                    [
                      {
                        "dia": "Lunes",
                        "materia": "Matemática I",
                        "aula": "Aula 101",
                        "inicio": "08:00 AM",
                        "fin": "10:00 AM"
                      }
                    ]
                    Asegúrate de que las horas estén en formato de 12 horas con AM o PM.
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

                        data_horario = json.loads(clean_text.strip())
                        df_h = pd.DataFrame(data_horario)

                        df_h.columns = [c.lower().strip().replace(" ", "_") for c in df_h.columns]
                        
                        columnas_deseadas = ["dia", "materia", "aula", "inicio", "fin"]
                        for col in columnas_deseadas:
                            if col not in df_h.columns:
                                df_h[col] = ""
                        df_h = df_h[columnas_deseadas]

                        dias_map = {
                            "lunes": 1, "martes": 2, "miércoles": 3, "miercoles": 3,
                            "jueves": 4, "viernes": 5, "sábado": 6, "sabado": 6, "domingo": 7,
                        }
                        df_h["d_orden"] = df_h["dia"].str.lower().map(dias_map).fillna(8)
                        df_h = df_h.sort_values(by=["d_orden", "inicio"])
                        df_h = df_h.drop(columns=["d_orden"])

                        st.session_state["horario_df"] = df_h
                        guardar_datos_usuario(supabase)
                        st.success("¡Horario procesado, organizado y guardado con éxito!")
                        st.rerun()

                except Exception as err:
                    st.error(f"Error procesando el horario: {err}")
    else:
        if st.button("🗑️ Eliminar / Volver a subir Horario", key="btn_eliminar_horario"):
            st.session_state["horario_df"] = None
            guardar_datos_usuario(supabase)
            st.rerun()

        df_horario_actual = st.session_state["horario_df"]

        columnas_deseadas = ["dia", "materia", "aula", "inicio", "fin"]
        for col in columnas_deseadas:
            if col not in df_horario_actual.columns:
                df_horario_actual[col] = ""
        df_horario_actual = df_horario_actual[columnas_deseadas]

        st.markdown("### 📋 Tu Horario Académico Organizado")

        df_editado = st.data_editor(
            df_horario_actual,
            use_container_width=True,
            hide_index=True,
            key="editor_horario",
        )
        st.session_state["horario_df"] = df_editado
