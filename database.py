import os
from supabase import create_client, Client

# Inicialización del cliente de Supabase (puedes usar st.secrets si prefieres)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def get_supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def obtener_datos_pensum():
    supabase = get_supabase_client()
    response = supabase.table("pensum").select("*").execute()
    return response.data

def actualizar_calificacion(materia_id, nueva_nota):
    supabase = get_supabase_client()
    supabase.table("pensum").update({"calificacion": nueva_nota}).eq("id", materia_id).execute()
