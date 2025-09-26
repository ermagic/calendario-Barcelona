# Fichero: planificador.py (Versión 2 - Planificación Semanal)
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
from streamlit_calendar import calendar
from database import supabase # Importamos el cliente de Supabase

# --- FUNCIÓN AUXILIAR PARA MAPEAR FRANJAS A HORAS CONCRETAS ---
def map_franja_to_time(fecha, franja):
    fecha_dt = pd.to_datetime(fecha).date()
    
    if franja == "Jornada Mañana (8-14h)":
        start_time, end_time = datetime.combine(fecha_dt, datetime.min.time()), datetime.combine(fecha_dt, datetime.max.time())
    elif franja == "Jornada Tarde (15-17h)":
        start_time, end_time = datetime.combine(fecha_dt, datetime.min.time()), datetime.combine(fecha_dt, datetime.max.time())
    else: # Default o si hay otros valores
        start_time, end_time = datetime.combine(fecha_dt, datetime.min.time()), datetime.combine(fecha_dt, datetime.max.time())
        
    return start_time.isoformat(), end_time.isoformat()

def mostrar_planificador():
    st.header("Planificador de Visitas 🗓️")
    
    if not supabase:
        st.error("La conexión con la base de datos no está disponible.")
        st.stop()

    # --- LECTURA DE DATOS GENERALES ---
    users_response = supabase.table('usuarios').select('id, nombre_completo').execute()
    users_df = pd.DataFrame(users_response.data)
    
    # --- COMIENZO DE LA LÓGICA DE PLANIFICACIÓN SEMANAL ---
    # 1. Obtenemos el número de la semana siguiente
    hoy = date.today()
    proxima_semana_fecha = hoy + timedelta(days=7)
    año_siguiente, semana_siguiente, _ = proxima_semana_fecha.isocalendar()

    st.info(f"Actualmente planificando la **Semana {semana_siguiente}** (del año {año_siguiente}).")

    # 2. Comprobamos si la planificación para la semana que viene ya está finalizada
    planificacion_response = supabase.table('planificaciones_semanales').select('*').eq(
        'usuario_id', st.session_state['usuario_id']
    ).eq('numero_semana', semana_siguiente).eq('año', año_siguiente).execute()
    
    planificacion_finalizada = bool(planificacion_response.data and planificacion_response.data[0]['status_planificacion'] == 'Finalizada')

    # --- PESTAÑAS DE VISUALIZACIÓN ---
    tab_planificar, tab_calendario, tab_gestion = st.tabs(["✍️ Planificar Mi Semana", "📅 Calendario Global", "👀 Mis Próximas Visitas"])

    # --- PESTAÑA 1: PLANIFICAR MI SEMANA (LA GRAN NOVEDAD) ---
    with tab_planificar:
        st.subheader(f"Planificación para la Semana {semana_siguiente}")

        if planificacion_finalizada:
            st.success("✅ Tu planificación para la semana que viene ya está finalizada y enviada.")
            st.info("Si necesitas hacer cambios, contacta con el supervisor. Las visitas asignadas a Martín aparecerán en la pestaña 'Mis Próximas Visitas'.")
        else:
            # Cargamos las visitas 'Propuesta' para la semana que viene
            mis_visitas_propuestas_res = supabase.table('visitas').select('*').eq(
                'usuario_id', st.session_state['usuario_id']
            ).eq('status', 'Propuesta').execute()
            
            df_propuestas = pd.DataFrame(mis_visitas_propuestas_res.data)

            # Usamos st.data_editor para una experiencia de edición tipo Excel
            st.write("Añade o edita tus visitas para la próxima semana. Haz clic en el '+' para añadir nuevas filas.")
            
            # --- NOVEDAD: Usamos un DataFrame en blanco si no hay datos ---
            if df_propuestas.empty:
                df_para_editar = pd.DataFrame(columns=['fecha', 'direccion_texto', 'observaciones'])
            else:
                # Nos aseguramos de que las columnas que queremos editar existan
                df_para_editar = df_propuestas[['fecha', 'direccion_texto', 'observaciones']]

            edited_df = st.data_editor(
                df_para_editar,
                num_rows="dynamic",
                column_config={
                    "fecha": st.column_config.DateColumn(
                        "Fecha Visita",
                        required=True,
                    ),
                    "direccion_texto": st.column_config.TextColumn(
                        "Ciudad / Ubicación",
                        required=True,
                    ),
                    "observaciones": st.column_config.TextColumn(
                        "Observaciones",
                    )
                },
                key="editor_visitas"
            )

            st.markdown("---")
            if st.button("💾 Guardar y Finalizar Planificación", type="primary", use_container_width=True):
                with st.spinner("Procesando y guardando..."):
                    # Borramos las propuestas anteriores para evitar duplicados
                    supabase.table('visitas').delete().eq(
                        'usuario_id', st.session_state['usuario_id']
                    ).eq('status', 'Propuesta').execute()
                    
                    # Insertamos las nuevas visitas del editor
                    nuevas_visitas = []
                    for index, row in edited_df.iterrows():
                        if row['direccion_texto'] and row['fecha']: # Solo guardar si tiene datos básicos
                             nuevas_visitas.append({
                                'usuario_id': st.session_state['usuario_id'],
                                'direccion_texto': row['direccion_texto'],
                                'fecha': str(row['fecha']),
                                'observaciones': row['observaciones'],
                                'status': 'Propuesta' # Estado por defecto
                            })
                    
                    if nuevas_visitas:
                        supabase.table('visitas').insert(nuevas_visitas).execute()

                    # Marcamos la planificación como 'Finalizada'
                    supabase.table('planificaciones_semanales').upsert({
                        'usuario_id': st.session_state['usuario_id'],
                        'numero_semana': semana_siguiente,
                        'año': año_siguiente,
                        'status_planificacion': 'Finalizada'
                    }).execute()
                    
                    st.success("¡Planificación guardada y finalizada con éxito!")
                    st.rerun()

    # --- PESTAÑA 2: CALENDARIO GLOBAL (CON MEJORAS VISUALES) ---
    with tab_calendario:
        st.subheader("Calendario de Visitas Global")
        
        # Leemos todas las visitas para el calendario
        all_visits_response = supabase.table('visitas').select('*, usuarios(nombre_completo)').execute()
        all_visits_df = pd.DataFrame(all_visits_response.data)

        calendar_events = []
        if not all_visits_df.empty:
            # Aplanamos el resultado de la relación con usuarios
            all_visits_df['nombre_completo'] = all_visits_df['usuarios'].apply(lambda x: x['nombre_completo'] if isinstance(x, dict) else 'N/A')
            all_visits_df.drop(columns=['usuarios'], inplace=True)

            for _, row in all_visits_df.iterrows():
                # --- NOVEDAD: Colores según el estado de la visita ---
                color = "gray" # Default
                if row['status'] == 'Propuesta':
                    color = "blue"
                elif row['status'] == 'Asignada a Supervisor':
                    color = "green"
                elif row['status'] == 'Cancelada':
                    color = "red"
                
                # --- NOVEDAD: Icono para las visitas de Martín ---
                title = f"{row['nombre_completo']} - {row['direccion_texto']}"
                if row['nombre_completo'] == "Martín": # Asumiendo que el nombre de Martín en la BD es "Martín"
                    title = f"👮 {title}"

                start_time, end_time = map_franja_to_time(row['fecha'], "Jornada Mañana (8-14h)") # Se puede ajustar si se usa hora exacta
                
                calendar_events.append({
                    "title": title,
                    "start": start_time,
                    "end": end_time,
                    "color": color,
                })
        
        calendar_options = {
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,timeGridWeek,listWeek"},
            "initialView": "dayGridMonth", "locale": "es",
        }
        
        calendar(events=calendar_events, options=calendar_options)

    # --- PESTAÑA 3: GESTIONAR MIS VISITAS (AHORA "MIS PRÓXIMAS VISITAS") ---
    with tab_gestion:
        st.subheader("Resumen de Mis Próximas Visitas")
        
        # Leemos todas las visitas futuras del usuario, sin importar el estado
        my_visits_res = supabase.table('visitas').select('*').eq(
            'usuario_id', st.session_state['usuario_id']
        ).gte('fecha', date.today().isoformat()).execute()

        my_visits_df = pd.DataFrame(my_visits_res.data).sort_values(by='fecha')

        if my_visits_df.empty:
            st.info("No tienes ninguna visita futura programada.")
        else:
            for _, visit in my_visits_df.iterrows():
                with st.container(border=True):
                    # --- NOVEDAD: Lógica para mostrar visitas reasignadas ---
                    if visit['status'] == 'Asignada a Supervisor':
                        st.warning(f"Visita a **{visit['direccion_texto']}** reasignada a Martín.", icon="👮")
                        nueva_fecha = datetime.fromisoformat(visit['fecha_asignada']).strftime('%d/%m/%Y') if visit.get('fecha_asignada') else "N/A"
                        nueva_hora = visit.get('hora_asignada', "N/A")
                        st.markdown(f"**Nueva Fecha y Hora:** {nueva_fecha} a las {nueva_hora}")
                        st.caption("Esta visita ha sido bloqueada y no requiere acción por tu parte.")

                    elif visit['status'] == 'Propuesta':
                        fecha_formateada = datetime.fromisoformat(visit['fecha']).strftime('%d/%m/%Y')
                        st.info(f"**{fecha_formateada}** - Visita propuesta a **{visit['direccion_texto']}**", icon="✍️")
                        if visit.get('observaciones'):
                            st.caption(f"Observaciones: {visit['observaciones']}")
                        st.caption("Esta visita está pendiente de la planificación final del supervisor.")
                    
                    # Aquí se podrían añadir otros estados como 'Confirmada', etc.