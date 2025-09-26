# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import googlemaps
import datetime as dt
import math
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import supabase # Importamos el cliente de Supabase

# --- INICIALIZACIÓN DE ESTADO (para este módulo) ---
def inicializar_estado_calculadora():
    """Inicializa las variables de sesión necesarias para la calculadora."""
    if 'calc_page' not in st.session_state: st.session_state.calc_page = 'calculator'
    if 'calculation_results' not in st.session_state: st.session_state.calculation_results = {}
    if 'gmaps_results' not in st.session_state: st.session_state.gmaps_results = None

# --- FUNCIONES DE LÓGICA ---
@st.cache_data
def cargar_datos_supabase():
    """Carga los datos de tiempos desde la tabla 'tiempos' de Supabase."""
    try:
        response = supabase.table('tiempos').select('*').execute()
        df = pd.DataFrame(response.data)
        if df.empty:
            st.error("Error: La tabla 'tiempos' de Supabase no devolvió datos.")
            return None
        df.rename(columns={
            'Poblacion_WFI': 'poblacion', 'Centro de Trabajo Nuevo': 'centro_trabajo',
            'Provincia Centro de Trabajo': 'provincia_ct', 'Distancia en Kms': 'distancia',
            'Tiempo(Min)': 'minutos_total', 'Tiempo a cargo de empresa(Min)': 'minutos_cargo'
        }, inplace=True)
        required_cols = ['poblacion', 'centro_trabajo', 'provincia_ct', 'distancia', 'minutos_total', 'minutos_cargo']
        if not all(col in df.columns for col in required_cols):
            st.error("Error Crítico: La tabla de Supabase no contiene todas las columnas necesarias.")
            return None
        df_clean = df[required_cols].dropna(subset=['poblacion', 'centro_trabajo', 'provincia_ct'])
        for col in ['poblacion', 'centro_trabajo', 'provincia_ct']:
            df_clean[col] = df_clean[col].str.strip()
        
        # --- LÍNEA CORREGIDA PARA LOS KM ---
        # Aseguramos que la columna 'distancia' se trate como texto para reemplazar comas
        # y luego se convierta a número de forma segura.
        df_clean['distancia'] = df_clean['distancia'].astype(str).str.replace(',', '.', regex=False)
        
        for col in ['distancia', 'minutos_total', 'minutos_cargo']:
            df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0)
            
        df_clean['minutos_total'] = df_clean['minutos_total'].astype(int)
        df_clean['minutos_cargo'] = df_clean['minutos_cargo'].astype(int)
        return df_clean
    except Exception as e:
        st.error(f"Error al conectar o procesar datos de Supabase: {e}")
        return None

@st.cache_data
def cargar_datos_empleados():
    """Carga los datos desde la tabla 'empleados' de Supabase."""
    try:
        response = supabase.table('empleados').select('*').execute()
        df = pd.DataFrame(response.data)
        if df.empty:
            st.error("Error: La tabla 'empleados' en Supabase está vacía o no se pudo cargar.")
            st.info("💡 Posible solución: Verifica que la 'Row Level Security (RLS)' esté desactivada para esta tabla en el panel de Supabase.")
            return None
        required_cols = ['PROVINCIA', 'EQUIPO', 'NOMBRE COMPLETO', 'EMAIL', 'PERSONAL']
        if not all(col in df.columns for col in required_cols):
            missing_cols = [col for col in required_cols if col not in df.columns]
            st.error(f"❌ Error en la tabla 'empleados' de Supabase: Faltan columnas: {missing_cols}")
            return None
        df_activos = df[df['PERSONAL'].str.lower() == 'activo'].copy()
        return df_activos
    except Exception as e: 
        st.error(f"Error al cargar los empleados desde Supabase. Error: {e}"); 
        return None

def calcular_minutos_con_limite(origen, destino, gmaps_client):
    try:
        directions_result = gmaps_client.directions(origen, destino, mode="driving", avoid="tolls")
        if not directions_result or not directions_result[0]['legs']: return None, None, "No se pudo encontrar una ruta."
        steps = directions_result[0]['legs'][0]['steps']
        total_capped_duration_seconds, total_distance_meters = 0, 0
        for step in steps:
            distancia_metros, duracion_google_seg = step['distance']['value'], step['duration']['value']
            total_distance_meters += distancia_metros
            theoretical_duration_90kmh_seg = (distancia_metros / 1000) / (90 / 3600) if distancia_metros > 0 else 0
            capped_duration_seg = max(duracion_google_seg, theoretical_duration_90kmh_seg)
            total_capped_duration_seconds += capped_duration_seg
        total_distancia_km = total_distance_meters / 1000
        total_minutos_final = math.ceil(total_capped_duration_seconds / 60)
        return total_distancia_km, total_minutos_final, None
    except googlemaps.exceptions.ApiError as e: return None, None, f"Error de la API de Google: {e}"
    except Exception as e: return None, None, f"Error inesperado: {e}"

def mostrar_horas_de_salida(total_minutos_desplazamiento):
    """
    Función MODIFICADA para la lógica de los viernes.
    """
    st.markdown("---"); st.subheader("🕒 Horas de Salida Sugeridas")
    dias_es = {"Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles", "Thursday": "Jueves", "Friday": "Viernes"}
    meses_es = {"January": "enero", "February": "febrero", "March": "marzo", "April": "abril", "May": "mayo", "June": "junio", "July": "julio", "August": "agosto", "September": "septiembre", "October": "octubre", "November": "noviembre", "December": "diciembre"}
    hoy = dt.date.today()
    dia_en, mes_en = hoy.strftime('%A'), hoy.strftime('%B')
    fecha_formateada = f"{dias_es.get(dia_en, dia_en)} {hoy.day} de {meses_es.get(mes_en, mes_en)}"
    st.session_state.calculation_results['fecha'] = fecha_formateada
    es_viernes = (hoy.weekday() == 4)
    
    # --- LÓGICA CORREGIDA PARA VIERNES ---
    if es_viernes:
        # Los viernes, ambos horarios salen a las 15:00
        horarios_base = {
            "Habitual Intensivo": dt.time(15, 0),
            "Normal": dt.time(15, 0)
        }
    else:
        horarios_base = {
            "Habitual Intensivo": dt.time(16, 0),
            "Normal": dt.time(17, 0)
        }
    
    tabla_rows = [f"| Horario | Hora Salida Habitual | Hora Salida Hoy ({fecha_formateada}) |", "|---|---|---|"]
    horas_salida_hoy = {}
    
    for nombre, hora_habitual in horarios_base.items():
        salida_dt_hoy = dt.datetime.combine(hoy, hora_habitual) - dt.timedelta(minutes=total_minutos_desplazamiento)
        hora_salida_str = salida_dt_hoy.strftime('%H:%M')
        horas_salida_hoy[nombre] = hora_salida_str
        tabla_rows.append(f"| **{nombre}** | {hora_habitual.strftime('%H:%M')} | **{hora_salida_str}** |")
        
    st.session_state.calculation_results['horas_salida'] = horas_salida_hoy
    st.markdown("\n".join(tabla_rows))


def send_email(recipients, subject, body):
    try:
        smtp_cfg = st.secrets["smtp"]
        sender, password = smtp_cfg["username"], smtp_cfg["password"]
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = sender, ", ".join(recipients), subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(smtp_cfg["server"], smtp_cfg["port"])
        server.starttls(); server.login(sender, password); server.send_message(msg); server.quit()
        st.success("✅ ¡Correo enviado con éxito!")
        return True
    except Exception as e: 
        st.error(f"Error al enviar el correo: {e}")
        st.info("Revisa la configuración en .streamlit/secrets.toml.")
        return False

# --- PÁGINA DE LA CALCULADORA ---
def pagina_calculadora():
    st.header("Calculadora de Tiempos y Notificaciones 🚗")
    df_tiempos = cargar_datos_supabase()
    def _cargo(minutos): return max(0, int(minutos) - 30)

    tab1, tab2 = st.tabs(["Cálculo oficial (desde Base de Datos)", "Cálculo informativo (con Google Maps)"])
    
    with tab1:
        st.subheader("Cálculo de tiempos desde la base de datos oficial")
        if df_tiempos is not None:
            provincias_ct = sorted(df_tiempos['provincia_ct'].unique())
            provincia_seleccionada = st.selectbox("1. Provincia del Centro de Trabajo:",provincias_ct, index=None, placeholder="Elige una provincia")
            if provincia_seleccionada:
                df_filtrado = df_tiempos[df_tiempos['provincia_ct'] == provincia_seleccionada]
                lista_poblaciones = sorted(df_filtrado['poblacion'].unique())
                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    mun_entrada = st.selectbox("2. Destino al inicio de jornada:", lista_poblaciones, index=None, placeholder="Selecciona población")
                    if mun_entrada:
                        info_entrada = df_filtrado[df_filtrado['poblacion'] == mun_entrada].iloc[0]
                        st.info(f"**Centro de Trabajo:** {info_entrada['centro_trabajo']}")
                with col2:
                    mun_salida = st.selectbox("3. Destino al final de jornada:", lista_poblaciones, index=None, placeholder="Selecciona población")
                    if mun_salida:
                        info_salida = df_filtrado[df_filtrado['poblacion'] == mun_salida].iloc[0]
                        st.info(f"**Centro de Trabajo:** {info_salida['centro_trabajo']}")
                if mun_entrada and mun_salida:
                    st.markdown("---")
                    datos_entrada = df_filtrado[df_filtrado['poblacion'] == mun_entrada].iloc[0]
                    datos_salida = df_filtrado[df_filtrado['poblacion'] == mun_salida].iloc[0]
                    min_total_entrada, dist_entrada, min_cargo_entrada = int(datos_entrada['minutos_total']), float(datos_entrada['distancia']), int(datos_entrada['minutos_cargo'])
                    min_total_salida, dist_salida, min_cargo_salida = int(datos_salida['minutos_total']), float(datos_salida['distancia']), int(datos_salida['minutos_cargo'])
                    st.session_state.calculation_results.update({
                        'aviso_pernocta': min_total_entrada > 80 or min_total_salida > 80, 'aviso_dieta': dist_entrada > 40 or dist_salida > 40,
                        'aviso_jornada': min_total_entrada > 60 or min_total_salida > 60, 'trayecto_entrada': f"De `{datos_entrada['centro_trabajo']}` a `{mun_entrada}`",
                        'trayecto_salida': f"De `{mun_salida}` a `{datos_salida['centro_trabajo']}`"
                    })
                    if st.session_state.calculation_results['aviso_pernocta']: st.warning("🛌 **Aviso Pernocta:** Trayecto supera 80 min.")
                    if st.session_state.calculation_results['aviso_dieta']: st.warning("⚠️ **Atención Media Dieta:** Trayecto supera 40km.")
                    if st.session_state.calculation_results['aviso_jornada']: st.warning("⏰ **Aviso Jornada:** Trayecto supera 60 min.")
                    st.markdown("---")
                    col_res1, col_res2 = st.columns(2)
                    with col_res1:
                        st.subheader("Viaje de Ida"); st.markdown(f"**{st.session_state.calculation_results['trayecto_entrada']}**"); st.metric("Distancia", f"{dist_entrada:.2f} km"); st.metric("Tiempo de viaje", f"{min_total_entrada} min"); st.metric("A cargo de empresa", f"{min_cargo_entrada} min")
                    with col_res2:
                        st.subheader("Viaje de Vuelta"); st.markdown(f"**{st.session_state.calculation_results['trayecto_salida']}**"); st.metric("Distancia", f"{dist_salida:.2f} km"); st.metric("Tiempo de viaje", f"{min_total_salida} min"); st.metric("A cargo de empresa", f"{min_cargo_salida} min")
                    st.markdown("---")
                    total_minutos_a_cargo = min_cargo_entrada + min_cargo_salida
                    st.success(f"**Tiempo total a restar de la jornada:** {total_minutos_a_cargo} minutos")
                    mostrar_horas_de_salida(total_minutos_a_cargo)
                    st.session_state.calculation_results['total_minutos'] = total_minutos_a_cargo
                    if st.button("📧 Enviar mail al equipo", key="btn_csv_mail"): st.session_state.calc_page = 'email_form'; st.rerun()
        else: st.warning("No se pudieron cargar los datos. La calculadora no puede funcionar.")

    with tab2:
        st.subheader("Cálculo por distancia (Reglas ponderadas)")
        try:
            gmaps = googlemaps.Client(key=st.secrets["google"]["api_key"])
        except Exception:
            st.error("Error: La clave de API de Google no está disponible."); st.stop()
        
        centros_map, lista_provincias_ct = {}, ["(Escribir dirección manual)"]
        if df_tiempos is not None:
            centros_df = df_tiempos[['provincia_ct', 'centro_trabajo']].drop_duplicates()
            centros_map = pd.Series(centros_df.centro_trabajo.values, index=centros_df.provincia_ct).to_dict()
            lista_provincias_ct.extend(sorted(centros_map.keys()))

        def update_field_from_select(field_key, select_key):
            provincia = st.session_state[select_key]
            if provincia in centros_map: st.session_state[field_key] = centros_map[provincia]
            st.session_state.gmaps_results = None
        
        if 'origen_ida' not in st.session_state: st.session_state.origen_ida = ""
        if 'destino_vuelta' not in st.session_state: st.session_state.destino_vuelta = ""

        col1_g, col2_g = st.columns(2)
        with col1_g:
            st.selectbox("Ayuda centro (Origen ida)", lista_provincias_ct, key='origen_ida_select', on_change=update_field_from_select, args=('origen_ida', 'origen_ida_select'))
            origen_ida = st.text_input("Origen (ida)", key="origen_ida", on_change=lambda: st.session_state.update(gmaps_results=None))
            destino_ida = st.text_input("Destino (ida)", key="destino_ida", on_change=lambda: st.session_state.update(gmaps_results=None))
        with col2_g:
            origen_vuelta = st.text_input("Origen (vuelta)", key="origen_vuelta", on_change=lambda: st.session_state.update(gmaps_results=None))
            st.selectbox("Ayuda centro (Destino vuelta)", lista_provincias_ct, key='destino_vuelta_select', on_change=update_field_from_select, args=('destino_vuelta', 'destino_vuelta_select'))
            destino_vuelta = st.text_input("Destino (vuelta)", key="destino_vuelta", on_change=lambda: st.session_state.update(gmaps_results=None))
        
        if st.button("Calcular Tiempo por Distancia", type="primary"):
            if all([origen_ida, destino_ida, origen_vuelta, destino_vuelta]):
                with st.spinner('Calculando...'):
                    dist_ida, min_ida, err_ida = calcular_minutos_con_limite(origen_ida, destino_ida, gmaps)
                    dist_vuelta, min_vuelta, err_vuelta = calcular_minutos_con_limite(origen_vuelta, destino_vuelta, gmaps)
                    if err_ida or err_vuelta:
                        if err_ida: st.error(f"Error ida: {err_ida}")
                        if err_vuelta: st.error(f"Error vuelta: {err_vuelta}")
                        st.session_state.gmaps_results = None
                    else:
                        st.session_state.gmaps_results = {"dist_ida": dist_ida, "min_ida": min_ida, "dist_vuelta": dist_vuelta, "min_vuelta": min_vuelta}
                        st.session_state.calculation_results.update({'trayecto_entrada': f"De `{origen_ida}` a `{destino_ida}`", 'trayecto_salida': f"De `{origen_vuelta}` a `{destino_vuelta}`"})
            else: st.warning("Por favor, rellene las cuatro direcciones."); st.session_state.gmaps_results = None
        
        if st.session_state.gmaps_results:
            res = st.session_state.gmaps_results
            es_identico = origen_ida.strip().lower() == destino_vuelta.strip().lower() and destino_ida.strip().lower() == origen_vuelta.strip().lower()
            if es_identico:
                dist, mins = (res['dist_ida'], res['min_ida']) if res['min_ida'] >= res['min_vuelta'] else (res['dist_vuelta'], res['min_vuelta'])
                st.session_state.calculation_results.update({'aviso_pernocta': mins > 80, 'aviso_dieta': dist > 40, 'aviso_jornada': mins > 60})
                if st.session_state.calculation_results['aviso_pernocta']: st.warning(f"🛌 **Aviso Pernocta:** Trayecto ({mins} min) supera 80 min.")
                if st.session_state.calculation_results['aviso_dieta']: st.warning(f"⚠️ **Atención Media Dieta:** Trayecto ({dist:.1f} km) supera 40km.")
                if st.session_state.calculation_results['aviso_jornada']: st.warning(f"⏰ **Aviso Jornada:** Trayecto ({mins} min) supera 60 min.")
                st.metric(f"TRAYECTO MÁS LARGO ({dist:.1f} km)", f"{_cargo(mins)} min a cargo", f"Tiempo total: {mins} min", delta_color="off")
                total_final = _cargo(mins) * 2
            else:
                st.session_state.calculation_results.update({'aviso_pernocta': res['min_ida'] > 80 or res['min_vuelta'] > 80, 'aviso_dieta': res['dist_ida'] > 40 or res['dist_vuelta'] > 40, 'aviso_jornada': res['min_ida'] > 60 or res['min_vuelta'] > 60})
                if st.session_state.calculation_results['aviso_pernocta']: st.warning("🛌 **Aviso Pernocta:** Trayecto supera 80 min.")
                if st.session_state.calculation_results['aviso_dieta']: st.warning("⚠️ **Atención Media Dieta:** Trayecto supera 40km.")
                if st.session_state.calculation_results['aviso_jornada']: st.warning("⏰ **Aviso Jornada:** Trayecto supera 60 min.")
                st.metric(f"IDA: {res['dist_ida']:.1f} km", f"{_cargo(res['min_ida'])} min a cargo", f"Tiempo total: {res['min_ida']} min", delta_color="off")
                st.metric(f"VUELTA: {res['dist_vuelta']:.1f} km", f"{_cargo(res['min_vuelta'])} min a cargo", f"Tiempo total: {res['min_vuelta']} min", delta_color="off")
                total_final = _cargo(res['min_ida']) + _cargo(res['min_vuelta'])
            st.markdown("---"); st.success(f"**Tiempo total a restar de la jornada:** {total_final} minutos"); mostrar_horas_de_salida(total_final)
            st.session_state.calculation_results['total_minutos'] = total_final
            if st.button("📧 Enviar mail al equipo", key="btn_gmaps_mail"): st.session_state.calc_page = 'email_form'; st.rerun()

# --- PÁGINA DE EMAIL ---
def pagina_email():
    st.header("📧 Redactar y Enviar Notificación")
    if st.button("⬅️ Volver a la calculadora"): st.session_state.calc_page = 'calculator'; st.rerun()
    st.markdown("---")
    employees_df = cargar_datos_empleados()
    if employees_df is None: st.warning("No se pudieron cargar datos de empleados."); return
        
    st.subheader("1. Filtrar y Seleccionar Destinatarios")
    col1, col2 = st.columns(2)
    with col1: provincia_sel = st.selectbox("Filtrar por Provincia:", employees_df['PROVINCIA'].unique())
    with col2:
        equipos_en_provincia = employees_df[employees_df['PROVINCIA'] == provincia_sel]['EQUIPO'].unique()
        equipo_sel = st.selectbox("Filtrar por Equipo:", equipos_en_provincia)
    personas_en_provincia = employees_df[employees_df['PROVINCIA'] == provincia_sel]
    personas_en_equipo = personas_en_provincia[personas_en_provincia['EQUIPO'] == equipo_sel]
    nombres_seleccionados = st.multiselect("Destinatarios:", options=personas_en_provincia['NOMBRE COMPLETO'].tolist(), default=personas_en_equipo['NOMBRE COMPLETO'].tolist())
    if not nombres_seleccionados: st.info("Selecciona al menos un destinatario."); st.stop()
    destinatarios_df = employees_df[employees_df['NOMBRE COMPLETO'].isin(nombres_seleccionados)]
    def crear_saludo(nombres):
        if not nombres: return "Hola,"
        nombres_cortos = [name.split()[0] for name in nombres]
        return f"Hola {nombres_cortos[0]}," if len(nombres_cortos) == 1 else f"Hola {', '.join(nombres_cortos[:-1])} y {nombres_cortos[-1]},"
    saludo = crear_saludo(nombres_seleccionados)
    with st.expander("Confirmar destinatarios y correos", expanded=True):
        if not destinatarios_df.empty: st.markdown("\n".join([f"- **{row['NOMBRE COMPLETO']}** ({row['EMAIL']})" for _, row in destinatarios_df.iterrows()]))
        else: st.write("No hay destinatarios.")
    
    tipo_mail = st.radio("Tipo de notificación:", ["Comunicar Horario de Salida", "Notificar Tipo de Jornada", "Informar de Pernocta"], horizontal=True)
    st.subheader("2. Revisa y Edita el Correo")
    res = st.session_state.calculation_results
    asunto_pred, cuerpo_pred = "", ""
    if tipo_mail == "Comunicar Horario de Salida":
        asunto_pred = f"Horario de salida para el {res.get('fecha', 'día de hoy')}"
        cuerpo_pred = f"{saludo}\n\nTe informo del horario de salida calculado para hoy, {res.get('fecha', '')}, será **{res.get('total_minutos', 0)} minutos** antes:\n\n- Salida en horario Intensivo: **{res.get('horas_salida', {}).get('Habitual Intensivo', 'N/A')}**\n- Salida en horario Normal: **{res.get('horas_salida', {}).get('Normal', 'N/A')}**\n\nTrayectos considerados:\n- Ida: {res.get('trayecto_entrada', 'No especificado')}\n- Vuelta: {res.get('trayecto_salida', 'No especificado')}\n\nSaludos,\n{st.session_state['nombre_completo']}"
    elif tipo_mail == "Notificar Tipo de Jornada":
        asunto_pred = f"Confirmación de jornada para el {res.get('fecha', 'día de hoy')}"
        cuerpo_pred = f"{saludo}\n\nDebido a los desplazamientos del día de hoy ({res.get('fecha', '')}), por favor, confirma el tipo de jornada a aplicar.\n\nRecuerda que los avisos generados han sido:\n- Media Dieta (>40km): **{'Sí' if res.get('aviso_dieta') else 'No'}**\n- Jornada Especial (>60min): **{'Sí' if res.get('aviso_jornada') else 'No'}**\n\nQuedo a la espera de tu confirmación.\n\nSaludos,\n{st.session_state['nombre_completo']}"
    elif tipo_mail == "Informar de Pernocta":
        asunto_pred = f"Aviso de posible pernocta - {res.get('fecha', 'día de hoy')}"
        cuerpo_pred = f"{saludo}\n\nEl cálculo de desplazamiento para hoy, {res.get('fecha', '')}, ha generado un aviso por superar los 80 minutos, lo que podría implicar una pernocta.\n\nPor favor, revisa la planificación y gestiona la reserva de hotel si es necesario.\n\nSaludos,\n{st.session_state['nombre_completo']}"
    
    asunto = st.text_input("Asunto:", asunto_pred)
    cuerpo = st.text_area("Cuerpo del Mensaje:", cuerpo_pred, height=300)
    st.markdown("---")
    
    if st.button("🚀 Enviar Email", type="primary"):
        send_email(destinatarios_df['EMAIL'].tolist(), asunto, cuerpo)

# --- FUNCIÓN PRINCIPAL DEL MÓDULO ---
def mostrar_calculadora_avanzada():
    """Esta es la función que se llamará desde la app principal."""
    inicializar_estado_calculadora()
    if st.session_state.calc_page == 'calculator':
        pagina_calculadora()
    elif st.session_state.calc_page == 'email_form':
        pagina_email()