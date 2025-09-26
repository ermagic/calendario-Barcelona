# Fichero: database.py (Versión Supabase)
import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def init_supabase_client() -> Client:
    """Inicializa y devuelve un cliente de Supabase."""
    try:
        supabase_url = st.secrets["supabase"]["url"]
        supabase_key = st.secrets["supabase"]["anon_key"]
        return create_client(supabase_url, supabase_key)
    except Exception as e:
        st.error(f"Error al conectar con Supabase: {e}")
        return None

# Creamos una instancia global para ser usada por los demás módulos
supabase = init_supabase_client()