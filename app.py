import json
import pandas as pd
import streamlit as st
from pypdf import PdfReader
from google import genai
from google.genai import types
from supabase import create_client, Client

# MUST BE THE FIRST STREAMLIT COMMAND
st.set_page_config(
    page_title="App Universitaria - Gestión de Materias",
    page_icon="🎓",
    layout="wide"
)

# --- INICIALIZACIÓN DE SERVICIOS ---
@st.cache_resource
def init_supabase() -> Client:
    raw_url = str(st.secrets["SUPABASE_URL"]).strip()
    if "/rest/v1" in raw_url:
        raw_url = raw_url.split("/rest/v1")[0]
    raw_url = raw_url.rstrip("/")
    
    key = str(st.secrets["SUPABASE_KEY"]).strip()
    return create_client(raw_url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error(f"Error al conectar con Supabase: {e}")

# --- ESTADO DE SESIÓN ---
if "usuario" not in st.session_state:
    st.session_state["usuario"] = None
if "pensum_df" not in st.session_state:
    st.session_state["pensum_df"] = None
if "evaluaciones" not in st.session_state:
    st.session_state["evaluaciones"] = {}
if "mensajes_chat" not in st.session_state:
    st.session_state["mensajes_chat"] = []

# --- FUNCIONES DE BASE DE DATOS ---
def cargar_datos_usuario(user_id):
    try:
        res = supabase.table("perfiles_usuario").select("*").eq("id", user_id).execute()
        if res.data:
            datos = res.data[0]
            if datos.get("pensum_data"):
                st.session_state["pensum_df"] = pd.DataFrame(datos["pensum_data"])
            if datos.get("evaluaciones_data"):
                st.session_state["evaluaciones"] = datos["evaluaciones_data"]
    except Exception as e:
        st.error(f"Error cargando datos de la base de datos: {e}")

def guardar_datos_usuario():
    if not st.session_state["usuario"]:
        return
    
    user_id = st.session_state["usuario"].id
    correo = st.session_state["usuario"].email
    
    pensum_json = st.session_state["pensum_df"].to_dict("records") if st.session_state["pensum_df"] is not None else None
    evals_json = st.session_state["evaluaciones"]
    
    data = {
        "id": user_id,
        "correo": correo,
        "pensum_data": pensum_json,
        "evaluaciones_data": evals_json
    }
    
    try:
        supabase.table("perfiles_usuario").upsert(data).execute()
        st.toast("💾 Cambios guardados automáticamente", icon="☁️")
    except Exception as e:
        st.error(f"Error al guardar datos: {e}")

# --- LÓGICA DE CONTROL DE PRELACIONES ---
def verificar_disponibilidad(row, df_completo):
    prelaciones_raw = str(row.get("prelaciones", "Ninguna")).strip()
    
    if prelaciones_raw.lower() in ["ninguna", "ninguno", "-", "", "none", "sin prelación"]:
        return True, "Disponible"
    
    codigos_aprobados = df_completo[df_completo["estado"] == "Aprobada"]["codigo"].tolist()
    materias_pre = [p.strip() for p in prelaciones_raw.replace("/", ",").split(",") if p.strip()]
    faltantes = []
    
    for pre in materias_pre:
        if pre not in codigos_aprobados and pre.lower() not in ["ninguna", ""]:
            faltantes.append(pre)
            
    if len(faltantes) > 0:
        return False, f"🔒 Bloqueada (Requiere aprobar: {', '.join(faltantes)})"
    
    return True, "Disponible"

# --- CÁLCULO DE PROMEDIO GLOBAL / ÍNDICE ACADÉMICO ---
def calcular_indice_academico(df_pensum, evaluaciones):
    total_creditos = 0
    puntos_acumulados = 0.0
    
    for _, row in df_pensum.iterrows():
        cod = row["codigo"]
        cred = row.get("creditos", 0)
        
        if cod in evaluaciones:
            plan = evaluaciones[cod].get("plan", [])
            if plan:
                df_plan = pd.DataFrame(plan)
                if "Nota" in df_plan.columns and "Valor (%)" in df_plan.columns:
                    nota_mat = ((df_plan["Nota"] / 20.0) * (df_plan["Valor (%)"] / 100.0) * 20.0).sum()
                    if row["estado"] in ["Aprobada", "Reprobada", "En Curso"]:
                        puntos_acumulados += nota_mat * cred
                        total_creditos += cred

    if total_creditos > 0:
        return puntos_acumulados / total_creditos
    return 0.0

# --- PANTALLA DE AUTENTICACIÓN ---
if st.session_state["usuario"] is None:
    st.title("🎓 Bienvenido a Mi App Universitaria")
    st.subheader("Inicia sesión o regístrate para gestionar tu pensum e historial académico")

    tab_login, tab_registro = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])

    with tab_login:
        with st.form("form_login"):
            email_login = st.text_input("Correo electrónico")
            pass_login = st.text_input("Contraseña", type="password")
            submit_login = st.form_submit_button("Ingresar")

            if submit_login:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email_login.strip(), "password": pass_login.strip()})
                    st.session_state["usuario"] = res.user
                    cargar_datos_usuario(res.user.id)
                    st.success("¡Sesión iniciada con éxito!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al iniciar sesión: {e}")

    with tab_registro:
        with st.form("form_registro"):
            email_reg = st.text_input("Correo electrónico para el registro")
            pass_reg = st.text_input("Contraseña", type="password")
            submit_reg = st.form_submit_button("Crear Cuenta")

            if submit_reg:
                try:
                    res = supabase.auth.sign_up({"email": email_reg.strip(), "password": pass_reg.strip()})
                    if res.user:
                        st.success("¡Cuenta creada exitosamente! Ahora puedes iniciar sesión.")
                except Exception as e:
                    st.error(f"Error al registrarse: {e}")

# --- APLICACIÓN PRINCIPAL (USUARIO LOGUEADO) ---
else:
    # BARRA LATERAL CON SELECTOR DESPLEGABLE OCULTO EN UN EXPANDER
    st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")
    
    with st.sidebar.expander("⚙️ Configuración de IA"):
        modelo_seleccionado = st.selectbox(
            "Selecciona el Modelo",
            [
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-1.5-flash",
                "gemini-3.5-flash"
            ],
            index=0,
            help="Elige un modelo alternativo si alcanzas el límite de solicitudes por minuto (RPM)."
        )

    st.sidebar.markdown("---")
    if st.sidebar.button("Cerrar Sesión", key="btn_logout"):
        supabase.auth.sign_out()
        st.session_state["usuario"] = None
        st.session_state["pensum_df"] = None
        st.session_state["evaluaciones"] = {}
        st.session_state["mensajes_chat"] = []
        st.rerun()

    st.title("🎓 Mi App Universitaria")

    # CREACIÓN DE PESTAÑAS PRINCIPALES
    tab_pensum, tab_horario, tab_chat = st.tabs([
        "📚 Pensum y Calificaciones", 
        "📅 Horario de Clases", 
        "🤖 Chat con Gemini"
    ])

    # ==========================================
    # PESTAÑA 1: PENSUM Y CALIFICACIONES
    # ==========================================
    with tab_pensum:
        st.subheader("📋 Pensum Estructurado por Niveles")

        if st.session_state["pensum_df"] is None:
            st.info("👋 Carga tu pensum en formato PDF para organizar tus niveles académicos.")
            uploaded_file = st.file_uploader("Sube el PDF de tu pensum universitario", type=["pdf"])

            if uploaded_file and st.button("📊 Organizar Pensum en Tabla"):
                with st.spinner("Procesando pensum con Gemini..."):
                    try:
                        api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                        client = genai.Client(api_key=api_key)

                        pdf_bytes = uploaded_file.read()
                        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

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
                            model=modelo_seleccionado,
                            contents=[prompt, pdf_part]
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
                                df["estado"] = "Inscrita"

                            st.session_state["pensum_df"] = df
                            guardar_datos_usuario()
                            st.success("¡Pensum procesado y guardado!")
                            st.rerun()

                    except Exception as err:
                        st.error(f"Error procesando el documento: {err}")

        else:
            if st.sidebar.button("🗑️ Eliminar / Volver a subir Pensum"):
                st.session_state["pensum_df"] = None
                st.session_state["evaluaciones"] = {}
                guardar_datos_usuario()
                st.rerun()

            df = st.session_state["pensum_df"]

            indice_aca = calcular_indice_academico(df, st.session_state["evaluaciones"])

            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
            with col_m1:
                st.metric("Total Materias", len(df))
            with col_m2:
                st.metric("Aprobadas", len(df[df["estado"] == "Aprobada"]))
            with col_m3:
                st.metric("En Curso", len(df[df["estado"] == "En Curso"]))
            with col_m4:
                st.metric("Inscritas / Pendientes", len(df[df["estado"] == "Inscrita"]))
            with col_m5:
                st.metric("📈 Índice Académico", f"{indice_aca:.2f} / 20.0")

            st.divider()

            semestres = list(df["semestre"].unique()) if "semestre" in df.columns else ["Nivel Único"]
            tabs_niveles = st.tabs(semestres)

            for idx_tab, semestre_nombre in enumerate(semestres):
                with tabs_niveles[idx_tab]:
                    df_nivel = df[df["semestre"] == semestre_nombre].copy()

                    disponibilidades = []
                    mensajes_est = []
                    for _, row in df_nivel.iterrows():
                        disp, msg = verificar_disponibilidad(row, df)
                        disponibilidades.append(disp)
                        mensajes_est.append(msg)

                    df_nivel["Disponibilidad"] = mensajes_est

                    bloqueadas_count = disponibilidades.count(False)
                    if bloqueadas_count > 0:
                        st.warning(f"⚠️ Tienes {bloqueadas_count} materia(s) bloqueada(s) por preliminares no aprobadas.")

                    evento_seleccion = st.dataframe(
                        df_nivel,
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"tabla_{semestre_nombre}",
                        column_config={
                            "semestre": "Nivel",
                            "codigo": "Código",
                            "materia": "Asignatura",
                            "creditos": st.column_config.NumberColumn("Créditos", format="%d"),
                            "prelaciones": "Requisitos / Prelaciones",
                            "estado": "Estado Actual",
                            "Disponibilidad": st.column_config.TextColumn("Estatus de Acceso")
                        }
                    )

                    filas_sel = evento_seleccion.get("selection", {}).get("rows", [])

                    if filas_sel:
                        idx_local = filas_sel[0]
                        materia_sel = df_nivel.iloc[idx_local]
                        codigo_mat = str(materia_sel.get("codigo", f"MAT-{idx_local}"))
                        nombre_mat = materia_sel.get("materia", "Asignatura")
                        esta_disponible = disponibilidades[idx_local]

                        st.divider()

                        if not esta_disponible:
                            st.error(f"🔒 **{codigo_mat} - {nombre_mat}** está **bloqueada**. Aprueba sus preliminares ({materia_sel.get('prelaciones')}) para registrar sus notas.")
                        else:
                            st.markdown(f"### 📝 Plan de Evaluaciones: **{codigo_mat} - {nombre_mat}**")

                            if codigo_mat not in st.session_state["evaluaciones"]:
                                st.session_state["evaluaciones"][codigo_mat] = {
                                    "estado": materia_sel.get("estado", "Inscrita"),
                                    "plan": [
                                        {"Evaluación": "Parcial 1", "Tema": "Unidad 1", "Valor (%)": 25, "Nota": 0.0},
                                        {"Evaluación": "Parcial 2", "Tema": "Unidad 2", "Valor (%)": 25, "Nota": 0.0},
                                        {"Evaluación": "Trabajo / Proyecto", "Tema": "Unidad 3", "Valor (%)": 25, "Nota": 0.0},
                                        {"Evaluación": "Exposición / Quices", "Tema": "Unidad 4", "Valor (%)": 25, "Nota": 0.0}
                                    ]
                                }

                            col_e1, col_e2 = st.columns(2)
                            with col_e1:
                                estado_actual = st.session_state["evaluaciones"][codigo_mat].get("estado", "Inscrita")
                                idx_e = ["Inscrita", "En Curso", "Aprobada", "Reprobada"].index(estado_actual) if estado_actual in ["Inscrita", "En Curso", "Aprobada", "Reprobada"] else 0
                                
                                nuevo_est = st.selectbox(
                                    "Estado de la Materia:",
                                    ["Inscrita", "En Curso", "Aprobada", "Reprobada"],
                                    index=idx_e,
                                    key=f"sel_est_{codigo_mat}"
                                )

                                if nuevo_est != estado_actual:
                                    st.session_state["evaluaciones"][codigo_mat]["estado"] = nuevo_est
                                    st.session_state["pensum_df"].loc[
                                        st.session_state["pensum_df"]["codigo"] == codigo_mat, "estado"
                                    ] = nuevo_est
                                    guardar_datos_usuario()
                                    st.rerun()

                            with col_e2:
                                escala_sel = st.radio(
                                    "Escala para ingresar notas:",
                                    ["0 - 20 pts", "0 - 100%"],
                                    horizontal=True,
                                    key=f"radio_esc_{codigo_mat}"
                                )

                            df_eval_actual = pd.DataFrame(st.session_state["evaluaciones"][codigo_mat]["plan"])
                            
                            if "Tema" not in df_eval_actual.columns:
                                df_eval_actual["Tema"] = ""

                            max_nota = 20.0 if "20" in escala_sel else 100.0

                            edited_df = st.data_editor(
                                df_eval_actual[["Evaluación", "Tema", "Valor (%)", "Nota"]],
                                num_rows="dynamic",
                                use_container_width=True,
                                key=f"editor_{codigo_mat}",
                                column_config={
                                    "Evaluación": st.column_config.TextColumn("Evaluación"),
                                    "Tema": st.column_config.TextColumn("Tema"),
                                    "Valor (%)": st.column_config.NumberColumn("Valor (%)", min_value=0, max_value=100, step=1),
                                    "Nota": st.column_config.NumberColumn(
                                        f"Nota ({'0-20 pts' if '20' in escala_sel else '0-100%'})",
                                        min_value=0.0,
                                        max_value=max_nota,
                                        step=0.5
                                    )
                                }
                            )

                            if not edited_df.equals(df_eval_actual[["Evaluación", "Tema", "Valor (%)", "Nota"]]):
                                st.session_state["evaluaciones"][codigo_mat]["plan"] = edited_df.to_dict("records")

                            # --- MÉTRICAS ACUMULATIVAS ---
                            st.markdown("---")
                            st.markdown("#### 📊 Resumen de Rendimiento")

                            peso_planificado = edited_df["Valor (%)"].sum() if "Valor (%)" in edited_df.columns else 0.0

                            if "20" in escala_sel:
                                max_nota = 20.0
                                min_aprobar = 9.5
                                unidad = "puntos"
                            else:
                                max_nota = 100.0
                                min_aprobar = 47.5
                                unidad = "%"

                            puntos_acum = 0.0
                            if "Nota" in edited_df.columns and "Valor (%)" in edited_df.columns:
                                puntos_acum = ((edited_df["Nota"] / max_nota) * (edited_df["Valor (%)"] / 100.0) * max_nota).sum()
                            
                            porcentaje_efectivo = (puntos_acum / max_nota) * 100.0 if max_nota > 0 else 0.0
                            falta_peso = 100.0 - peso_planificado
                            puntos_faltantes = min_aprobar - puntos_acum

                            col_ac1, col_ac2, col_ac3 = st.columns(3)

                            col_ac1.metric(
                                label="Porcentaje Obtenido / Evaluado",
                                value=f"{porcentaje_efectivo:.1f}% / {peso_planificado:.1f}%"
                            )

                            col_ac2.metric(
                                label="Nota Acumulada",
                                value=f"{puntos_acum:.2f} / {max_nota:.1f} {unidad}"
                            )

                            if puntos_faltantes <= 0:
                                col_ac3.metric(label="Estado de Aprobación", value="✅ Aprobado")
                            elif falta_peso > 0:
                                nota_req = (puntos_faltantes / (falta_peso / 100.0))

# ==========================================
    # PESTAÑA 2: HORARIO DE CLASES
    # ==========================================
    with tab_horario:
        st.subheader("📅 Gestión de Horario")
        
        # Selección de tiempo de alerta
        tiempo_alerta = st.select_slider(
            "Minutos de anticipación para la alerta:",
            options=[5, 10, 15],
            value=5
        )

        uploaded_horario = st.file_uploader("Sube tu horario (PDF)", type=["pdf"])

        if uploaded_horario:
            if st.button("Procesar y Organizar Horario"):
                # 1. Llamada a Gemini para extraer estructura JSON
                # El prompt debe pedir: {"dia": "Lunes", "inicio": "08:00", "fin": "10:00", "materia": "..."}
                
                # 2. Lógica de agrupación de horas consecutivas
                # df = pd.DataFrame(datos_gemini)
                # Ejemplo rápido de agrupación:
                # Si (materia_n == materia_n+1) y (fin_n == inicio_n+1): fusionar.
                
                st.success("Horario organizado con éxito")
                st.session_state["horario_df"] = df_agrupado

        if "horario_df" in st.session_state and st.session_state["horario_df"] is not None:
            st.table(st.session_state["horario_df"])
            
            # 3. Lógica de Alertas
            # Necesitas comparar datetime.now() con las horas del df
            import datetime
            ahora = datetime.datetime.now().strftime("%H:%M")
            # Comparar si (hora_clase - tiempo_alerta) == ahora
          def agrupar_horario(df):
    df = df.sort_values(by=["dia", "inicio"])
    resultado = []
    
    for i, row in df.iterrows():
        if not resultado:
            resultado.append(row.to_dict())
        else:
            prev = resultado[-1]
            if row["materia"] == prev["materia"] and row["inicio"] == prev["fin"]:
                prev["fin"] = row["fin"]
            else:
                resultado.append(row.to_dict())
    return pd.DataFrame(resultado)
    
    # Dentro del bucle de verificación de horario
if es_hora_de_alerta:
    st.toast(f"🚨 La clase {materia} comienza en {tiempo_alerta} minutos")
    
    # Alerta hablada básica usando el motor de texto a voz del navegador/sistema
    js_code = f"""
    <script>
        var msg = new SpeechSynthesisUtterance('Atención, la clase {materia} comienza en {tiempo_alerta} minutos');
        window.speechSynthesis.speak(msg);
    </script>
    """
    st.components.v1.html(js_code, height=0)
