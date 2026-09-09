import datetime
import io
import json
import time
import uuid
import extra_streamlit_components as stx
from google import genai
from google.genai import types
from pypdf import PdfReader
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from supabase import Client, create_client

# --- INTEGRACIÓN: COMPONENTE DE NOTIFICACIONES ---
push_js = """
<script>
async function registrarDispositivo() {
    if (!("Notification" in window)) {
        console.log("Este navegador no soporta notificaciones de escritorio.");
        return;
    }
    
    let permission = await Notification.requestPermission();
    if (permission === "granted") {
        console.log("Permiso de notificaciones concedido.");
    }
}
registrarDispositivo();
</script>
"""
components.html(push_js, height=0)

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="App Universitaria - Gestión de Materias",
    page_icon="🎓",
    layout="wide",
)

# --- 2. GESTOR DE COOKIES ---
@st.cache_resource
def get_cookie_manager():
    return stx.CookieManager()

cookie_manager = get_cookie_manager()

# --- 3. INICIALIZACIÓN DE SERVICIOS ---
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

# --- 4. ESTADO DE SESIÓN ---
if "usuario" not in st.session_state:
    st.session_state["usuario"] = None
if "pensum_df" not in st.session_state:
    st.session_state["pensum_df"] = None
if "evaluaciones" not in st.session_state:
    st.session_state["evaluaciones"] = {}
if "horario_df" not in st.session_state:
    st.session_state["horario_df"] = None
if "escala_df" not in st.session_state:
    st.session_state["escala_df"] = pd.DataFrame([
        {"Nivel de logro de la asignatura": "00% - 05%", "Calificación Cuantitativa": "01", "Calificación Cualitativa": "MUY DEFICIENTE"},
        {"Nivel de logro de la asignatura": "06% - 11%", "Calificación Cuantitativa": "02", "Calificación Cualitativa": "MUY DEFICIENTE"},
        {"Nivel de logro de la asignatura": "12% - 17%", "Calificación Cuantitativa": "03", "Calificación Cualitativa": "MUY DEFICIENTE"},
        {"Nivel de logro de la asignatura": "18% - 23%", "Calificación Cuantitativa": "04", "Calificación Cualitativa": "MUY DEFICIENTE"},
        {"Nivel de logro de la asignatura": "24% - 29%", "Calificación Cuantitativa": "05", "Calificación Cualitativa": "MUY DEFICIENTE"},
        {"Nivel de logro de la asignatura": "30% - 34%", "Calificación Cuantitativa": "06", "Calificación Cualitativa": "DEFICIENTE"},
        {"Nivel de logro de la asignatura": "35% - 39%", "Calificación Cuantitativa": "07", "Calificación Cualitativa": "DEFICIENTE"},
        {"Nivel de logro de la asignatura": "40% - 44%", "Calificación Cuantitativa": "08", "Calificación Cualitativa": "DEFICIENTE"},
        {"Nivel de logro de la asignatura": "45% - 49%", "Calificación Cuantitativa": "09", "Calificación Cualitativa": "DEFICIENTE"}
    ])
if "mensajes_asistente" not in st.session_state:
    st.session_state["mensajes_asistente"] = [{
        "role": "assistant",
        "content": "¡Hola! Soy tu asistente virtual. ¿En qué te puedo ayudar hoy?",
    }]

# --- 5. FUNCIONES AUXILIARES (BACKOFF Y DB) ---
def generar_con_reintentos(client, model, contents, config=None, max_intentos=3):
    intentos = 0
    espera = 2
    while intentos < max_intentos:
        try:
            if config:
                return client.models.generate_content(model=model, contents=contents, config=config)
            else:
                return client.models.generate_content(model=model, contents=contents)
        except Exception as e:
            intentos += 1
            if intentos >= max_intentos:
                raise e
            time.sleep(espera)
            espera *= 2

def cargar_datos_usuario(user_id):
    try:
        res = supabase.table("perfiles_usuario").select("*").eq("id", user_id).execute()
        if res.data and len(res.data) > 0:
            datos = res.data[0]
            if datos.get("pensum_data"):
                st.session_state["pensum_df"] = pd.DataFrame(datos["pensum_data"])
            
            if datos.get("evaluaciones_data"):
                evals_cargadas = datos["evaluaciones_data"]
                for cod, info in evals_cargadas.items():
                    if "plan" in info:
                        for item in info["plan"]:
                            if "Fecha" in item and isinstance(item["Fecha"], str):
                                try:
                                    item["Fecha"] = datetime.datetime.strptime(item["Fecha"], "%Y-%m-%d").date()
                                except ValueError:
                                    item["Fecha"] = datetime.date.today()
                st.session_state["evaluaciones"] = evals_cargadas

            if datos.get("horario_data"):
                st.session_state["horario_df"] = pd.DataFrame(datos["horario_data"])

            if datos.get("escala_data"):
                st.session_state["escala_df"] = pd.DataFrame(datos["escala_data"])
    except Exception as e:
        st.error(f"Error cargando datos de la base de datos: {e}")

def guardar_datos_usuario():
    if not st.session_state["usuario"]:
        return

    user_id = st.session_state["usuario"].id
    correo = st.session_state["usuario"].email

    pensum_json = (
        st.session_state["pensum_df"].to_dict("records")
        if st.session_state["pensum_df"] is not None
        else None
    )
    
    evals_json = {}
    for cod, info in st.session_state["evaluaciones"].items():
        evals_json[cod] = {
            "estado": info.get("estado", "No Inscrita"),
            "plan": []
        }
        for item in info.get("plan", []):
            item_copia = item.copy()
            if "Fecha" in item_copia:
                if isinstance(item_copia["Fecha"], (datetime.date, datetime.datetime)):
                    item_copia["Fecha"] = item_copia["Fecha"].strftime("%Y-%m-%d")
            evals_json[cod]["plan"].append(item_copia)

    horario_json = (
        st.session_state["horario_df"].to_dict("records")
        if st.session_state["horario_df"] is not None
        else None
    )

    escala_json = (
        st.session_state["escala_df"].to_dict("records")
        if st.session_state["escala_df"] is not None
        else None
    )

    data = {
        "id": user_id,
        "correo": correo,
        "pensum_data": pensum_json,
        "evaluaciones_data": evals_json,
        "horario_data": horario_json,
        "escala_data": escala_json,
    }

    try:
        supabase.table("perfiles_usuario").upsert(data).execute()
        st.toast("💾 Cambios guardados automáticamente", icon="☁️")
    except Exception as e:
        st.error(f"Error al guardar datos: {e}")

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

def calcular_nota_materia(cod, evaluaciones):
    if cod in evaluaciones:
        plan = evaluaciones[cod].get("plan", [])
        if plan:
            df_plan = pd.DataFrame(plan)
            if "Nota" in df_plan.columns:
                notas_validas = df_plan["Nota"].dropna()
                if len(notas_validas) > 0:
                    escala_key = f"radio_esc_{cod}"
                    escala_sel = st.session_state.get(escala_key, "Acumulativa")
                    
                    if "Acumulativa" in escala_sel:
                        return float(notas_validas.sum())
                    else:
                        return float(notas_validas.mean())
    return 0.0

def calcular_promedios_semestres(df_pensum, evaluaciones):
    promedios_por_semestre = {}
    semestres = df_pensum["semestre"].unique()
    
    for sem in semestres:
        df_sem = df_pensum[df_pensum["semestre"] == sem]
        notas_sem = []
        for _, row in df_sem.iterrows():
            cod = row["codigo"]
            estado = row["estado"]
            if estado in ["Aprobada", "Reprobada", "En Curso"]:
                nota = calcular_nota_materia(cod, evaluaciones)
                notas_sem.append(nota)
        
        if len(notas_sem) > 0:
            promedios_por_semestre[sem] = sum(notas_sem) / len(notas_sem)
        else:
            promedios_por_semestre[sem] = 0.0
            
    return promedios_por_semestre

def calcular_indice_academico(df_pensum, evaluaciones):
    promedios_sem = calcular_promedios_semestres(df_pensum, evaluaciones)
    valores_prom = [p for p in promedios_sem.values() if p > 0.0]
    if len(valores_prom) > 0:
        return sum(valores_prom) / len(valores_prom)
    return 0.0

# --- AUTO-LOGIN ---
if st.session_state["usuario"] is None:
    token_guardado = cookie_manager.get(cookie="sb_refresh_token")
    if token_guardado and isinstance(token_guardado, str) and len(token_guardado.strip()) > 0:
        try:
            res_session = supabase.auth.set_session(token_guardado, token_guardado)
            if res_session and res_session.user:
                st.session_state["usuario"] = res_session.user
                if res_session.session and res_session.session.refresh_token:
                    cookie_manager.set(
                        "sb_refresh_token",
                        res_session.session.refresh_token,
                        expires_at=datetime.datetime.now() + datetime.timedelta(days=30)
                    )
                cargar_datos_usuario(res_session.user.id)
                st.rerun()
        except Exception:
            cookie_manager.delete("sb_refresh_token")

# --- 6. AUTENTICACIÓN / PANTALLA PRINCIPAL ---
if st.session_state["usuario"] is None:
    st.title("🎓 Bienvenido a Mi App Universitaria")
    st.subheader("Inicia sesión en tu cuenta.")

    tab_login, tab_registro = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])

    with tab_login:
        with st.form("form_login"):
            email_login = st.text_input("Correo electrónico")
            pass_login = st.text_input("Contraseña", type="password")
            recordar_dispositivo = st.checkbox("Recordar esta sesión en este dispositivo", value=True)
            submit_login = st.form_submit_button("Ingresar")

            if submit_login:
                try:
                    res = supabase.auth.sign_in_with_password({
                        "email": email_login.strip(),
                        "password": pass_login.strip(),
                    })
                    if res.user:
                        st.session_state["usuario"] = res.user
                        if recordar_dispositivo and res.session and res.session.refresh_token:
                            cookie_manager.set(
                                "sb_refresh_token",
                                res.session.refresh_token,
                                expires_at=datetime.datetime.now() + datetime.timedelta(days=30)
                            )
                        cargar_datos_usuario(res.user.id)
                        st.success("¡Sesión iniciada con éxito!")
                        time.sleep(0.5)
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
                    res = supabase.auth.sign_up({
                        "email": email_reg.strip(),
                        "password": pass_reg.strip(),
                    })
                    if res.user:
                        st.success("¡Cuenta creada exitosamente! Ahora puedes iniciar sesión.")
                except Exception as e:
                    st.error(f"Error al registrarse: {e}")

else:
    # --- PANEL DE USUARIO LOGUEADO ---
    st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")

    with st.sidebar.expander("⚙️ Configuración de IA"):
        modelo_seleccionado = st.selectbox(
            "Selecciona el Modelo",
            ["gemini-3.6-flash", "gemini-3.5-flash"],
            index=0,
            help="Si un modelo presenta alta demanda (503), la aplicación intentará con otra versión disponible."
        )

    st.sidebar.markdown("---")

    if st.session_state.get("pensum_df") is not None:
        df_p = st.session_state["pensum_df"].copy()
        evals = st.session_state.get("evaluaciones", {})
        
        if "estado" in df_p.columns:
            df_filtrado = df_p[df_p["estado"].astype(str).str.lower() != "no inscrita"].copy()
        else:
            df_filtrado = df_p.copy()

        if not df_filtrado.empty:
            notas_finales = []
            for _, row_mat in df_filtrado.iterrows():
                n_val = calcular_nota_materia(row_mat["codigo"], evals)
                notas_finales.append(round(n_val, 2))
            df_filtrado["Nota Final"] = notas_finales

            promedios_sem = calcular_promedios_semestres(df_p, evals)
            indice_gen = calcular_indice_academico(df_p, evals)

            html_contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Resumen Académico</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; color: #333; }}
        h1 {{ color: #004085; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
    </style>
</head>
<body>
    <h1>Reporte de Rendimiento Académico</h1>
    <p><strong>Índice Académico General:</strong> {indice_gen:.2f} / 20.0</p>
    <h2>Detalle de Materias</h2>
    <table>
        <tr><th>Semestre</th><th>Código</th><th>Materia</th><th>Estado</th><th>Nota Final</th></tr>"""

            for _, row in df_filtrado.iterrows():
                html_contenido += f"<tr><td>{row.get('semestre', '')}</td><td>{row.get('codigo', '')}</td><td>{row.get('materia', '')}</td><td>{row.get('estado', '')}</td><td>{row.get('Nota Final', 0.0):.2f}</td></tr>"

            html_contenido += "</table></body></html>"

            pdf_bytes = html_contenido.encode('utf-8')

            st.sidebar.download_button(
                label="📥 Descargar Reporte (HTML)",
                data=pdf_bytes,
                file_name="resumen_academico.html",
                mime="text/html"
            )

    if st.sidebar.button("🔄 Refrescar Página", key="btn_refrescar_pagina"):
        st.rerun()

    if st.sidebar.button("Cerrar Sesión", key="btn_logout"):
        try:
            cookie_manager.delete("sb_refresh_token")
        except Exception:
            pass
        supabase.auth.sign_out()
        st.session_state["usuario"] = None
        st.session_state["pensum_df"] = None
        st.session_state["evaluaciones"] = {}
        st.session_state["horario_df"] = None
        st.rerun()

    st.title("🎓 Mi App Universitaria")

    tab_pensum, tab_horario, tab_asistente, tab_pomodoro = st.tabs([
        "📊 Pensum y Calificaciones",
        "📅 Horario de Clases",
        "🤖 Asistente Virtual IA",
        "⏱️ Pomodoro de Estudio Integrado"
    ])

    # ==========================================
    # PESTAÑA 1: PENSUM Y CALIFICACIONES
    # ==========================================
    with tab_pensum:
        with st.expander("🔔 Ver Alertas de Actividades (Vencidas, Hoy y Próximas)", expanded=False):
            hoy = datetime.date.today()
            limite_futuro = hoy + datetime.timedelta(days=3)
            
            atrasadas, para_hoy, proximas = [], [], []

            if "evaluaciones" in st.session_state:
                for cod_mat, info_mat in st.session_state["evaluaciones"].items():
                    plan = info_mat.get("plan", [])
                    for ev in plan:
                        entregada = ev.get("Entregada", False)
                        fecha_ev = ev.get("Fecha")

                        if isinstance(fecha_ev, str):
                            try:
                                fecha_ev = datetime.datetime.strptime(fecha_ev, "%Y-%m-%d").date()
                            except ValueError:
                                continue
                        elif isinstance(fecha_ev, datetime.datetime):
                            fecha_ev = fecha_ev.date()

                        if not entregada and fecha_ev:
                            item = {
                                "Código": cod_mat,
                                "Evaluación": ev.get("Evaluación"),
                                "Tema": ev.get("Tema"),
                                "Fecha": fecha_ev,
                                "Valor (%)": ev.get("Valor (%)")
                            }
                            
                            if fecha_ev < hoy:
                                atrasadas.append(item)
                            elif fecha_ev == hoy:
                                para_hoy.append(item)
                            elif hoy < fecha_ev <= limite_futuro:
                                proximas.append(item)

            if atrasadas or para_hoy or proximas:
                if atrasadas:
                    st.error(f"🚨 Tienes **{len(atrasadas)}** actividad(es) **atrasada(s)**")
                    st.dataframe(pd.DataFrame(atrasadas), use_container_width=True)
                if para_hoy:
                    st.warning(f"🔥 Tienes **{len(para_hoy)}** actividad(es) para **HOY**")
                    st.dataframe(pd.DataFrame(para_hoy), use_container_width=True)
                if proximas:
                    st.info(f"⏳ Tienes **{len(proximas)}** actividad(es) próximas (3 días)")
                    st.dataframe(pd.DataFrame(proximas), use_container_width=True)
            else:
                st.success("🎉 ¡Excelente! No tienes actividades pendientes.")

        st.subheader("📋 Pensum Estructurado por Niveles")

        if st.session_state["pensum_df"] is None:
            uploaded_file = st.file_uploader("Sube el PDF de tu pensum universitario", type=["pdf"])
            if uploaded_file and st.button("📊 Organizar Pensum en Tabla"):
                with st.spinner("Procesando pensum..."):
                    try:
                        api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                        client = genai.Client(api_key=api_key)
                        pdf_bytes = uploaded_file.read()
                        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

                        prompt = """Extrae exhaustivamente todas las materias del documento del pensum proporcionado.
Devuelve ÚNICAMENTE un JSON válido con la siguiente estructura:
[{"semestre": "Semestre I", "codigo": "MAT-101", "materia": "Matemática I", "creditos": 4, "prelaciones": "Ninguna"}]"""

                        response = generar_con_reintentos(client, modelo_seleccionado, [prompt, pdf_part])
                        if response and response.text:
                            clean_text = response.text.strip().replace("```json", "").replace("```", "")
                            data = json.loads(clean_text)
                            df = pd.DataFrame(data)
                            if "estado" not in df.columns:
                                df["estado"] = "No Inscrita"
                            st.session_state["pensum_df"] = df
                            guardar_datos_usuario()
                            st.success("¡Pensum procesado!")
                            st.rerun()
                    except Exception as err:
                        st.error(f"Error al procesar el documento: {err}")
        else:
            if st.sidebar.button("🗑️ Eliminar Pensum", key="btn_eliminar_pensum"):
                st.session_state["pensum_df"] = None
                st.session_state["evaluaciones"] = {}
                guardar_datos_usuario()
                st.rerun()

            df = st.session_state["pensum_df"]
            indice_aca = calcular_indice_academico(df, st.session_state["evaluaciones"])

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Total Materias", len(df))
            col_m2.metric("Aprobadas", len(df[df["estado"] == "Aprobada"]))
            col_m3.metric("Reprobadas", len(df[df["estado"] == "Reprobada"]))
            col_m4.metric("📈 Índice Académico", f"{indice_aca:.2f} / 20.0")

            st.divider()

            semestres = list(df["semestre"].unique()) if "semestre" in df.columns else ["Nivel Único"]
            promedios_semestrales = calcular_promedios_semestres(df, st.session_state["evaluaciones"])
            tabs_niveles = st.tabs(semestres)

            for idx_tab, semestre_nombre in enumerate(semestres):
                with tabs_niveles[idx_tab]:
                    df_nivel = df[df["semestre"] == semestre_nombre].copy()
                    notas_finales_nivel = [f"{calcular_nota_materia(row['codigo'], st.session_state['evaluaciones']):.2f} pts" for _, row in df_nivel.iterrows()]
                    df_nivel["Nota Final"] = notas_finales_nivel

                    st.info(f"📊 Promedio ({semestre_nombre}): {promedios_semestrales.get(semestre_nombre, 0.0):.2f} / 20.0")

                    evento_seleccion = st.dataframe(
                        df_nivel,
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="single-row",
                        key=f"tabla_{semestre_nombre}"
                    )

                    filas_sel = evento_seleccion.get("selection", {}).get("rows", [])
                    if filas_sel:
                        materia_sel = df_nivel.iloc[filas_sel[0]]
                        codigo_mat = str(materia_sel.get("codigo"))
                        nombre_mat = materia_sel.get("materia")

                        st.markdown(f"### 📝 Plan de Evaluaciones: **{codigo_mat} - {nombre_mat}**")

                        if codigo_mat not in st.session_state["evaluaciones"]:
                            hoy = datetime.date.today()
                            st.session_state["evaluaciones"][codigo_mat] = {
                                "estado": materia_sel.get("estado", "No Inscrita"),
                                "plan": [
                                    {"Evaluación": "Parcial 1", "Tema": "Unidad 1", "Valor (%)": 25, "Nota": 0.0, "Fecha": hoy, "Entregada": False},
                                    {"Evaluación": "Parcial 2", "Tema": "Unidad 2", "Valor (%)": 25, "Nota": 0.0, "Fecha": hoy, "Entregada": False}
                                ]
                            }

                        df_eval_actual = pd.DataFrame(st.session_state["evaluaciones"][codigo_mat]["plan"])
                        edited_df = st.data_editor(
                            df_eval_actual,
                            num_rows="dynamic",
                            use_container_width=True,
                            key=f"editor_{codigo_mat}"
                        )

                        if st.button("💾 Guardar Notas", key=f"btn_guardar_{codigo_mat}"):
                            st.session_state["evaluaciones"][codigo_mat]["plan"] = edited_df.to_dict("records")
                            guardar_datos_usuario()
                            st.success("Notas guardadas")
                            st.rerun()

    # ==========================================
    # PESTAÑA 2: HORARIO DE CLASES
    # ==========================================
    with tab_horario:
        st.subheader("📅 Gestión de Horario de Clases")
        if st.session_state.get("horario_df") is None:
            uploaded_horario = st.file_uploader("Sube el PDF de tu horario", type=["pdf"])
            if uploaded_horario and st.button("Procesar Horario"):
                # Lógica del procesador de horario
                pass
        else:
            df_horario_actual = st.session_state["horario_df"]
            df_editado = st.data_editor(df_horario_actual, use_container_width=True, key="editor_horario")
            st.session_state["horario_df"] = df_editado

    # ==========================================
    # PESTAÑA 3: ASISTENTE VIRTUAL
    # ==========================================
    with tab_asistente:
        st.subheader("🤖 Asistente Virtual Universitario")
        prompt_usuario = st.chat_input("Escribe una consulta...")
        if prompt_usuario:
            st.chat_message("user").write(prompt_usuario)
            # Procesamiento con Gemini
            st.chat_message("assistant").write("Procesando tu solicitud...")

    # ==========================================
    # PESTAÑA 4: POMODORO
    # ==========================================
    with tab_pomodoro:
        st.subheader("⏱️ Pomodoro de Estudio")
        if "pomodoro_tiempo" not in st.session_state:
            st.session_state["pomodoro_tiempo"] = 25 * 60
        
        minutos = st.session_state["pomodoro_tiempo"] // 60
        segundos = st.session_state["pomodoro_tiempo"] % 60
        st.metric("Tiempo restante", f"{minutos:02d}:{segundos:02d}")
