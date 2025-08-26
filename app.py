import streamlit as st
import pandas as pd
from datetime import date
from calendar import month_name
from db import (
    init_db, ensure_employees, list_employees, add_employee, set_employee_active,
    create_request, list_requests, update_status, delete_request,
    has_overlap_for_employee, get_calendar_matrix
)

# ---------- Inicialización ----------
st.set_page_config(page_title="Vacaciones por Mes", page_icon="📆", layout="wide")
init_db()
# Si quieres precargar empleados, añade sus nombres aquí:
ensure_employees(["JUANRA TORNER", "ANDRES MARTINI", "PEDRO MARZO", "CARLOS SALCEDO",
                  "JUAN RUIZ", "CLAUDIU SEMENIUC", "OSCAR HERNANDEZ", "CARLOS GALVEZ"])

# ---------- Autenticación (opcional con secrets) ----------
def get_auth():
    # Si configuras .streamlit/secrets.toml con usuarios, úsalo. Si no, modo simple.
    if "credentials" in st.secrets:
        import streamlit_authenticator as stauth
        creds = st.secrets["credentials"]
        cookie = st.secrets.get("cookie", {})
        preauth = st.secrets.get("preauthorized", {})
        authenticator = stauth.Authenticate(
            creds, cookie.get("name","vacaciones_cookie"),
            cookie.get("key","supersecret"), cookie.get("expiry_days", 7),
            preauth
        )
        name, auth_status, username = authenticator.login("Iniciar sesión", "sidebar")
        if auth_status:
            role = creds["usernames"][username].get("role", "empleado")
            return {"name": name, "username": username, "role": role, "logout": authenticator.logout}
        elif auth_status is False:
            st.sidebar.error("Usuario o contraseña incorrectos")
        else:
            st.sidebar.info("Introduce tus credenciales")
        return None
    else:
        # Modo simple sin contraseña
        st.sidebar.info("Modo sin autenticación (configura secrets para login real).")
        role = st.sidebar.selectbox("Rol", ["empleado", "responsable"])
        emp_names = list_employees()
        default_emp = emp_names[0] if emp_names else "Empleado"
        user = st.sidebar.selectbox("Empleado", [default_emp] + [e for e in emp_names if e != default_emp])
        return {"name": user, "username": user, "role": role, "logout": None}

auth = get_auth()
if not auth:
    st.stop()

# ---------- Sidebar: selección de mes/año ----------
today = date.today()
col1, col2 = st.sidebar.columns(2)
year = col1.number_input("Año", min_value=2020, max_value=2100, value=today.year, step=1)
month = col2.number_input("Mes", min_value=1, max_value=12, value=today.month, step=1)
st.sidebar.caption(f"Mostrando: {month_name[month]} {year}")

# ---------- Sección: gestión de empleados (solo responsable) ----------
with st.sidebar.expander("Gestión de empleados"):
    if auth["role"] == "responsable":
        new_emp = st.text_input("Añadir empleado")
        if st.button("Añadir", use_container_width=True, type="secondary") and new_emp.strip():
            add_employee(new_emp.strip().upper())
            st.success(f"Empleado añadido: {new_emp.strip().upper()}")
    emps = list_employees(active_only=False)
    if emps:
        emp_to_toggle = st.selectbox("Activar/Desactivar", emps)
        active = st.toggle("Activo", value=True, key=f"active_{emp_to_toggle}")
        if st.button("Guardar estado", use_container_width=True):
            set_employee_active(emp_to_toggle, active)
            st.success("Actualizado")

# ---------- Título ----------
st.title("📆 Calendario de Vacaciones por Mes")

# ---------- Formulario de solicitud (empleado) ----------
if auth["role"] == "empleado":
    with st.container():
        st.subheader("Solicitar vacaciones")
        with st.form(key="solicitud_vacaciones"):
            employee = st.text_input("Empleado", value=auth["name"]).upper()
            date_range = st.date_input("Rango de fechas", value=(today, today))
            note = st.text_area("Notas (opcional)", placeholder="Motivo, comentarios, etc.")
            submitted = st.form_submit_button("Enviar solicitud")
            if submitted:
                if not isinstance(date_range, tuple) or len(date_range) != 2:
                    st.error("Selecciona un rango de fechas válido.")
                else:
                    d0, d1 = sorted(date_range)
                    if has_overlap_for_employee(employee, d0, d1, include_pending=True):
                        st.warning("Ya tienes solicitudes aprobadas/pendientes que se solapan con esas fechas.")
                    create_request(employee, d0, d1, note)
                    st.success("Solicitud enviada y marcada como pendiente.")

# ---------- Panel de aprobaciones (responsable) ----------
if auth["role"] == "responsable":
    st.subheader("Aprobaciones pendientes")
    pending = list_requests(status="pendiente")
    if not pending:
        st.info("No hay solicitudes pendientes.")
    else:
        for r in pending:
            with st.container():
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
                c1.write(f"ID: {r['id']}")
                c2.write(f"Empleado: {r['employee']}")
                c3.write(f"Desde: {r['start_date']} → Hasta: {r['end_date']}")
                c4.write(r.get("note") or "")
                approve = c5.button("Aprobar", key=f"a_{r['id']}")
                reject = c5.button("Rechazar", key=f"r_{r['id']}")
                if approve:
                    update_status(r["id"], "aprobada", approver=auth["name"])
                    st.success(f"Solicitud {r['id']} aprobada")
                    st.experimental_rerun()
                if reject:
                    update_status(r["id"], "rechazada", approver=auth["name"])
                    st.warning(f"Solicitud {r['id']} rechazada")
                    st.experimental_rerun()

# ---------- Solicitudes propias (empleado) ----------
if auth["role"] == "empleado":
    st.subheader("Mis solicitudes")
    mine = [r for r in list_requests() if r["employee"] == auth["name"].upper()]
    if not mine:
        st.info("Aún no has creado solicitudes.")
    else:
        for r in mine:
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 2, 2])
            c1.write(f"#{r['id']}")
            c2.write(f"{r['start_date']} → {r['end_date']}")
            c3.write(f"Estado: {r['status']}")
            c4.write(r.get("note") or "")
            if r["status"] == "pendiente":
                if c5.button("Cancelar", key=f"del_{r['id']}"):
                    delete_request(r["id"], employee=auth["name"].upper())
                    st.info("Solicitud cancelada")
                    st.experimental_rerun()

# ---------- Calendario mensual ----------
st.subheader(f"Calendario mensual: {month_name[month]} {year}")

matrix, days_in_month = get_calendar_matrix(year, month)
# Construimos DataFrame para mostrar colores
df = pd.DataFrame({d: "" for d in range(1, days_in_month + 1)}, index=matrix.keys())
for emp, days_map in matrix.items():
    for d, status in days_map.items():
        if status == "aprobada":
            df.loc[emp, d] = "A"
        elif status == "pendiente":
            df.loc[emp, d] = "P"
        elif status == "rechazada":
            df.loc[emp, d] = "R"
        else:
            df.loc[emp, d] = ""

def colorize(val):
    colors = {
        "A": "background-color: #2ecc71; color: white;",      # Verde aprobado
        "P": "background-color: #f1c40f; color: black;",      # Amarillo pendiente
        "R": "background-color: #e74c3c; color: white;",      # Rojo rechazado
        "": ""
    }
    return colors.get(val, "")

styled = df.style.applymap(colorize)
st.caption("Leyenda: A=Aprobada, P=Pendiente, R=Rechazada")
st.table(styled)

# ---------- Exportaciones ----------
with st.expander("Exportar datos"):
    export_month = st.button("Exportar mes a CSV")
    if export_month:
        csv = df.to_csv(index=True).encode("utf-8")
        st.download_button("Descargar CSV", data=csv, file_name=f"vacaciones_{year}_{month:02d}.csv", mime="text/csv")

# ---------- Cierre de sesión (si aplica) ----------
if auth.get("logout"):
    auth["logout"]("Cerrar sesión", "sidebar")