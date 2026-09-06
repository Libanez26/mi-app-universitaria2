if "pensum_df" not in st.session_state:
    st.session_state["pensum_df"] = None
if "evaluaciones" not in st.session_state:
    st.session_state["evaluaciones"] = {}
if "escala_df" not in st.session_state:
    st.session_state["escala_df"] = pd.DataFrame()

  # ==========================================
  # PESTAÑA 4: TÉCNICA POMODORO
  # ==========================================
  with tab_pomodoro:
    st.subheader("⏱️ Pomodoro de Estudio Integrado")

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
