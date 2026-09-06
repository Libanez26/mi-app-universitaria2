import datetime
import json
import uuid
import time
import extra_streamlit_components as st_cookie
from google import genai
from google.genai import types
from pypdf import PdfReader
import pandas as pd
import streamlit as pd_st # Usaremos st para streamlit estándar
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

# --- 1. CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="App Universitaria - Gestión de Materias",
    page_icon="🎓",
    layout="wide",
)

# --- 2. INICIALIZAR GESTOR DE COOKIES ---
cookie_manager = st_cookie.CookieManager()
device_token_cookie = cookie_manager.get(cookie="dispositivo_confiable_token")

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
  st.session_state["escala_df"] = None
if "mensajes_asistente" not in st.session_state:
  st.session_state["mensajes_asistente"] = [{
      "role": "assistant",
      "content": "¡Hola! Soy tu asistente virtual académico. ¿En qué te puedo ayudar hoy con tus materias, notas o planificación?",
  }]

# --- 5. FUNCIONES DE BASE DE DATOS ---
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
      if "Fecha" in item_copia and isinstance(item_copia["Fecha"], (datetime.date, datetime.datetime)):
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

# --- 6. RECUPERAR SESIÓN POR COOKIE ---
if st.session_state["usuario"] is None:
  if device_token_cookie:
    try:
      verificacion_disp = (
          supabase.table("dispositivos_confiados")
          .select("*")
          .eq("device_token", device_token_cookie)
          .execute()
      )
      if verificacion_disp.data and len(verificacion_disp.data) > 0:
        user_id_asociado = verificacion_disp.data[0]["user_id"]
        res_usuario = (
            supabase.table("perfiles_usuario")
            .select("*")
            .eq("id", user_id_asociado)
            .execute()
        )
        if res_usuario.data:
          class UserDummy:
            def __init__(self, uid, uemail):
              self.id = uid
              self.email = uemail

          correo_asociado = res_usuario.data[0].get("correo", "usuario@app.com")
          st.session_state["usuario"] = UserDummy(user_id_asociado, correo_asociado)
          cargar_datos_usuario(user_id_asociado)
          st.rerun()
    except Exception:
      pass

# --- 7. LÓGICA DE CONTROL DE PRELACIONES ---
def verificar_disponibilidad(row, df_completo):
  prelaciones_raw = str(row.get("prelaciones", "Ninguna")).strip()
  if prelaciones_raw.lower() in ["ninguna", "ninguno", "-", "", "none", "sin prelación"]:
    return True, "Disponible"

  codigos_aprobados = df_completo[df_completo["estado"] == "Aprobada"]["codigo"].tolist()
  materias_pre = [p.strip() for p in prelaciones_raw.replace("/", ",").split(",") if p.strip()]
  faltantes = [pre for pre in materias_pre if pre not in codigos_aprobados]

  if len(faltantes) > 0:
    return False, f"🔒 Bloqueada (Requiere aprobar: {', '.join(faltantes)})"
  return True, "Disponible"

# --- 8. CÁLCULO DE ÍNDICE ACADÉMICO ---
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
          suma_val = df_plan["Valor (%)"].sum()
          if suma_val > 0:
            nota_mat = ((df_plan["Nota"] / 20.0) * (df_plan["Valor (%)"] / 100.0) * 20.0).sum()
          else:
            nota_mat = df_plan["Nota"].sum()
          
          if row["estado"] in ["Aprobada", "Reprobada", "En Curso"]:
            puntos_acumulados += nota_mat * cred
            total_creditos += cred

  if total_creditos > 0:
    return puntos_acumulados / total_creditos
  return 0.0

# --- 9. FUNCIÓN DE LLAMADA A GEMINI CON REINTENTOS (ANTI-TRÁFICO) ---
def llamada_gemini_con_reintentos(client, model_name, contents, max_intentos=3):
  intentos = 0
  espera = 2
  while intentos < max_intentos:
    try:
      response = client.models.generate_content(model=model_name, contents=contents)
      return response
    except Exception as e:
      error_str = str(e)
      if "429" in error_str or "ResourceExhausted" in error_str or "traffic" in error_str.lower():
        intentos += 1
        if intentos >= max_intentos:
          raise Exception("Servidor saturado (Alto tráfico). Por favor, intenta de nuevo en unos segundos.")
        time.sleep(espera)
        espera *= 2
      else:
        raise e

# --- 10. PANTALLA DE AUTENTICACIÓN ---
if st.session_state["usuario"] is None:
  st.title("🎓 Bienvenido a Mi App Universitaria")
  st.subheader("Inicia sesión y marca la casilla si deseas recordar este dispositivo.")

  tab_login, tab_registro = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])

  with tab_login:
    with st.form("form_login"):
      email_login = st.text_input("Correo electrónico")
      pass_login = st.text_input("Contraseña", type="password")
      recordar_dispositivo = st.checkbox("Confiar en este dispositivo", value=True)
      submit_login = st.form_submit_button("Ingresar")

      if submit_login:
        try:
          res = supabase.auth.sign_in_with_password({
              "email": email_login.strip(),
              "password": pass_login.strip(),
          })
          if res.user:
            st.session_state["usuario"] = res.user
            if recordar_dispositivo:
              nuevo_token = str(uuid.uuid4())
              cookie_manager.set("dispositivo_confiable_token", nuevo_token, max_age=31536000)
              supabase.table("dispositivos_confiados").insert({
                  "user_id": res.user.id,
                  "device_token": nuevo_token,
                  "nombre_dispositivo": "Dispositivo Confiable",
              }).execute()

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
          res = supabase.auth.sign_up({
              "email": email_reg.strip(),
              "password": pass_reg.strip(),
          })
          if res.user:
            st.success("¡Cuenta creada exitosamente! Ya puedes iniciar sesión.")
        except Exception as e:
          st.error(f"Error al registrarse: {e}")

# --- 11. APLICACIÓN PRINCIPAL ---
else:
  st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")

  with st.sidebar.expander("⚙️ Configuración de IA"):
    modelo_seleccionado = st.selectbox(
        "Selecciona el Modelo",
        ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-3.5-flash"],
        index=0,
    )

  st.sidebar.markdown("---")
  if st.sidebar.button("🔄 Refrescar Página"):
    components.html("<script>window.parent.location.reload();</script>", height=0)

  if st.sidebar.button("Cerrar Sesión en este equipo"):
    if device_token_cookie:
      try:
        supabase.table("dispositivos_confiados").delete().eq("device_token", device_token_cookie).execute()
      except Exception:
        pass
      cookie_manager.delete("dispositivo_confiable_token")

    supabase.auth.sign_out()
    st.session_state["usuario"] = None
    st.session_state["pensum_df"] = None
    st.session_state["evaluaciones"] = {}
    st.session_state["horario_df"] = None
    st.session_state["escala_df"] = None
    st.rerun()

  st.title("🎓 Mi App Universitaria")

  tab_pensum, tab_horario, tab_escala, tab_asistente, tab_pomodoro = st.tabs([
      "📚 Pensum y Calificaciones",
      "📅 Horario de Clases",
      "📊 Escala de Notas",
      "🤖 Asistente Virtual IA",
      "⏱️ Pomodoro de Estudio",
  ])

  # --- PESTAÑA 1: PENSUM Y CALIFICACIONES ---
  with tab_pensum:
    st.subheader("📋 Pensum Estructurado y Evaluaciones")
    if st.session_state["pensum_df"] is None:
      st.info("👋 Carga tu pensum en formato PDF para comenzar.")
      uploaded_file = st.file_uploader("Sube el PDF de tu pensum", type=["pdf"], key="up_pensum")
      if uploaded_file and st.button("📊 Organizar Pensum en Tabla"):
        with st.spinner("Procesando pensum con Gemini..."):
          try:
            api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
            client = genai.Client(api_key=api_key)
            pdf_bytes = uploaded_file.read()
            pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
            prompt = """Extrae exhaustivamente todas las materias del documento del pensum proporcionado. 
            Devuelve la respuesta ÚNICAMENTE como una estructura JSON válida de lista de objetos con claves: 
            semestre, codigo, materia, creditos, prelaciones."""
            response = llamada_gemini_con_reintentos(client, modelo_seleccionado, [prompt, pdf_part])
            if response and response.text:
              clean_text = response.text.strip().replace("```json", "").replace("
