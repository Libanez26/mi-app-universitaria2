import streamlit as st
import pandas as pd
import datetime
from google import genai
from database import guardar_datos_usuario

def render(supabase):
    st.subheader("🤖 Asistente Virtual Universitario")
    st.write(
        "Elige si prefieres interactuar mediante el menú de botones guiados o conversar libremente con le chat de IA."
    )

    tipo_asistente = st.radio(
        "Selecciona el modo de interacción:",
        ["🧭 Asistente Guiado (Solo Botones)", "💬 Chat Libre (Conversacional)"],
        horizontal=True,
        key="selector_modo_asistente",
    )

    if "modo_asistente" not in st.session_state:
        st.session_state["modo_asistente"] = "menu_principal"
    if "sub_modo" not in st.session_state:
        st.session_state["sub_modo"] = None
    
    mensaje_inicial_comun = "¡Hola! Soy tu asistente virtual académico. ¿En qué te puedo ayudar hoy?"

    if "mensajes_guiado" not in st.session_state:
        st.session_state["mensajes_guiado"] = [{
            "role": "assistant",
            "content": mensaje_inicial_comun,
        }]
    if "mensajes_conversacional" not in st.session_state:
        st.session_state["mensajes_conversacional"] = [{
            "role": "assistant",
            "content": mensaje_inicial_comun,
        }]

    st.markdown("""
        <style>
        .chat-container {
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding: 10px;
            max-height: 450px;
            overflow-y: auto;
            background-color: #0e1117;
            border-radius: 10px;
            margin-bottom: 15px;
        }
        .msg-user {
            background-color: #2b313e;
            color: #ffffff;
            padding: 10px 14px;
            border-radius: 12px 12px 2px 12px;
            align-self: flex-end;
            max-width: 75%;
            box-shadow: 0 1px 2px rgba(0,0,0,0.2);
        }
        .msg-assistant {
            background-color: #1f242d;
            color: #e0e0e0;
            padding: 10px 14px;
            border-radius: 12px 12px 12px 2px;
            align-self: flex-start;
            max-width: 75%;
            border-left: 4px solid #4CAF50;
            box-shadow: 0 1px 2px rgba(0,0,0,0.2);
        }
        .msg-title {
            font-size: 0.75rem;
            color: #888888;
            margin-bottom: 4px;
            font-weight: bold;
        }
        </style>
    """, unsafe_allow_html=True)

    if "Asistente Guiado" in tipo_asistente:
        col_bt1, col_bt2 = st.columns([4, 1])
        with col_bt2:
            if st.button("🗑️ Reiniciar", key="btn_reiniciar_guiado"):
                st.session_state["mensajes_guiado"] = [{
                    "role": "assistant",
                    "content": mensaje_inicial_comun,
                }]
                st.session_state["modo_asistente"] = "menu_principal"
                st.session_state["sub_modo"] = None
                st.rerun()

        chat_html_g = '<div class="chat-container">'
        for mensaje in st.session_state["mensajes_guiado"]:
            if mensaje["role"] == "user":
                chat_html_g += f'<div class="msg-user"><div class="msg-title">Tú</div>{mensaje["content"]}</div>'
            else:
                chat_html_g += f'<div class="msg-assistant"><div class="msg-title">Asistente Guiado</div>{mensaje["content"]}</div>'
        chat_html_g += '</div>'
        st.markdown(chat_html_g, unsafe_allow_html=True)

        st.markdown("---")

        if st.session_state["modo_asistente"] == "menu_principal":
            st.markdown("### 📌 Menú de Opciones Disponibles")
            c1, c2 = st.columns(2)

            with c1:
                if st.button("📊 Consultar Notas por Materia", use_container_width=True, key="btn_g_notas"):
                    st.session_state["modo_asistente"] = "notas_filtro_estado"
                    st.rerun()

                if st.button("🕒 ¿A qué hora es la clase de...?", use_container_width=True, key="btn_g_horario"):
                    st.session_state["modo_asistente"] = "horario_por_materia"
                    st.rerun()

            with c2:
                if st.button("⏳ Ver Próximas 5 Tareas / Evaluaciones", use_container_width=True, key="btn_g_tareas"):
                    lista_proximas = []
                    pensum_df = st.session_state.get("pensum_df")
                    evaluaciones_dict = st.session_state.get("evaluaciones", {})

                    if pensum_df is not None and not pensum_df.empty:
                        col_est = next((c for c in pensum_df.columns if "estado" in c.lower() or "status" in c.lower()), None)
                        col_cod = next((c for c in pensum_df.columns if "codigo" in c.lower() or "código" in c.lower()), None)
                        col_mat = next((c for c in pensum_df.columns if "materia" in c.lower() or "asignatura" in c.lower()), None)

                        if col_est and col_cod and col_mat:
                            materias_en_curso = pensum_df[pensum_df[col_est].astype(str).str.lower() == "en curso"]
                            for _, row in materias_en_curso.iterrows():
                                cod = str(row[col_cod])
                                nom_materia = str(row[col_mat])
                                if cod in evaluaciones_dict:
                                    plan = evaluaciones_dict[cod].get("plan", [])
                                    for ev in plan:
                                        if not ev.get("Entregada", False):
                                            lista_proximas.append({
                                                "materia": nom_materia,
                                                "codigo": cod,
                                                "evaluacion": ev.get("Evaluación", "Evaluación"),
                                                "tema": ev.get("Tema", ""),
                                                "fecha": ev.get("Fecha", datetime.date.today())
                                            })

                    lista_proximas = sorted(lista_proximas, key=lambda x: str(x["fecha"]))
                    primeras_5 = lista_proximas[:5]

                    if primeras_5:
                        tareas_destacadas = "⏳ **Primeras 5 actividades próximas (Materias en Curso):**\n\n"
                        for idx, item in enumerate(primeras_5, 1):
                            tareas_destacadas += f"{idx}. **{item['materia']}** ({item['codigo']}) - *{item['evaluacion']}* ({item['tema']}) | 📅 **Fecha:** {item['fecha']}\n"
                    else:
                        tareas_destacadas = "⏳ No hay actividades pendientes registradas para las materias en curso actualmente."

                    st.session_state["mensajes_guiado"].append({"role": "user", "content": "Ver las 5 próximas actividades de materias en curso"})
                    st.session_state["mensajes_guiado"].append({"role": "assistant", "content": tareas_destacadas})
                    st.rerun()

                if st.button("⚠️ Alertas o Materias con Riesgo", use_container_width=True, key="btn_g_riesgo"):
                    alertas_txt = "⚠️ **Reporte de Alertas y Materias en Riesgo:**\n\n"
                    materias_en_riesgo = []
                    pensum_df = st.session_state.get("pensum_df")
                    evaluaciones_dict = st.session_state.get("evaluaciones", {})

                    if pensum_df is not None and not pensum_df.empty:
                        col_est = next((c for c in pensum_df.columns if "estado" in c.lower() or "status" in c.lower()), None)
                        col_cod = next((c for c in pensum_df.columns if "codigo" in c.lower() or "código" in c.lower()), None)
                        col_mat = next((c for c in pensum_df.columns if "materia" in c.lower() or "asignatura" in c.lower()), None)

                        if col_est and col_cod and col_mat:
                            materias_en_curso = pensum_df[pensum_df[col_est].astype(str).str.lower() == "en curso"]
                            for _, row in materias_en_curso.iterrows():
                                cod = str(row[col_cod])
                                nom_materia = str(row[col_mat])
                                if cod in evaluaciones_dict:
                                    plan = evaluaciones_dict[cod].get("plan", [])
                                    notas_m = [float(e.get("Nota", 0)) for e in plan if e.get("Nota") is not None]
                                    if notas_m:
                                        prom_m = sum(notas_m) / len(notas_m)
                                        if prom_m < 12:
                                            materias_en_riesgo.append(f"- **{nom_materia}** ({cod}): Promedio actual bajo ({prom_m:.2f}).")

                    if materias_en_riesgo:
                        alertas_txt += "Se detectaron las siguientes materias con rendimiento bajo:\n" + "\n".join(materias_en_riesgo)
                    else:
                        alertas_txt += "✅ ¡Excelente noticia! No se registran materias en curso con notas en zona de riesgo actualmente."

                    st.session_state["mensajes_guiado"].append({"role": "user", "content": "Consultar materias en riesgo o con alertas pendientes"})
                    st.session_state["mensajes_guiado"].append({"role": "assistant", "content": alertas_txt})
                    st.rerun()

        elif st.session_state["modo_asistente"] == "notas_filtro_estado":
            st.markdown("### 🔍 Selecciona el estado de las materias:")
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                if st.button("📝 En Curso", use_container_width=True, key="btn_f_curso"):
                    st.session_state["sub_modo"] = "en curso"
                    st.session_state["modo_asistente"] = "seleccionar_materia_notas"
                    st.rerun()
            with col_f2:
                if st.button("✅ Aprobadas", use_container_width=True, key="btn_f_aprobada"):
                    st.session_state["sub_modo"] = "aprobada"
                    st.session_state["modo_asistente"] = "seleccionar_materia_notas"
                    st.rerun()
            with col_f3:
                if st.button("❌ Reprobadas", use_container_width=True, key="btn_f_reprobada"):
                    st.session_state["sub_modo"] = "reprobada"
                    st.session_state["modo_asistente"] = "seleccionar_materia_notas"
                    st.rerun()

            if st.button("⬅️ Volver al Menú Principal", use_container_width=True, key="btn_g_volver_1"):
                st.session_state["modo_asistente"] = "menu_principal"
                st.rerun()

        elif st.session_state["modo_asistente"] == "seleccionar_materia_notas":
            filtro_estado = st.session_state.get("sub_modo", "en curso")
            st.markdown(f"### 📚 Materias con estado: **{filtro_estado.upper()}**")

            materias_filtradas = [] 
            if "pensum_df" in st.session_state and st.session_state["pensum_df"] is not None and not st.session_state["pensum_df"].empty:
                df_p = st.session_state["pensum_df"]
                col_mat = next((c for c in df_p.columns if "materia" in c.lower() or "asignatura" in c.lower() or "nombre" in c.lower()), None)
                col_cod = next((c for c in df_p.columns if "codigo" in c.lower() or "código" in c.lower()), None)
                col_est = next((c for c in df_p.columns if "estado" in c.lower() or "status" in c.lower() or "condicion" in c.lower()), None)

                if col_mat and col_cod and col_est:
                    df_valido = df_p[
                        ~df_p[col_est].astype(str).str.lower().str.contains("no inscrita") &
                        df_p[col_est].astype(str).str.lower().str.contains(filtro_estado)
                    ]
                    for _, r in df_valido.iterrows():
                        materias_filtradas.append((str(r[col_mat]), str(r[col_cod])))

            if materias_filtradas:
                nombres_materias = [m[0] for m in materias_filtradas]
                materia_elegida = st.selectbox("Selecciona una unidad curricular:", nombres_materias, key="select_materia_g")
                codigo_elegido = next((m[1] for m in materias_filtradas if m[0] == materia_elegida), None)

                if st.button("Ver notas exactas", use_container_width=True, key="btn_g_ver_notas"):
                    detalle_notas = f"📊 **Notas exactas para: {materia_elegida}**\n\n- Condición: **{filtro_estado.capitalize()}**\n\n"
                    df_tabla_notas = None
                    if codigo_elegido and codigo_elegido in st.session_state.get("evaluaciones", {}):
                        plan_datos = st.session_state["evaluaciones"][codigo_elegido].get("plan", [])
                        if plan_datos:
                            df_tabla_notas = pd.DataFrame(plan_datos)

                    if df_tabla_notas is not None and not df_tabla_notas.empty:
                        c_nom = next((c for c in df_tabla_notas.columns if "evaluación" in c.lower() or "tema" in c.lower() or "nombre" in c.lower()), df_tabla_notas.columns[0])
                        c_nota = next((c for c in df_tabla_notas.columns if "nota" in c.lower() or "puntos" in c.lower()), None)

                        for idx, row in df_tabla_notas.iterrows():
                            nombre_ev = row.get(c_nom, f"Evaluación {idx+1}")
                            val_nota = float(row.get(c_nota, 0.0)) if c_nota and pd.notna(row.get(c_nota)) else 0.0
                            detalle_notas += f"- **{nombre_ev}**: {val_nota} pts\n"
                    else:
                        detalle_notas += "⚠️ No hay notas registradas para esta materia en el sistema todavía."

                    st.session_state["mensajes_guiado"].append({"role": "user", "content": f"Ver notas de: {materia_elegida}"})
                    st.session_state["mensajes_guiado"].append({"role": "assistant", "content": detalle_notas})
                    st.session_state["modo_asistente"] = "menu_principal"
                    st.rerun()
            else:
                st.info("No se encontraron materias bajo este criterio.")

            if st.button("⬅️ Volver", use_container_width=True, key="btn_g_volver_2"):
                st.session_state["modo_asistente"] = "notas_filtro_estado"
                st.rerun()

        elif st.session_state["modo_asistente"] == "horario_por_materia":
            st.markdown("### 🕒 Consultar horario de clases por materia")
            materias_horario = []
            if "horario_df" in st.session_state and st.session_state["horario_df"] is not None and not st.session_state["horario_df"].empty:
                df_h = st.session_state["horario_df"]
                col_m_h = next((c for c in df_h.columns if "materia" in c.lower() or "asignatura" in c.lower() or "curso" in c.lower()), None)
                if col_m_h:
                    materias_horario = df_h[col_m_h].dropna().unique().tolist()

            if materias_horario:
                mat_h_elegida = st.selectbox("Selecciona la materia:", materias_horario, key="select_mat_h_g")
                if st.button("Consultar hora de clase", use_container_width=True, key="btn_g_consultar_h"):
                    fila_h = df_h[df_h[col_m_h] == mat_h_elegida]
                    info_horario_txt = f"📅 **Horario registrado para {mat_h_elegida}:**\n\n"
                    for _, row_h in fila_h.iterrows():
                        info_horario_txt += f"- **Día:** {row_h.get('dia', 'N/A')} | **Aula:** {row_h.get('aula', 'N/A')} | **Hora:** {row_h.get('inicio', '')} - {row_h.get('fin', '')}\n"

                    st.session_state["mensajes_guiado"].append({"role": "user", "content": f"Consultar horario de: {mat_h_elegida}"})
                    st.session_state["mensajes_guiado"].append({"role": "assistant", "content": info_horario_txt})
                    st.session_state["modo_asistente"] = "menu_principal"
                    st.rerun()
            else:
                st.info("No hay datos de horario cargados.")

            if st.button("⬅️ Volver al Menú Principal", use_container_width=True, key="btn_g_volver_3"):
                st.session_state["modo_asistente"] = "menu_principal"
                st.rerun()

    else:
        col_c1, col_c2 = st.columns([4, 1])
        with col_c2:
            if st.button("🗑️ Reiniciar", key="btn_reiniciar_conversacional"):
                st.session_state["mensajes_conversacional"] = [{
                    "role": "assistant",
                    "content": mensaje_inicial_comun,
                }]
                st.rerun()

        chat_html_c = '<div class="chat-container">'
        for mensaje in st.session_state["mensajes_conversacional"]:
            if mensaje["role"] == "user":
                chat_html_c += f'<div class="msg-user"><div class="msg-title">Tú</div>{mensaje["content"]}</div>'
            else:
                chat_html_c += f'<div class="msg-assistant"><div class="msg-title">Asistente IA</div>{mensaje["content"]}</div>'
        chat_html_c += '</div>'
        st.markdown(chat_html_c, unsafe_allow_html=True)

        if prompt_usuario := st.chat_input("Escribe una consulta libre para la IA..."):
            st.session_state["mensajes_conversacional"].append({
                "role": "user",
                "content": prompt_usuario,
            })

            with st.spinner("Pensando respuesta..."):
                try:
                    api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                    client = genai.Client(api_key=api_key)

                    pensum_resumen = (
                        st.session_state["pensum_df"].to_string()
                        if st.session_state.get("pensum_df") is not None
                        else "No cargado"
                    )
                    horario_resumen = (
                        st.session_state["horario_df"].to_string()
                        if st.session_state.get("horario_df") is not None
                        else "No cargado"
                    )
                    escala_resumen = (
                        st.session_state["escala_df"].to_string()
                        if st.session_state.get("escala_df") is not None
                        else "No cargado"
                    )

                    system_instruction_text = f"""
                    Eres un asistente virtual inteligente, amigable y versátil integrado en una aplicación universitaria.
                    Responde de forma natural, cordial y útil a cualquier saludo, pregunta general o consulta del usuario.
                    Si la pregunta está relacionada con su rendimiento, materias, clases o escala evaluativa, utiliza esta información de contexto del usuario:
                    --- PENSUM Y ESTADO DE MATERIAS ---
                    {pensum_resumen}
                    --- HORARIO DE CLASES ---
                    {horario_resumen}
                    --- ESCALA EVALUATIVA ---
                    {escala_resumen}
                    """

                    modelos_a_probar = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash"]
                    response = None
                    ultimo_error = None

                    for mod in modelos_a_probar:
                        try:
                            response = client.models.generate_content(
                                model=mod,
                                contents=prompt_usuario,
                                config={
                                    'system_instruction': system_instruction_text
                                }
                            )
                            if response and response.text:
                                break
                        except Exception as ex:
                            ultimo_error = ex
                            continue

                    if response and response.text:
                        respuesta_ia = response.text
                    else:
                        raise ultimo_error if ultimo_error else Exception("No se pudo obtener respuesta de ningún modelo.")

                    st.session_state["mensajes_conversacional"].append({
                        "role": "assistant",
                        "content": respuesta_ia,
                    })
                    st.rerun()

                except Exception as e:
                    error_str = str(e)
                    
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                        error_msj = (
                            "⚠️ **Has alcanzado el límite de cuotas diarias.**\n\n"
                            "Has superado temporalmente las consultas gratuitas permitidas para hoy. "
                            "Por favor, intenta nuevamente más tarde."
                        )
                    else:
                        error_msj = "⚠️ Ocurrió un error temporal con la API de IA. Por favor, intenta de nuevo en unos segundos."

                    st.session_state["mensajes_conversacional"].append({
                        "role": "assistant",
                        "content": error_msj,
                    })
                    st.rerun()
