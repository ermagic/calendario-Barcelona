# Fichero: admin.py (Versión 3 - Interfaz Final Interactiva)
import streamlit as st
import pandas as pd
from database import supabase
from supabase import create_client, Client
from datetime import date, timedelta, datetime, time
import googlemaps
import itertools
import folium # Para el mapa
import smtplib # Para enviar correos
from email.mime.text import MIMEText # Para enviar correos

# --- CLIENTE ADMIN ---
def get_admin_client() -> Client:
    try:
        url = st.secrets["supabase"]["url"]
        service_key = st.secrets["supabase"]["service_key"]
        return create_client(url, service_key)
    except Exception:
        return None

# --- FUNCIÓN PARA ENVIAR EMAILS (TRAÍDA DESDE desplazamientos.py) ---
def send_email(recipients, subject, body):
    try:
        smtp_cfg = st.secrets["smtp"]
        sender, password = smtp_cfg["username"], smtp_cfg["password"]
        msg = MIMEText(body, 'html') # Usamos HTML para un formato más rico
        msg['From'], msg['To'], msg['Subject'] = sender, ", ".join(recipients), subject
        server = smtplib.SMTP(smtp_cfg["server"], smtp_cfg["port"])
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        st.success("✅ ¡Correo de notificación enviado con éxito!")
        return True
    except Exception as e: 
        st.error(f"Error al enviar el correo: {e}")
        return False

# --- LÓGICA DEL MOTOR DE PLANIFICACIÓN (EL CEREBRO - código anterior) ---
@st.cache_data(ttl=3600)
def get_distance_matrix(locations):
    try:
        gmaps = googlemaps.Client(key=st.secrets["google"]["api_key"])
        matrix = gmaps.distance_matrix(locations, locations, mode="driving")
        return matrix
    except Exception as e:
        st.error(f"Error al contactar con la API de Google Maps: {e}")
        return None

# ... (La función generate_optimal_plan se mantiene exactamente igual que en el paso anterior)
def generate_optimal_plan():
    """Función principal que orquesta la creación del plan para Martín."""
    with st.spinner("Analizando visitas y calculando rutas óptimas... Este proceso puede tardar un minuto."):
        # 1. DEFINIR LA SEMANA SIGUIENTE
        today = date.today()
        start_of_next_week = today + timedelta(days=-today.weekday(), weeks=1)
        end_of_next_week = start_of_next_week + timedelta(days=6)

        # 2. OBTENER VISITAS CANDIDATAS
        response = supabase.table('visitas').select('*, usuarios(nombre_completo)').eq(
            'status', 'Propuesta'
        ).gte('fecha', start_of_next_week).lte('fecha', end_of_next_week).execute()
        
        candidate_visits = response.data
        if not candidate_visits:
            st.warning("No hay visitas propuestas para la semana que viene. No se puede generar un plan.")
            return None

        df_visits = pd.DataFrame(candidate_visits)
        df_visits['nombre_coordinador'] = df_visits['usuarios'].apply(lambda x: x['nombre_completo'] if x else 'N/A')

        # 3. CONSTRUIR LA MATRIZ DE DISTANCIAS
        home_base = "Centro de Barcelona, Barcelona"
        unique_locations = list(df_visits['direccion_texto'].unique())
        all_locations = [home_base] + unique_locations
        
        dist_matrix = get_distance_matrix(all_locations)
        if not dist_matrix:
            st.error("No se pudo generar la matriz de distancias. El proceso se ha detenido.")
            return None

        # 4. SIMULAR LA MEJOR RUTA PARA CADA DÍA
        daily_results = []
        for i in range(5): # Lunes a Viernes
            day = start_of_next_week + timedelta(days=i)
            time_budget_seconds = (8 * 3600) if day.weekday() != 4 else (6 * 3600) # 8h o 6h para viernes
            
            best_route_for_day = []
            max_visits_for_day = 0

            day_visits = df_visits[pd.to_datetime(df_visits['fecha']).dt.date == day]
            if day_visits.empty:
                continue

            num_visits_to_permute = min(len(day_visits), 7)
            
            for p in itertools.permutations(day_visits.index, num_visits_to_permute):
                current_time = 0
                current_route = []
                
                first_visit_loc = day_visits.loc[p[0], 'direccion_texto']
                first_loc_index = all_locations.index(first_visit_loc)
                travel_to_first = dist_matrix['rows'][0]['elements'][first_loc_index]['duration']['value']
                current_time += travel_to_first

                for j in range(len(p)):
                    current_time += 45 * 60 # 45 minutos en sitio

                    travel_to_next = 0
                    if j < len(p) - 1:
                        loc_a = day_visits.loc[p[j], 'direccion_texto']
                        loc_b = day_visits.loc[p[j+1], 'direccion_texto']
                        idx_a = all_locations.index(loc_a)
                        idx_b = all_locations.index(loc_b)
                        travel_to_next = dist_matrix['rows'][idx_a]['elements'][idx_b]['duration']['value']
                        current_time += travel_to_next
                    
                    if current_time > time_budget_seconds:
                        break 
                    
                    current_route.append(day_visits.loc[p[j]].to_dict())

                if len(current_route) > max_visits_for_day:
                    last_visit_loc = current_route[-1]['direccion_texto']
                    last_loc_index = all_locations.index(last_visit_loc)
                    travel_from_last = dist_matrix['rows'][last_loc_index]['elements'][0]['duration']['value']
                    
                    if (current_time + travel_from_last) <= time_budget_seconds:
                        max_visits_for_day = len(current_route)
                        best_route_for_day = current_route

            if best_route_for_day:
                daily_results.append({ "day": day, "score": max_visits_for_day, "route": best_route_for_day })

        if not daily_results:
            st.warning("No se pudo encontrar ninguna ruta viable para ningún día.")
            return None
            
        sorted_days = sorted(daily_results, key=lambda x: x['score'], reverse=True)
        final_plan = sorted_days[:3]
        
        st.success("¡Propuesta de planificación generada!")
        return final_plan

# --- INTERFAZ DE STREAMLIT ---
def mostrar_panel_admin():
    st.header("Panel de Administración 👑")
    supabase_admin = get_admin_client()
    if not supabase or not supabase_admin:
        st.error("La conexión con la base de datos no está disponible."); st.stop()
    
    tab_users, tab_planner = st.tabs(["👥 Gestionar Usuarios", "🤖 Planificador Automático"])

    with tab_users:
        # ... (código de gestión de usuarios se mantiene igual)
        st.subheader("Gestión de Usuarios")
        # ...

    # --- PESTAÑA 2: PLANIFICADOR AUTOMÁTICO (CON LA NUEVA INTERFAZ) ---
    with tab_planner:
        st.subheader("Generador de Planificación para Martín")
        if st.button("🤖 Generar Nueva Planificación Óptima", type="primary"):
            st.session_state.generated_plan = generate_optimal_plan()
            st.session_state.plan_confirmed = False # Resetea el estado de confirmación
        
        st.markdown("---")

        if 'generated_plan' in st.session_state and st.session_state.generated_plan:
            plan = st.session_state.generated_plan
            
            # --- NOVEDAD: MOSTRAR MAPA CON RUTAS ---
            st.subheader("🗺️ Mapa de Rutas Propuestas")
            map_center = [41.3851, 2.1734] # Centro de Barcelona
            m = folium.Map(location=map_center, zoom_start=8)
            colors = ['blue', 'green', 'red']
            
            # --- Geocodificar ubicaciones para el mapa ---
            all_visit_locations = {visit['direccion_texto'] for day in plan for visit in day['route']}
            geolocator = googlemaps.Client(key=st.secrets["google"]["api_key"])
            locations_coords = {}
            for loc in all_visit_locations:
                try:
                    geocode_result = geolocator.geocode(loc)
                    if geocode_result:
                        lat = geocode_result[0]['geometry']['location']['lat']
                        lng = geocode_result[0]['geometry']['location']['lng']
                        locations_coords[loc] = (lat, lng)
                except Exception:
                    pass # Ignorar si una ubicación no se encuentra

            for i, day_plan in enumerate(plan):
                points = []
                for visit in day_plan['route']:
                    loc = visit['direccion_texto']
                    if loc in locations_coords:
                        points.append(locations_coords[loc])
                        folium.Marker(
                            location=locations_coords[loc],
                            popup=f"{loc}<br>Propuesto por: {visit['nombre_coordinador']}",
                            tooltip=loc,
                            icon=folium.Icon(color=colors[i], icon='user', prefix='fa')
                        ).add_to(m)
                if points:
                    folium.PolyLine(points, color=colors[i], weight=2.5, opacity=1).add_to(m)
            
            # st_folium(m, width=725, height=500) # Descomentar si tienes streamlit-folium

            # --- NOVEDAD: TABLERO KANBAN INTERACTIVO ---
            st.subheader("🗓️ Tablero de Planificación")
            cols = st.columns(len(plan))

            for i, day_plan in enumerate(plan):
                day_str = day_plan['day'].strftime('%A, %d de %B').capitalize()
                with cols[i]:
                    st.markdown(f"#### {day_str}")
                    st.markdown(f"**{day_plan['score']} visita(s)**")
                    
                    for visit_idx, visit in enumerate(day_plan['route']):
                        with st.container(border=True):
                            st.markdown(f"**📍 {visit['direccion_texto']}**")
                            st.caption(f"Propuesto por: {visit['nombre_coordinador']}")
                            
                            if st.button("🗑️ Quitar", key=f"del_{day_plan['day']}_{visit['id']}", help="Eliminar esta visita del plan de Martín"):
                                # Lógica para eliminar la visita del plan en session_state
                                st.session_state.generated_plan[i]['route'].pop(visit_idx)
                                st.rerun()
            
            st.markdown("---")

            # --- NOVEDAD: BOTONES DE CONFIRMACIÓN Y NOTIFICACIÓN ---
            if 'plan_confirmed' not in st.session_state:
                st.session_state.plan_confirmed = False

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Confirmar y Asignar Plan", type="primary", use_container_width=True, disabled=st.session_state.plan_confirmed):
                    with st.spinner("Confirmando y actualizando la base de datos..."):
                        # --- Lógica para actualizar Supabase ---
                        for day_plan in st.session_state.generated_plan:
                            current_time_dt = datetime.combine(day_plan['day'], time(8, 0)) # Hora de inicio
                            for visit in day_plan['route']:
                                supabase.table('visitas').update({
                                    'status': 'Asignada a Supervisor',
                                    'fecha_asignada': str(day_plan['day']),
                                    'hora_asignada': current_time_dt.strftime('%H:%M')
                                }).eq('id', visit['id']).execute()
                                # Aquí se podría añadir la lógica para insertar la copia para Martín
                                # y calcular los tiempos de viaje para la hora exacta, por simplicidad
                                # por ahora solo asignamos la hora de inicio de la jornada.
                        
                        st.session_state.plan_confirmed = True
                        st.success("¡Plan confirmado y asignado en la base de datos!")
                        st.rerun()

            with col2:
                if st.session_state.plan_confirmed:
                    if st.button("📧 Notificar a Coordinadores", use_container_width=True):
                        # --- Lógica para enviar email ---
                        res_users = supabase.table('usuarios').select('email').eq('rol', 'coordinador').execute()
                        coordinator_emails = [user['email'] for user in res_users.data]
                        
                        body = "<h3>Resumen de visitas asignadas a Martín</h3><p>¡Hola equipo! Martín se encargará de las siguientes visitas:</p><ul>"
                        for day_plan in st.session_state.generated_plan:
                             day_str = day_plan['day'].strftime('%A, %d/%m')
                             body += f"<li><b>{day_str}:</b></li><ul>"
                             for visit in day_plan['route']:
                                 body += f"<li>{visit['direccion_texto']} (de {visit['nombre_coordinador']})</li>"
                             body += "</ul>"
                        body += "</ul><p>Saludos,<br>Sistema de Planificación</p>"

                        send_email(coordinator_emails, f"Planificación de Martín - Semana {day_plan['day'].isocalendar()[1]}", body)