import streamlit as st
from supabase import Client
import extra_streamlit_components as st_cookie

def gestionar_autenticacion(supabase: Client, cookie_manager: st_cookie.CookieManager):
    st.title("🎓 Bienvenido a tu App Universitaria")
    st.write("Inicia sesión o regístrate para continuar.")

    tab1, tab2 = st.tabs(["Iniciar Sesión", "Registrarse"])

    with tab1:
        st.subheader("Acceso a tu cuenta")
        correo_login = st.text_input("Correo electrónico", key="login_correo")
        password_login = st.text_input("Contraseña", type="password", key="login_pass")

        if st.button("Entrar", key="btn_login"):
            if not correo_login or not password_login:
                st.warning("Por favor, completa todos los campos.")
            else:
                try:
                    res = supabase.auth.sign_in_with_password({
                        "email": correo_login,
                        "password": password_login
                    })
                    st.session_state["usuario"] = res.user
                    st.success("¡Inicio de sesión exitoso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al iniciar sesión: {e}")

    with tab2:
        st.subheader("Crear una nueva cuenta")
        correo_reg = st.text_input("Correo electrónico", key="reg_correo")
        password_reg = st.text_input("Contraseña (mínimo 6 caracteres)", type="password", key="reg_pass")

        if st.button("Registrarse", key="btn_reg"):
            if not correo_reg or not password_reg:
                st.warning("Por favor, completa todos los campos.")
            else:
                try:
                    res = supabase.auth.sign_up({
                        "email": correo_reg,
                        "password": password_reg
                    })
                    st.success("¡Registro exitoso! Revisa tu correo para verificar tu cuenta o inicia sesión.")
                except Exception as e:
                    st.error(f"Error en el registro: {e}")
