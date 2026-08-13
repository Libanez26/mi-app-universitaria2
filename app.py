import datetime
import json
import uuid
import extra_streamlit_components as st_cookie
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
if "mensajes_asistente" not in st.session_state:
  st.session_state["mensajes_asistente"] = [{
      "role": "assistant",
      "content": (
          "¡Hola! Soy tu asistente virtual. ¿En qué te puedo ayudar hoy?"
      ),
  }]


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
          "Confiar en este dispositivo (Mantener sesión abierta solo aquí)",
          value=True
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

              js_pedir_permiso = """
              <script>
                  if (window.Notification && Notification.permission !== "granted") {
                      Notification.requestPermission().then(permission => {
                          if (permission === "granted") {
                              console.log("Permiso de notificación concedido.");
                          }
                      });
                  }
              </script>
              """
              st.components.v1.html(js_pedir_permiso, height=0)

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
            "Si un modelo presenta alta demanda (503), la aplicación intentará "
            "automáticamente con otra versión disponible."
        ),
    )

  st.sidebar.markdown("---")

  if st.sidebar.button("🔄 Refrescar Página", key="btn_refrescar_pagina"):
    components.html(
        """
        <script>
            window.parent.location.reload();
        </script>
        """,
        height=0,
    )

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
    st.session_state["mensajes_asistente"] = [{
        "role": "assistant",
        "content": (
            "¡Hola! Soy tu asistente virtual. ¿En qué te puedo ayudar hoy?"
        ),
    }]
    st.rerun()

  st.title("🎓 Mi App Universitaria")

  tab_pensum, tab_horario, tab_asistente, tab_pomodoro = st.tabs([
      "📚 Pensum y Calificaciones",
      "📅 Horario de Clases",
      "🤖 Asistente Virtual IA",
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
                df["estado"] = "No Inscrita"

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

      col_m1, col_m2, col_m3, col_m4, col_m5, col_m6 = st.columns(6)
      with col_m1:
        st.metric("Total Materias", len(df))
      with col_m2:
        st.metric("Aprobadas", len(df[df["estado"] == "Aprobada"]))
      with col_m3:
        st.metric("En Curso", len(df[df["estado"] == "En Curso"]))
      with col_m4:
        st.metric(
            "Inscritas", len(df[df["estado"] == "Inscrita"])
        )
      with col_m5:
        st.metric(
            "No Inscritas", len(df[df["estado"] == "No Inscrita"])
        )
      with col_m6:
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
                    "estado": materia_sel.get("estado", "No Inscrita"),
                    "plan": [
                        {
                            "Evaluación": "Parcial 1",
                            "Tema": "Unidad 1",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                            "Entregada": False,
                        },
                        {
                            "Evaluación": "Parcial 2",
                            "Tema": "Unidad 2",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                            "Entregada": False,
                        },
                        {
                            "Evaluación": "Trabajo / Proyecto",
                            "Tema": "Unidad 3",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                            "Entregada": False,
                        },
                        {
                            "Evaluación": "Exposición / Quices",
                            "Tema": "Unidad 4",
                            "Valor (%)": 25,
                            "Nota": 0.0,
                            "Fecha": hoy,
                            "Entregada": False,
                        },
                    ],
                }

              col_e1, col_e2 = st.columns(2)
              with col_e1:
                estado_actual = (
                    st.session_state["evaluaciones"][codigo_mat]
                    .get("estado", "No Inscrita")
                )
                estados_disponibles = [
                    "No Inscrita",
                    "Inscrita",
                    "En Curso",
                    "Aprobada",
                    "Reprobada",
                ]
                idx_e = (
                    estados_disponibles.index(estado_actual)
                    if estado_actual in estados_disponibles
                    else 0
                )

                nuevo_est = st.selectbox(
                    "Estado de la Materia:",
                    estados_disponibles,
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

              for item in st.session_state["evaluaciones"][codigo_mat]["plan"]:
                if "Entregada" not in item:
                  item["Entregada"] = False

              df_eval_actual = pd.DataFrame(
                  st.session_state["evaluaciones"][codigo_mat]["plan"]
              )

              if "Tema" not in df_eval_actual.columns:
                df_eval_actual["Tema"] = ""
              if "Fecha" not in df_eval_actual.columns:
                df_eval_actual["Fecha"] = datetime.date.today()

              max_nota = 20.0 if "20" in escala_sel else 100.0

              with st.form(key=f"form_editor_notas_{codigo_mat}"):
                edited_df = st.data_editor(
                    df_eval_actual[["Evaluación", "Tema", "Valor (%)", "Nota", "Fecha", "Entregada"]],
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
                        "Entregada": st.column_config.CheckboxColumn("¿Entregada?"),
                    },
                )

                submit_notas = st.form_submit_button("💾 Guardar Notas")

                if submit_notas:
                  st.session_state["evaluaciones"][codigo_mat]["plan"] = (
                      edited_df.to_dict("records")
                  )
                  guardar_datos_usuario()
                  st.success("¡Notas guardadas correctamente!")
                  st.rerun()

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
                        Asegúrate de que las horas estén en formato de 12 horas con AM o PM (ej. "08:00 AM", "02:30 PM").
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
              
              columnas_deseadas = ["dia", "materia", "aula", "inicio", "fin"]
              for col in columnas_deseadas:
                if col not in df_h.columns:
                  df_h[col] = ""
              df_h = df_h[columnas_deseadas]

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
              df_h = df_h.drop(columns=["d_orden"])

              st.session_state["horario_df"] = df_h
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

  # ==========================================
# PESTAÑA 3: ASISTENTE VIRTUAL UNIVERSITARIO
# ==========================================
with tab_asistente:
    st.subheader("🤖 Asistente Virtual Universitario")
    st.write(
        "Elige si prefieres interactuar mediante el menú de botones guiados o conversar libremente con el chat de IA."
    )

    # Selector superior para alternar los modos
    tipo_asistente = st.radio(
        "Selecciona el modo de interacción:",
        ["🧭 Asistente Guiado (Solo Botones)", "💬 Chat Libre (Conversacional)"],
        horizontal=True,
        key="selector_modo_asistente",
    )

    # Inicialización de variables de sesión
    if "modo_asistente" not in st.session_state:
        st.session_state["modo_asistente"] = "menu_principal"
    if "sub_modo" not in st.session_state:
        st.session_state["sub_modo"] = None
    
    # Historiales independientes o compartidos de mensajería estilo chat
    if "mensajes_guiado" not in st.session_state:
        st.session_state["mensajes_guiado"] = [{
            "role": "assistant",
            "content": (
                "¡Hola! Soy tu asistente guiado. "
                "Selecciona una de las opciones del menú superior para consultar tu información académica de forma rápida."
            ),
        }]
    if "mensajes_conversacional" not in st.session_state:
        st.session_state["mensajes_conversacional"] = [{
            "role": "assistant",
            "content": (
                "¡Hola! Soy tu chat conversacional con IA. "
                "Escribe cualquier duda sobre tu pensum, notas u horario y te responderé de inmediato."
            ),
        }]

    # Estilos CSS inyectados para simular una interfaz limpia de mensajería instantánea
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

    # ==========================================
    # MODO 1: ASISTENTE GUIADO (SOLO BOTONES, SIN CAJA DE TEXTO)
    # ==========================================
    if "Asistente Guiado" in tipo_asistente:
        col_bt1, col_bt2 = st.columns([4, 1])
        with col_bt2:
            if st.button("🗑️ Reiniciar", key="btn_reiniciar_guiado"):
                st.session_state["mensajes_guiado"] = [{
                    "role": "assistant",
                    "content": "¡Hola! Menú reiniciado. ¿Qué deseas consultar hoy?",
                }]
                st.session_state["modo_asistente"] = "menu_principal"
                st.session_state["sub_modo"] = None
                st.rerun()

        # Renderizar historial estilo chat para el modo guiado
        chat_html_g = '<div class="chat-container">'
        for mensaje in st.session_state["mensajes_guiado"]:
            if mensaje["role"] == "user":
                chat_html_g += f'<div class="msg-user"><div class="msg-title">Tú</div>{mensaje["content"]}</div>'
            else:
                chat_html_g += f'<div class="msg-assistant"><div class="msg-title">Asistente Guiado</div>{mensaje["content"]}</div>'
        chat_html_g += '</div>'
        st.markdown(chat_html_g, unsafe_allow_html=True)

        st.markdown("---")

        # RAMIFICACIÓN 1: MENÚ PRINCIPAL
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
                                    suma_parcial = 0
                                    total_val = 0
                                    for ev in plan:
                                        nota = ev.get("Nota")
                                        val = ev.get("Valor (%)", 25)
                                        if nota is not None:
                                            suma_parcial += float(nota) * (float(val) / 100.0)
                                            total_val += float(val)
                                    if total_val > 30 and (suma_parcial / (total_val / 100.0)) < 12:
                                        materias_en_riesgo.append(f"- **{nom_materia}** ({cod}): Promedio parcial bajo ({suma_parcial:.2f}).")

                    if materias_en_riesgo:
                        alertas_txt += "Se detectaron las siguientes materias con rendimiento bajo:\n" + "\n".join(materias_en_riesgo)
                    else:
                        alertas_txt += "✅ ¡Excelente noticia! No se registran materias en curso con notas en zona de riesgo actualmente."

                    st.session_state["mensajes_guiado"].append({"role": "user", "content": "Consultar materias en riesgo o con alertas pendientes"})
                    st.session_state["mensajes_guiado"].append({"role": "assistant", "content": alertas_txt})
                    st.rerun()

        # RAMIFICACIÓN 2: FILTRO DE ESTADO DE NOTAS
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

        # RAMIFICACIÓN 3: SELECCIONAR MATERIA ESPECÍFICA PARA NOTAS
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

                if st.button("Ver notas exactas y promedio", use_container_width=True, key="btn_g_ver_notas"):
                    detalle_notas = f"📊 **Notas exactas para: {materia_elegida}**\n\n- Condición: **{filtro_estado.capitalize()}**\n\n"
                    df_tabla_notas = None
                    if codigo_elegido and codigo_elegido in st.session_state.get("evaluaciones", {}):
                        plan_datos = st.session_state["evaluaciones"][codigo_elegido].get("plan", [])
                        if plan_datos:
                            df_tabla_notas = pd.DataFrame(plan_datos)

                    if df_tabla_notas is not None and not df_tabla_notas.empty:
                        suma_ponderada = 0
                        total_porcentaje = 0
                        c_nom = next((c for c in df_tabla_notas.columns if "evaluación" in c.lower() or "tema" in c.lower() or "nombre" in c.lower()), df_tabla_notas.columns[0])
                        c_nota = next((c for c in df_tabla_notas.columns if "nota" in c.lower() or "puntos" in c.lower()), None)
                        c_val = next((c for c in df_tabla_notas.columns if "valor" in c.lower() or "%" in c.lower()), None)

                        for idx, row in df_tabla_notas.iterrows():
                            nombre_ev = row.get(c_nom, f"Evaluación {idx+1}")
                            val_nota = float(row.get(c_nota, 0.0)) if c_nota and pd.notna(row.get(c_nota)) else 0.0
                            val_porc = float(row.get(c_val, 0.0)) if c_val and pd.notna(row.get(c_val)) else 25.0
                            
                            detalle_notas += f"- **{nombre_ev}**: {val_nota} pts (Valor: {val_porc}%)\n"
                            suma_ponderada += val_nota * (val_porc / 100.0)
                            total_porcentaje += val_porc

                        if total_porcentaje > 0:
                            promedio_calculado = (suma_ponderada / total_porcentaje) * 20 if total_porcentaje <= 1 else suma_ponderada
                            detalle_notas += f"\n⭐ **Promedio Definitivo:** **{promedio_calculado:.2f} / 20.0**"
                        else:
                            detalle_notas += f"\n⭐ **Promedio Definitivo:** Sin ponderación válida."
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

        # RAMIFICACIÓN 4: CONSULTAR HORARIO POR MATERIA
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

    # ==========================================
    # MODO 2: CHAT LIBRE CONVERSACIONAL (CON CAJA DE TEXTO ACTIVA)
    # ==========================================
    else:
        # Renderizar historial estilo chat para el modo conversacional
        chat_html_c = '<div class="chat-container">'
        for mensaje in st.session_state["mensajes_conversacional"]:
            if mensaje["role"] == "user":
                chat_html_c += f'<div class="msg-user"><div class="msg-title">Tú</div>{mensaje["content"]}</div>'
            else:
                chat_html_c += f'<div class="msg-assistant"><div class="msg-title">Asistente IA</div>{mensaje["content"]}</div>'
        chat_html_c += '</div>'
        st.markdown(chat_html_c, unsafe_allow_html=True)

        # Entrada de texto exclusiva para el chat libre
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

                    system_instruction = f"""
                    Eres un asistente virtual inteligente, amigable y versátil integrado en una aplicación universitaria.
                    Responde de forma natural, cordial y útil a cualquier saludo, pregunta general o consulta del usuario.
                    Si la pregunta está relacionada con su rendimiento, materias o clases, utiliza esta información de contexto del usuario:
                    --- PENSUM Y ESTADO DE MATERIAS ---
                    {pensum_resumen}
                    --- HORARIO DE CLASES ---
                    {horario_resumen}
                    """

                    modelos_a_probar = [modelo_seleccionado, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
                    modelos_a_probar = list(dict.fromkeys(modelos_a_probar))
                    response = None
                    ultimo_error = None

                    for mod in modelos_a_probar:
                        try:
                            response = client.models.generate_content(
                                model=mod,
                                contents=[
                                    system_instruction,
                                    f"Mensaje del usuario: {prompt_usuario}",
                                ],
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
                    error_msj = "Ocurrió un error temporal con la API de IA. Por favor, intenta de nuevo en unos segundos."
                    st.session_state["mensajes_conversacional"].append({
                        "role": "assistant",
                        "content": error_msj,
                    })
                    st.rerun()
  # ==========================================
# PESTAÑA 4: TÉCNICA POMODORO
# ==========================================
with tab_pomodoro:
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
        if st.button("▶️ Iniciar", key="btn_pomo_iniciar"):
            st.session_state["pomodoro_activo"] = True
    with col2:
        if st.button("⏸️ Pausar", key="btn_pomo_pausar"):
            st.session_state["pomodoro_activo"] = False
    with col3:
        if st.button("🔄 Reiniciar", key="btn_pomo_reiniciar"):
            actualizar_tiempo()
            st.session_state["pomodoro_activo"] = True
    with col4:
        if st.button("⏹️ Detener", key="btn_pomo_detener"):
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
