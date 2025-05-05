import streamlit as st
from functions import download_csv_from_drive, get_drive_service, parse_date
from icalendar import Calendar, Event
from datetime import datetime
import pytz
from io import BytesIO

# Configuración de la página
st.set_page_config(page_title="Progra a Calendario", page_icon="📅")

# Título y descripción
st.title("Programación a Calendario")
st.write("Genera un archivo .ics para importar la programación de vuelos en Google Calendar o Apple Calendar.")

# Selector de mes, año y tipo de servicio
st.subheader("Configurar programación")
meses = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]
mes_actual = meses[datetime.now().month - 1]
mes_seleccionado = st.selectbox("Selecciona un mes", meses, index=meses.index(mes_actual))
anio_seleccionado = st.number_input("Selecciona un año", min_value=2020, max_value=2030, value=datetime.now().year)
servicio_seleccionado = st.multiselect(
    "Selecciona tipos de servicio",
    options=["CO", "CC - C73", "CC - WEB", "LI", "SR - REF", "SR - OPC", "SA", "RM - QUIR", "RM - CMA"],
    default=["CO"]  # Por defecto, seleccionar CO
)

# Botón para generar el archivo .ics
if st.button("Generar archivo .ics"):
    try:
        folder_id = '1B8gnCmbBaGMBT77ba4ntjpZj_NkJcvuI'
        file_name = 'Consulta_de_servicios.csv'
        service = get_drive_service()
        df = download_csv_from_drive(service, folder_id, file_name)
        
        if df is None:
            st.error("No se encontró el archivo CSV en Google Drive.")
        else:
            # Filtrar por mes, año y servicios seleccionados
            mes_num = meses.index(mes_seleccionado) + 1
            df['parsed_date'] = df['Inicio'].apply(parse_date)
            df_filtered = df[
                (df['parsed_date'].dt.month == mes_num) &
                (df['parsed_date'].dt.year == anio_seleccionado) &
                (df['Servicio'].isin(servicio_seleccionado))
            ]
            
            if df_filtered.empty:
                st.warning("No se encontraron vuelos para los criterios seleccionados.")
            else:
                # Crear calendario
                cal = Calendar()
                cal.add('prodid', '-//Progra Pedrito//xAI//EN')
                cal.add('version', '2.0')
                
                # Zona horaria (ejemplo: Europe/Madrid)
                tz = pytz.timezone('Europe/Madrid')
                
                # Crear un evento por cada fila
                for _, row in df_filtered.iterrows():
                    event = Event()
                    inicio = parse_date(row['Inicio'])
                    fin = parse_date(row['Fin'])
                    
                    # Convertir a fechas con zona horaria
                    inicio_tz = tz.localize(inicio)
                    fin_tz = tz.localize(fin)
                    
                    # Configurar campos del evento
                    event.add('dtstart', inicio_tz)
                    event.add('dtend', fin_tz)
                    event.add('summary', f"{row['Servicio']} {row['Nº Vue.'] or ''} {row['Dep.']}-{row['Arr.']}")
                    event.add('location', f"{row['Dep.']}-{row['Arr.']}")
                    event.add('description', f"Servicio: {row['Servicio']}\nNúmero de vuelo: {row['Nº Vue.'] or 'N/A'}\nRuta: {row['Dep.']}-{row['Arr.']}")
                    event.add('uid', f"flight-{row['Inicio']}-{row['Dep.']}-{row['Arr.']}@prograpedrito")
                    
                    cal.add_component(event)
                
                # Generar el archivo .ics
                ics_buffer = BytesIO()
                ics_buffer.write(cal.to_ical())
                ics_buffer.seek(0)
                
                # Botón de descarga
                st.download_button(
                    label="Descargar archivo .ics",
                    data=ics_buffer,
                    file_name=f"Programacion_{mes_seleccionado}_{anio_seleccionado}.ics",
                    mime="text/calendar"
                )
                st.success("Archivo .ics generado con éxito. Descárgalo e impórtalo en tu calendario.")
    except Exception as e:
        st.error(f"Error al generar el archivo .ics: {str(e)}")
