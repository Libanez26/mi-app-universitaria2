if "pensum_df" not in st.session_state:
    st.session_state["pensum_df"] = None
if "evaluaciones" not in st.session_state:
    st.session_state["evaluaciones"] = {}
if "escala_df" not in st.session_state:
    st.session_state["escala_df"] = pd.DataFrame()Z

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
                # Sincronizamos el estado de la materia priorizando el diccionario de evaluaciones o el DataFrame
                estado_actual = st.session_state["evaluaciones"][codigo_mat].get("estado", materia_sel.get("estado", "No Inscrita"))
                
                estados_disponibles = [
                    "No Inscrita",
                    "Inscrita",
                    "En Curso",
                    "Aprobada",
                    "Reprobada",
                ]
                
                key_selectbox_estado = f"sel_est_{codigo_mat}"

                idx_e = (
                    estados_disponibles.index(estado_actual)
                    if estado_actual in estados_disponibles
                    else 0
                )

                nuevo_est = st.selectbox(
                    "Estado de la Materia:",
                    estados_disponibles,
                    index=idx_e,
                    key=key_selectbox_estado,
                )

                if nuevo_est != estado_actual:
                  # Actualizamos tanto el diccionario como el DataFrame global del pensum
                  st.session_state["evaluaciones"][codigo_mat]["estado"] = nuevo_est
                  st.session_state["pensum_df"].loc[
                      st.session_state["pensum_df"]["codigo"] == codigo_mat,
                      "estado",
                  ] = nuevo_est
                  guardar_datos_usuario()
                  st.rerun()

              with col_e2:
                key_escala_anterior = f"escala_anterior_{codigo_mat}"
                if key_escala_anterior not in st.session_state:
                    st.session_state[key_escala_anterior] = "Acumulativa (Suma de notas)"

                escala_sel = st.radio(
                    "Tipo de Cálculo de Notas:",
                    ["Acumulativa (Suma de notas)", "Promediada (Promedio de notas)"],
                    horizontal=True,
                    key=f"radio_esc_{codigo_mat}",
                )

                if escala_sel != st.session_state[key_escala_anterior]:
                    st.session_state[key_escala_anterior] = escala_sel
                    guardar_datos_usuario()

              plan_data_inicial = st.session_state["evaluaciones"][codigo_mat]["plan"]
              df_eval_actual = pd.DataFrame(plan_data_inicial)

              for col_req in [
                  "Evaluación",
                  "Tema",
                  "Valor (%)",
                  "Nota",
                  "Fecha",
                  "Entregada",
              ]:
                if col_req not in df_eval_actual.columns:
                  if col_req == "Valor (%)":
                    df_eval_actual[col_req] = 25.0
                  elif col_req == "Nota":
                    df_eval_actual[col_req] = 0.0
                  elif col_req == "Entregada":
                    df_eval_actual[col_req] = False
                  elif col_req == "Fecha":
                    df_eval_actual[col_req] = datetime.date.today()
                  else:
                    df_eval_actual[col_req] = ""

              if "Nota (%)" not in df_eval_actual.columns:
                df_eval_actual["Nota (%)"] = (
                    df_eval_actual["Nota"] / 20.0
                ) * df_eval_actual["Valor (%)"]

              def obtener_nota_desde_escala(pct_obtenido):
                df_escala = st.session_state.get("escala_df", pd.DataFrame())
                if df_escala.empty:
                  return round((pct_obtenido / 100.0) * 20.0, 2)
                
                for _, row in df_escala.iterrows():
                  rango_str = str(row.get("Nivel de logro de la asignatura", ""))
                  if "-" in rango_str:
                    try:
                      partes = rango_str.replace("%", "").split("-")
                      min_r = float(partes[0].strip())
                      max_r = float(partes[1].strip())
                      if min_r <= pct_obtenido <= max_r:
                        val_cuant = float(row.get("Calificación Cuantitativa", 0))
                        return val_cuant
                    except ValueError:
                      continue
                return round((pct_obtenido / 100.0) * 20.0, 2)

              def sincronizar_notas_editor():
                editor_key = f"editor_{codigo_mat}"
                if editor_key not in st.session_state:
                  return

                edited_data = st.session_state[editor_key]
                plan_actual = st.session_state["evaluaciones"][codigo_mat][
                    "plan"
                ]

                for i_str, cambios in edited_data.get(
                    "edited_rows", {}
                ).items():
                  i = int(i_str)
                  if i >= len(plan_actual):
                    continue

                  if "Nota (%)" in cambios:
                    nuevo_pct = float(cambios["Nota (%)"])
                    nuevo_pct = max(0.0, min(100.0, nuevo_pct))
                    plan_actual[i]["Nota (%)"] = nuevo_pct
                    
                    pts_calculados = obtener_nota_desde_escala(nuevo_pct)
                    plan_actual[i]["Nota"] = pts_calculados

                  elif "Nota" in cambios:
                    nuevo_pts = float(cambios["Nota"])
                    nuevo_pts = max(
                        0.0, min(20.0, nuevo_pts)
                    )
                    plan_actual[i]["Nota"] = nuevo_pts
                    plan_actual[i]["Nota (%)"] = round(
                        (nuevo_pts / 20.0) * 100.0, 2
                    )

                if "added_rows" in edited_data and edited_data["added_rows"]:
                  for row_nueva in edited_data["added_rows"]:
                    p_val = float(row_nueva.get("Nota", 0.0))
                    v_val = float(row_nueva.get("Valor (%)", 25.0))
                    pct_val = float(row_nueva.get("Nota (%)", (p_val / 20.0) * 100.0))
                    
                    pts_calculados = obtener_nota_desde_escala(pct_val)
                    row_nueva["Nota (%)"] = pct_val
                    row_nueva["Nota"] = pts_calculados
                    plan_actual.append(row_nueva)

                if "deleted_rows" in edited_data and edited_data[
                    "deleted_rows"
                ]:
                  indices_a_borrar = sorted(
                      edited_data["deleted_rows"], reverse=True
                  )
                  for idx_del in indices_a_borrar:
                    if idx_del < len(plan_actual):
                      plan_actual.pop(idx_del)

              sincronizar_notas_editor()

              edited_df = st.data_editor(
                  df_eval_actual[[
                      "Evaluación",
                      "Tema",
                      "Valor (%)",
                      "Nota",
                      "Nota (%)",
                      "Fecha",
                      "Entregada",
                  ]],
                  num_rows="dynamic",
                  use_container_width=True,
                  key=f"editor_{codigo_mat}",
                  on_change=sincronizar_notas_editor,
                  column_config={
                      "Evaluación": st.column_config.TextColumn("Evaluación"),
                      "Tema": st.column_config.TextColumn("Tema"),
                      "Valor (%)": st.column_config.NumberColumn(
                          "Valor (%)", min_value=0, max_value=100, step=1
                      ),
                      "Nota": st.column_config.NumberColumn(
                          "Nota (0-20 pts)",
                          min_value=0.0,
                          max_value=20.0,
                          step=0.5,
                          format="%.1f",
                      ),
                      "Nota (%)": st.column_config.NumberColumn(
                          "Nota (%)",
                          min_value=0.0,
                          max_value=100.0,
                          step=0.1,
                          format="%.2f%%",
                      ),
                      "Fecha": st.column_config.DateColumn(
                          "Fecha de Entrega", format="YYYY-MM-DD"
                      ),
                      "Entregada": st.column_config.CheckboxColumn(
                          "¿Entregada?"
                      ),
                  },
              )

              if st.button("💾 Guardar Notas", key=f"btn_guardar_notas_{codigo_mat}"):
                sincronizar_notas_editor()
                guardar_datos_usuario()
                st.success("¡Notas guardadas correctamente!")
                st.rerun()

              st.markdown("---")
              st.markdown("#### 📊 Resumen de Rendimiento")

              es_acumulativa = "Acumulativa" in escala_sel
              min_aprobar = 12

              puntos_acum = 0.0
              porcentaje_acum = 0.0

              if "Nota" in edited_df.columns and not edited_df.empty:
                notas_validas = edited_df["Nota"].dropna()
                if len(notas_validas) > 0:
                  if es_acumulativa:
                    puntos_acum = notas_validas.sum()
                  else:
                    puntos_acum = notas_validas.mean()
                else:
                  puntos_acum = 0.0

              if "Nota (%)" in edited_df.columns and not edited_df.empty:
                porcentajes_validos = edited_df["Nota (%)"].dropna()
                if len(porcentajes_validos) > 0:
                  if es_acumulativa:
                    porcentaje_acum = porcentajes_validos.sum()
                  else:
                    porcentaje_acum = porcentajes_validos.mean()
                else:
                  porcentaje_acum = 0.0

              resultado_combinado = f"{puntos_acum:.2f} pts / {porcentaje_acum:.1f}%"

              col_ac1, col_ac2 = st.columns(2)
              col_ac1.metric(
                  label="Modo de Cálculo",
                  value=escala_sel,
              )
              col_ac2.metric(
                  label="Resultado Obtenido",
                  value=resultado_combinado,
              )

              st.markdown("---")
              st.markdown("#### ✅ Resultado Final")

              if puntos_acum >= min_aprobar:
                  st.success(
                      f"¡Felicidades! Con {puntos_acum:.2f} pts / {porcentaje_acum:.1f}%, estás"
                      " **APROBADO** en esta materia."
                  )
                  if st.button("Marcar como Aprobada automáticamente", key=f"btn_aprob_{codigo_mat}"):
                      # 1. Actualizar estado en evaluaciones
                      if codigo_mat not in st.session_state["evaluaciones"]:
                          st.session_state["evaluaciones"][codigo_mat] = {"estado": "Aprobada", "plan": []}
                      else:
                          st.session_state["evaluaciones"][codigo_mat]["estado"] = "Aprobada"
                      
                      # 2. Actualizar estado en el DataFrame global del pensum para desbloquear prelaciones
                      st.session_state["pensum_df"].loc[
                          st.session_state["pensum_df"]["codigo"] == codigo_mat,
                          "estado",
                      ] = "Aprobada"
                      
                      # 3. Limpiar caché del selectbox de estado para forzar el cambio visual inmediato
                      if key_selectbox_estado in st.session_state:
                          del st.session_state[key_selectbox_estado]
                      
                      # 4. Guardar y refrescar la app
                      guardar_datos_usuario()
                      st.toast(f"¡La materia {codigo_mat} ahora está Aprobada!", icon="🎉")
                      st.rerun()
              else:
                  faltan = min_aprobar - puntos_acum
                  st.warning(
                      f"Con {puntos_acum:.2f} pts / {porcentaje_acum:.1f}%, aún no alcanzas la nota mínima. Te faltan"
                      f" **{faltan:.2f} pts** para aprobar."
                  )

              st.markdown("---")
              with st.expander("📌 Ver / Configurar Tabla de Escala Evaluativa de Referencia"):
              
                archivo_pdf = st.file_uploader("Sube el PDF de la Escala Evaluativa", type=["pdf"], key=f"uploader_escala_{codigo_mat}")

                if archivo_pdf is not None:
                    with st.spinner("Procesando escala evaluativa con Gemini..."):
                      try:
                        api_key = str(st.secrets["GEMINI_API_KEY"]).strip()
                        client = genai.Client(api_key=api_key)

                        pdf_bytes = archivo_pdf.read()
                        pdf_part = types.Part.from_bytes(
                            data=pdf_bytes, mime_type="application/pdf"
                        )

                        prompt_escala = """
                        Extrae la tabla de escala de notas o calificación institucional del documento proporcionado.
                        Devuelve la respuesta ÚNICAMENTE como una estructura JSON válida, que sea una lista de objetos con exactamente estas claves:
                        [
                          {
                            "Nivel de logro de la asignatura": "00% - 05%",
                            "Calificación Cuantitativa": "01",
                            "Calificación Cualitativa": "MUY DEFICIENTE"
                          }
                        ]
                        """

                        response_escala = client.models.generate_content(
                            model=modelo_seleccionado, contents=[prompt_escala, pdf_part]
                        )

                        if response_escala and response_escala.text:
                          clean_text_esc = response_escala.text.strip()
                          if clean_text_esc.startswith("```json"):
                            clean_text_esc = clean_text_esc[7:]
                          if clean_text_esc.startswith("```"):
                            clean_text_esc = clean_text_esc[3:]
                          if clean_text_esc.endswith("```"):
                            clean_text_esc = clean_text_esc[:-3]

                          data_escala = json.loads(clean_text_esc.strip())
                          st.session_state["escala_df"] = pd.DataFrame(data_escala)
                          guardar_datos_usuario()
                          st.success("¡PDF procesado y escala actualizada correctamente!")
                          st.rerun()
                      except Exception as err_esc:
                        st.error(f"Error procesando el PDF de escala: {err_esc}")

                col_esc_btn1, col_esc_btn2 = st.columns([3, 1])
                with col_esc_btn2:
                  if st.button("🗑️ Vaciar Tabla", key=f"btn_vaciar_escala_{codigo_mat}"):
                    st.session_state["escala_df"] = pd.DataFrame(columns=[
                        "Nivel de logro de la asignatura",
                        "Calificación Cuantitativa",
                        "Calificación Cualitativa"
                    ])
                    guardar_datos_usuario()
                    st.rerun()

                df_escala_actual = st.session_state["escala_df"]
                columnas_req_escala = [
                    "Nivel de logro de la asignatura",
                    "Calificación Cuantitativa",
                    "Calificación Cualitativa"
                ]
                for col in columnas_req_escala:
                  if col not in df_escala_actual.columns:
                    df_escala_actual[col] = ""

                with st.form(f"form_editor_escala_{codigo_mat}"):
                  df_escala_editado = st.data_editor(
                      df_escala_actual[columnas_req_escala],
                      num_rows="dynamic",
                      use_container_width=True,
                      key=f"editor_escala_{codigo_mat}",
                      column_config={
                          "Nivel de logro de la asignatura": st.column_config.TextColumn("Nivel de logro de la asignatura"),
                          "Calificación Cuantitativa": st.column_config.TextColumn("Calificación Cuantitativa"),
                          "Calificación Cualitativa": st.column_config.TextColumn("Calificación Cualitativa"),
                      }
                  )
                  submit_escala = st.form_submit_button("💾 Guardar Cambios en la Escala")
                  if submit_escala:
                    st.session_state["escala_df"] = df_escala_editado
                    guardar_datos_usuario()
                    st.success("¡Escala evaluativa actualizada correctamente!")
                    st.rerun()
