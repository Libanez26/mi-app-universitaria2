import datetime
import json
import uuid
import extra_streamlit_components as st_cookie
from google import genai
from google.genai import types
from pypdf import PdfReader
import pandas as pd
import streamlit as st
from supabase import Client, create_client

# --- 1. MUST BE THE FIRST STREAMLIT COMMAND ---
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
if "mensajes_chat" not in st.session_state:
  st.session_state["mensajes_chat"] = []


# --- 5. FUNCIONES DE BASE DE DATOS (CON SERIALIZACIÓN DE FECHAS) ---
def cargar_datos_usuario(user_id):
  try:
    res = (
        supabase.table("perfiles_usuario").select("*").eq("id", user_id).execute()
    )
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
        "estado": info.get("estado", "Inscrita"),
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

  data = {
      "id": user_id,
      "correo": correo,
      "pensum_data": pensum_json,
      "evaluaciones_data": evals_json,
      "horario_data": horario_json,
  }

  try:
    supabase.table("perfiles_usuario").upsert(data).execute()
    st.toast("💾 Cambios guardados automáticamente", icon="☁️")
  except Exception as e:
    st.error(f"Error al guardar datos: {e}")


# --- 6. RECUPERAR SESIÓN INDEPENDIENTE POR DISPOSITIVO (COOKIE) ---
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

  if prelaciones_raw.lower() in [
      "ninguna",
      "ninguno",
      "-",
      "",
      "none",
      "sin prelación",
  ]:
    return True, "Disponible"

  codigos_aprobados = df_completo[df_completo["estado"] == "Aprobada"][
      "codigo"
  ].tolist()
  materias_pre = [
      p.strip() for p in prelaciones_raw.replace("/", ",").split(",") if p.strip()
  ]
  faltantes = []

  for pre in materias_pre:
    if pre not in codigos_aprobados and pre.lower() not in ["ninguna", ""]:
      faltantes.append(pre)

  if len(faltantes) > 0:
    return (
        False,
        f"🔒 Bloqueada (Requiere aprobar: {', '.join(faltantes)})",
    )

  return True, "Disponible"


# --- 8. CÁLCULO DE PROMEDIO GLOBAL ---
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
          nota_mat = (
              (df_plan["Nota"] / 20.0)
              * (df_plan["Valor (%)"] / 100.0)
              * 20.0
          ).sum()
          if row["estado"] in ["Aprobada", "Reprobada", "En Curso"]:
            puntos_acumulados += nota_mat * cred
            total_creditos += cred

  if total_creditos > 0:
    return puntos_acumulados / total_creditos
  return 0.0


# --- 9. PANTALLA DE AUTENTICACIÓN ---
if st.session_state["usuario"] is None:
  st.title("🎓 Bienvenido a Mi App Universitaria")
  st.subheader(
      "Inicia sesión y marca la casilla si deseas recordar este dispositivo."
  )

  tab_login, tab_registro = st.tabs(["🔑 Iniciar Sesión", "📝 Registrarse"])

  with tab_login:
    with st.form("form_login"):
      email_login = st.text_input("Correo electrónico")
      pass_login = st.text_input("Contraseña", type="password")

      recordar_dispositivo = st.checkbox(
          "Confiar en este dispositivo (Mantener sesión abierta solo aquí)"
      )

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
              cookie_manager.set(
                  "dispositivo_confiable_token", nuevo_token, max_age=31536000
              )
              supabase.table("dispositivos_confiados").insert({
                  "user_id": res.user.id,
                  "device_token": nuevo_token,
                  "nombre_dispositivo": "Dispositivo Confiable Independiente",
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
            st.success(
                "¡Cuenta creada exitosamente! Ahora puedes iniciar sesión."
            )
        except Exception as e:
          st.error(f"Error al registrarse: {e}")

# --- 10. APLICACIÓN PRINCIPAL (USUARIO LOGUEADO) ---
else:
  st.sidebar.write(f"👤 **Usuario:** {st.session_state['usuario'].email}")

  with st.sidebar.expander("⚙️ Configuración de IA"):
    modelo_seleccionado = st.selectbox(
        "Selecciona el Modelo",
        [
            "gemini-3.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-2.5-flash",
        ],
        index=0,
        help=(
            "Elige un modelo alternativo si alcanzas el límite de solicitudes"
            " por minuto (RPM)."
        ),
    )

  st.sidebar.markdown("---")
  if st.sidebar.button("Cerrar Sesión en este equipo", key="btn_logout"):
    if device_token_cookie:
      try:
        supabase.table("dispositivos_confiados").delete().eq(
            "device_token", device_token_cookie
        ).execute()
      except Exception:
        pass
      cookie_manager.delete("dispositivo_confiable_token")

    supabase.auth.sign_out()
    st.session_state["usuario"] = None
    st.session_state["pensum_df"] = None
    st.session_state["evaluaciones"] = {}
    st.session_state["mensajes_chat"] = []
    st.rerun()

  st.title("🎓 Mi App Universitaria")

  # --- NOTIFICACIONES AUTOMÁTICAS DE ACTIVIDADES PENDIENTES ---
  if st.session_state["pensum_df"] is not None:
    hoy_fecha = datetime.date.today()
    avisos_pendientes = []
    
    df_pensum_temp = st.session_state["pensum_df"]
    materias_en_curso = df_pensum_temp[df_pensum_temp["estado"] == "En Curso"]["codigo"].tolist()
    
    for cod_mat in materias_en_curso:
      if cod_mat in st.session_state["evaluaciones"]:
        plan_evals = st.session_state["evaluaciones"][cod_mat].get("plan", [])
      else:
        plan_evals = [
            {"Evaluación": "Parcial 1", "Fecha": hoy_fecha},
            {"Evaluación": "Parcial 2", "Fecha": hoy_fecha},
            {"Evaluación": "Trabajo / Proyecto", "Fecha": hoy_fecha},
            {"Evaluación": "Exposición / Quices", "Fecha": hoy_fecha},
        ]
        
      for eval_item in plan_evals:
        f_eval = eval_item.get("Fecha")
        if isinstance(f_eval, str):
          try:
            f_eval = datetime.datetime.strptime(f_eval, "%Y-%m-%d").date()
          except ValueError:
            f_eval = hoy_fecha
        
        if isinstance(f_eval, datetime.date):
          dias_restantes = (f_eval - hoy_fecha).days
          if dias_restantes <= 7:
            nombre_eval = eval_item.get("Evaluación", "Actividad")
            
            if dias_restantes == 0:
              texto_tiempo = "la entrega es **hoy**"
            elif dias_restantes == 1:
              texto_tiempo = "vence **mañana**"
            elif dias_restantes < 0:
              texto_tiempo = f"está atrasada por **{abs(dias_restantes)} días**"
            else:
              texto_tiempo = f"faltan **{dias_restantes} días**"
              
            avisos_pendientes.append(f"📌 **{cod_mat}** - _{nombre_eval}_: {texto_tiempo}.")

    if avisos_pendientes:
      with st.expander("🔔 Notificaciones de Entregas Próximas", expanded=True):
        for aviso in avisos_pendientes:
          st.warning(aviso)

  tab_pensum, tab_horario, tab_chat = st.tabs([
      "📚 Pensum y Calificaciones",
      "📅 Horario de Clases",
      "⏱️ Pomodoro de Estudio Integrado",
  ])

  # ==========================================
  # PESTAÑA 1: PENSUM Y CALIFICACIONES
  # ==========================================
  with tab_pensum:
    st.subheader("📋 Pensum Estructurado por Niveles")

    if st.session_state["pensum_df"] is None:
      st.info(
          "👋 Carga tu pensum en formato PDF para organizar tus niveles"
          " académicos."
      )
      uploaded_file = st.file_uploader(
          "Sube el PDF de tu pensum universitario", type=["pdf"]
      )

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
                df["estado"] = "Inscrita"

              st.session_state["pensum_df"] = df
              guardar_datos_usuario()
              st.success("¡Pensum procesado y guardado!")
              st.rerun()

          except Exception as err:
            st.error(f"Error procesando el documento: {err}")

    else:
      if st.sidebar.button(
          "🗑️ Eliminar / Volver a subir Pensum", key="btn_eliminar_pensum"
      ):
        st.session_state["pensum_df"] = None
        st.session_state["evaluaciones"] = {}
        guardar_datos_usuario()
        st.rerun()

      df = st.session_state["pensum_df"]

      indice_aca = calcular_indice_academico(
          df, st.session_state["evaluaciones"]
      )

      col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
      with col_m1:
        st.metric("Total Materias", len(df))
      with col_m2:
        st.metric("Aprobadas", len(df[df["estado"] == "Aprobada"]))
      with col_m3:
        st.metric("En Curso", len(df[df["estado"] == "En Curso"]))
      with col_m4:
        st.metric(
            "Inscritas / Pendientes", len(df[df["estado"] == "Inscrita"])
        )
      with col_m5:
        st.metric("📈 Índice Académico", f"{indice_aca:.2f} / 20.0")

      st.divider()

      semestres = (
          list(df["semestre"].unique())
          if "semestre" in df.columns
          else ["Nivel Único"]
      )
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
            st.warning(
                f"⚠️ Tienes {bloqueadas_count} materia(s) bloqueada(s) por"
                " preliminares no aprobadas."
            )

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
                  "creditos": st.column_config.NumberColumn(
                      "Créditos", format="%d"
                  ),
                  "prelaciones": "Requisitos / Prelaciones",
                  "estado": "Estado Actual",
                  "Disponibilidad": st.column_config.TextColumn(
                      "Estatus de Acceso"
                  ),
              },
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
              st.error(
                  f"🔒 **{codigo_mat} - {nombre_mat}** está **bloqueada**."
                  f" Aprueba sus preliminares ({materia_sel.get('prelaciones')})"
                  " para registrar sus notas."
              )
            else:
              st.markdown(
                  f"### 📝 Plan de Evaluaciones: **{codigo_mat} - {nombre_mat}**"
              )

              if codigo_mat not in st.session_state["evaluaciones"]:
                hoy = datetime.date.today()
                st.session_state["evaluaciones"][codigo_mat] = {
                    "estado": materia_sel.get("estado", "Inscrita"),
                    "plan": [
                        {
                            "Evaluación": "Parcial 1",
                            "Tema": "Unidad 1",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                        },
                        {
                            "Evaluación": "Parcial 2",
                            "Tema": "Unidad 2",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                        },
                        {
                            "Evaluación": "Trabajo / Proyecto",
                            "Tema": "Unidad 3",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                        },
                        {
                            "Evaluación": "Exposición / Quices",
                            "Tema": "Unidad 4",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                        },
                    ],
                }

              col_e1, col_e2 = st.columns(2)
              with col_e1:
                estado_actual = (
                    st.session_state["evaluaciones"][codigo_mat]
                    .get("estado", "Inscrita")
                )
                idx_e = (
                    [
                        "Inscrita",
                        "En Curso",
                        "Aprobada",
                        "Reprobada",
                    ].index(estado_actual)
                    if estado_actual
                    in ["Inscrita", "En Curso", "Aprobada", "Reprobada"]
                    else 0
                )

                nuevo_est = st.selectbox(
                    "Estado de la Materia:",
                    ["Inscrita", "En Curso", "Aprobada", "Reprobada"],
                    index=idx_e,
                    key=f"sel_est_{codigo_mat}",
                )

                if nuevo_est != estado_actual:
                  st.session_state["evaluaciones"][codigo_mat][
                      "estado"
                  ] = nuevo_est
                  st.session_state["pensum_df"].loc[
                      st.session_state["pensum_df"]["codigo"] == codigo_mat,
                      "estado",
                  ] = nuevo_est
                  guardar_datos_usuario()
                  st.rerun()

              with col_e2:
                escala_sel = st.radio(
                    "Escala para ingresar notas:",
                    ["0 - 20 pts", "0 - 100%"],
                    horizontal=True,
                    key=f"radio_esc_{codigo_mat}",
                )

              df_eval_actual = pd.DataFrame(
                  st.session_state["evaluaciones"][codigo_mat]["plan"]
              )

              if "Tema" not in df_eval_actual.columns:
                df_eval_actual["Tema"] = ""
              if "Fecha" not in df_eval_actual.columns:
                df_eval_actual["Fecha"] = datetime.date.today()

              max_nota = 20.0 if "20" in escala_sel else 100.0

              edited_df = st.data_editor(
                  df_eval_actual[["Evaluación", "Tema", "Valor (%)", "Nota", "Fecha"]],
                  num_rows="dynamic",
                  use_container_width=True,
                  key=f"editor_{codigo_mat}",
                  column_config={
                      "Evaluación": st.column_config.TextColumn("Evaluación"),
                      "Tema": st.column_config.TextColumn("Tema"),
                      "Valor (%)": st.column_config.NumberColumn(
                          "Valor (%)", min_value=0, max_value=100, step=1
                      ),
                      "Nota": st.column_config.NumberColumn(
                          f"Nota ({'0-20 pts' if '20' in escala_sel else '0-100%'})",
                          min_value=0.0,
                          max_value=max_nota,
                          step=0.5,
                      ),
                      "Fecha": st.column_config.DateColumn(
                          "Fecha de Entrega", format="YYYY-MM-DD"
                      ),
                  },
              )

              if not edited_df.equals(
                  df_eval_actual[["Evaluación", "Tema", "Valor (%)", "Nota", "Fecha"]]
              ):
                st.session_state["evaluaciones"][codigo_mat]["plan"] = (
                    edited_df.to_dict("records")
                )
                guardar_datos_usuario()

              st.markdown("---")
              st.markdown("#### 📊 Resumen de Rendimiento")

              peso_planificado = (
                  edited_df["Valor (%)"].sum()
                  if "Valor (%)" in edited_df.columns
                  else 0.0
              )

              if "20" in escala_sel:
                max_nota = 20.0
                min_aprobar = 12
                unidad = "puntos"
              else:
                max_nota = 100.0
                min_aprobar = 60
                unidad = "%"

              puntos_acum = 0.0
              if "Nota" in edited_df.columns and "Valor (%)" in edited_df.columns:
                puntos_acum = (
                    (edited_df["Nota"] / max_nota)
                    * (edited_df["Valor (%)"] / 100.0)
                    * max_nota
                ).sum()

              porcentaje_efectivo = (
                  (puntos_acum / max_nota) * 100.0 if max_nota > 0 else 0.0
              )
              falta_peso = 100.0 - peso_planificado

              col_ac1, col_ac2, col_ac3 = st.columns(3)

              col_ac1.metric(
                  label="Porcentaje Obtenido / Evaluado",
                  value=f"{porcentaje_efectivo:.1f}% / {peso_planificado:.1f}%",
              )

              col_ac2.metric(
                  label="Nota Acumulada",
                  value=f"{puntos_acum:.2f} / {max_nota:.1f} {unidad}",
              )

              st.markdown("---")
              st.markdown("#### ✅ Resultado Final")

              nota_final_objetivo = 12 if "20" in escala_sel else 60

              if puntos_acum >= nota_final_objetivo:
                st.success(
                    f"¡Felicidades! Con {puntos_acum:.2f} {unidad}, estás"
                    " **APROBADO** en esta materia."
                )
                if st.button("Marcar como Aprobada automáticamente"):
                  st.session_state["evaluaciones"][codigo_mat][
                      "estado"
                  ] = "Aprobada"
                  st.session_state["pensum_df"].loc[
                      st.session_state["pensum_df"]["codigo"] == codigo_mat,
                      "estado",
                  ] = "Aprobada"
                  guardar_datos_usuario()
                  st.rerun()
              else:
                faltan = nota_final_objetivo - puntos_acum
                st.warning(
                    f"Aún no alcanzas la nota mínima. Te faltan"
                    f" **{faltan:.2f} {unidad}** para aprobar."
                )

                if falta_peso > 0:
                  nota_necesaria = (faltan / falta_peso) * 100
                  st.info(
                      "💡 Necesitas un promedio de"
                      f" **{nota_necesaria:.1f} pts** en lo que queda por"
                      f" evaluar ({falta_peso:.1f}%) para aprobar."
                  )

  # ==========================================
  # PESTAÑA 2: HORARIO DE CLASES
  # ==========================================
  with tab_horario:
    st.subheader("📅 Gestión de Horario de Clases")

    if st.session_state.get("horario_df") is None:
      st.info(
          "👋 Sube tu horario de clases en formato PDF para organizarlo"
          " automáticamente."
      )
      uploaded_horario = st.file_uploader(
          "Sube el PDF de tu horario", type=["pdf"], key="file_uploader_horario"
      )

      if uploaded_horario and st.button(
          "📊 Procesar y Organizar Horario", key="btn_procesar_horario"
      ):
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
                        Devuelve la respuesta ÚNICAMENTE como una estructura JSON válida, que sea una lista de objetos con exactamente estas claves:
                        [
                          {
                            "dia": "Lunes",
                            "materia": "Matemática I",
                            "inicio": "08:00",
                            "fin": "10:00",
                            "aula": "Aula 101"
                          }
                        ]
                        Asegúrate de que las horas estén en formato de 24 horas (HH:MM).
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

              df_h.columns = [
                  c.lower().strip().replace(" ", "_") for c in df_h.columns
              ]
              dias_map = {
                  "lunes": 1,
                  "martes": 2,
                  "miércoles": 3,
                  "miercoles": 3,
                  "jueves": 4,
                  "viernes": 5,
                  "sábado": 6,
                  "sabado": 6,
                  "domingo": 7,
              }
              df_h["d_orden"] = (
                  df_h["dia"].str.lower().map(dias_map).fillna(8)
              )
              df_h = df_h.sort_values(by=["d_orden", "inicio"])

              resultado_agrupado = []
              for _, row in df_h.iterrows():
                if not resultado_agrupado:
                  resultado_agrupado.append(row.to_dict())
                else:
                  prev = resultado_agrupado[-1]
                  if (
                      row["dia"] == prev["dia"]
                      and row["materia"] == prev["materia"]
                      and row["inicio"] == prev["fin"]
                  ):
                    prev["fin"] = row["fin"]
                  else:
                    resultado_agrupado.append(row.to_dict())

              df_final_horario = pd.DataFrame(resultado_agrupado)
              if "d_orden" in df_final_horario.columns:
                df_final_horario = df_final_horario.drop(columns=["d_orden"])

              df_final_horario["notificar"] = True

              st.session_state["horario_df"] = df_final_horario
              guardar_datos_usuario()
              st.success(
                  "¡Horario procesado, organizado y guardado con éxito!"
              )
              st.rerun()

          except Exception as err:
            st.error(f"Error procesando el horario: {err}")
    else:
      if st.button(
          "🗑️ Eliminar / Volver a subir Horario", key="btn_eliminar_horario"
      ):
        st.session_state["horario_df"] = None
        guardar_datos_usuario()
        st.rerun()

      col1, col2 = st.columns([1, 3])
      with col1:
        activar_alertas = st.toggle("Activar alertas", value=True)
      with col2:
        tiempo_alerta = st.select_slider(
            "Anticipación (min):", [5, 10, 15], value=5
        )

      df_horario_actual = st.session_state["horario_df"]

      if "notificar" not in df_horario_actual.columns:
        df_horario_actual["notificar"] = True

      st.markdown("### 📋 Tu Horario Académico Organizado")

      df_editado = st.data_editor(
          df_horario_actual,
          column_config={
              "notificar": st.column_config.CheckboxColumn("¿Recibir aviso?")
          },
          use_container_width=True,
          hide_index=True,
          key="editor_horario",
      )
      st.session_state["horario_df"] = df_editado

      ahora_dt = datetime.datetime.now()
      hora_actual_minutos = ahora_dt.hour * 60 + ahora_dt.minute

      if activar_alertas:
        for _, clase in df_editado.iterrows():
          if clase.get("notificar", True):
            try:
              h_ini, m_ini = map(int, str(clase["inicio"]).split(":"))
              inicio_en_minutos = h_ini * 60 + m_ini

              diferencia = inicio_en_minutos - hora_actual_minutos

              if diferencia == tiempo_alerta:
                materia_alerta = clase["materia"]
                aula_alerta = clase.get("aula", "asignada")
                mensaje_alerta = f"Atención: La clase de {materia_alerta} en el aula {aula_alerta} comienza en {tiempo_alerta} minutos."

                st.toast(f"🚨 {mensaje_alerta}", icon="⏳")

                js_voz = f"""
                                <script>
                                    var utterance = new SpeechSynthesisUtterance("{mensaje_alerta}");
                                    utterance.lang = 'es-ES';
                                    window.speechSynthesis.speak(utterance);
                                </script>
                                """
                st.components.v1.html(js_voz, height=0)
            except Exception:
              pass

  # ==========================================
  # PESTAÑA 3: Técnica Pomodoro
  # ==========================================
  with tab_chat:
    st.subheader("🍅 Técnica Pomodoro")

    with st.expander("¿Qué es esto?"):
      st.write("""
            Esta herramienta utiliza la técnica **Pomodoro** para mejorar tu productividad:
            1. **Foco:** Trabaja durante 25 minutos sin distracciones.
            2. **Descanso corto:** 5 minutos para estirar las piernas.
            3. **Descanso largo:** 20 minutos para recargar tras varios ciclos.
            """)

    if "pomodoro_tiempo" not in st.session_state:
      st.session_state["pomodoro_tiempo"] = 25 * 60
    if "pomodoro_activo" not in st.session_state:
      st.session_state["pomodoro_activo"] = False


    def actualizar_tiempo():
      modo = st.session_state["modo_seleccionado"]
      if "25m" in modo:
        st.session_state["pomodoro_tiempo"] = 25 * 60
      elif "5m" in modo:
        st.session_state["pomodoro_tiempo"] = 5 * 60
      else:
        st.session_state["pomodoro_tiempo"] = 20 * 60
      st.session_state["pomodoro_activo"] = False


    st.radio(
        "Selecciona tu sesión:",
        ["Foco (25m)", "Descanso Corto (5m)", "Descanso Largo (20m)"],
        horizontal=True,
        key="modo_seleccionado",
        on_change=actualizar_tiempo,
    )

    minutos = st.session_state["pomodoro_tiempo"] // 60
    segundos = st.session_state["pomodoro_tiempo"] % 60
    st.metric("Tiempo restante", f"{minutos:02d}:{segundos:02d}")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
      if st.button("▶️ Iniciar"):
        st.session_state["pomodoro_activo"] = True
    with col2:
      if st.button("⏸️ Pausar"):
        st.session_state["pomodoro_activo"] = False
    with col3:
      if st.button("🔄 Reiniciar"):
        actualizar_tiempo()
        st.session_state["pomodoro_activo"] = True
    with col4:
      if st.button("⏹️ Detener"):
        st.session_state["pomodoro_activo"] = False
        actualizar_tiempo()

    import time

    if (
        st.session_state["pomodoro_activo"]
        and st.session_state["pomodoro_tiempo"] > 0
    ):
      time.sleep(1)
      st.session_state["pomodoro_tiempo"] -= 1
      st.rerun()
    elif (
        st.session_state["pomodoro_tiempo"] == 0
        and st.session_state["pomodoro_activo"]
    ):
      st.balloons()
      st.success("¡Tiempo finalizado!")
      st.session_state["pomodoro_activo"] = False
