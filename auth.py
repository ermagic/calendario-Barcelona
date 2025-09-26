# Fichero: auth.py (Versión Final)
import streamlit as st
from database import supabase

def verificar_usuario_supabase(email, password):
    """
    Verifica las credenciales contra Supabase Auth y recupera el perfil del usuario.
    Devuelve un diccionario con los datos del perfil si es exitoso, o None si falla.
    """
    if not supabase:
        st.error("La conexión con la base de datos no está disponible.")
        return None
        
    try:
        # 1. Iniciar sesión en el sistema de autenticación de Supabase
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        user = response.user
        
        if user:
            # 2. Si el login es correcto, buscar su perfil en la tabla 'usuarios'
            profile_response = supabase.table('usuarios').select('*').eq('id', user.id).single().execute()
            
            # .single() asegura que solo obtenemos un resultado.
            # .data contendrá el diccionario del perfil
            user_profile = profile_response.data
            
            if user_profile:
                return user_profile
            else:
                # Esto es un caso crítico: el usuario existe en Auth pero no en nuestra tabla de perfiles.
                st.error("Login correcto, pero no se encontró un perfil de usuario asociado.")
                supabase.auth.sign_out() # Cerramos la sesión por seguridad
                return None

    except Exception as e:
        # Los errores de "Invalid login credentials" son capturados aquí
        st.error("Email o contraseña incorrectos.")
        return None
    
    return None