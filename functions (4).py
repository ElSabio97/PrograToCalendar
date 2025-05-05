import streamlit as st
import pandas as pd
import requests
import json
from bs4 import BeautifulSoup
from io import StringIO, BytesIO
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# Definir los scopes necesarios
SCOPES = ['https://www.googleapis.com/auth/drive']

# URL del archivo airports.json en GitHub (reemplaza con tu URL real)
AIRPORTS_URL = "https://raw.githubusercontent.com/ElSabio97/Consulta-de-servicios/main/airports.json"

# Función para cargar los datos de aeropuertos desde GitHub
def load_airports_data():
    try:
        response = requests.get(AIRPORTS_URL)
        response.raise_for_status()  # Lanza una excepción si la solicitud falla
        airports_list = json.loads(response.text)
        # Convertir la lista en un diccionario para búsqueda rápida por IATA
        return {airport["IATA"]: airport["City"] for airport in airports_list}
    except requests.RequestException as e:
        st.error(f"Error al descargar airports.json: {str(e)}")
        return {}
    except json.JSONDecodeError as e:
        st.error(f"Error al parsear airports.json: {str(e)}")
        return {}

# Cargar los datos de aeropuertos al inicio (se almacena en memoria)
AIRPORTS = load_airports_data()

# Función para obtener el servicio de Google Drive
def get_drive_service():
    try:
        credentials_json = st.secrets["google_drive"]["credentials"]
        credentials_info = json.loads(credentials_json)
        credentials = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
        return build('drive', 'v3', credentials=credentials)
    except KeyError:
        st.error("Google Drive credentials not found.")
        raise
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON in credentials: {str(e)}")
        raise

# Función para procesar la tabla HTML y convertirla a CSV
def process_html_table(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    table = soup.find('table')
    if not table:
        raise ValueError("No se encontró una tabla válida en el HTML proporcionado.")
    df = pd.read_html(str(table))[0]
    if df.empty:
        raise ValueError("La tabla HTML no contiene datos válidos.")
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False, encoding='utf-8')
    return csv_buffer.getvalue()

# Función para descargar el CSV de Google Drive
def download_csv_from_drive(service, folder_id, file_name):
    query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    if not files:
        return None
    file_id = files[0]['id']
    request = service.files().get_media(fileId=file_id)
    file_buffer = BytesIO()
    downloader = request.execute()
    file_buffer.write(downloader)
    file_buffer.seek(0)
    try:
        return pd.read_csv(file_buffer, encoding='utf-8')
    except UnicodeDecodeError:
        file_buffer.seek(0)
        return pd.read_csv(file_buffer, encoding='latin1')

# Función para parsear fechas con múltiples formatos
def parse_date(date_str):
    date_str = str(date_str).replace(" (LT)", "").strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"No se pudo parsear la fecha: {date_str}")

# Función para actualizar el archivo CSV en Google Drive
def update_csv_in_drive(csv_data, folder_id, file_name):
    service = get_drive_service()
    try:
        new_df = pd.read_csv(StringIO(csv_data), encoding='utf-8')
    except UnicodeDecodeError:
        new_df = pd.read_csv(StringIO(csv_data), encoding='latin1')
    ref_date_str = new_df.iloc[0, 1]
    ref_date = parse_date(ref_date_str)
    existing_df = download_csv_from_drive(service, folder_id, file_name)
    if existing_df is not None:
        existing_df['parsed_date'] = existing_df.iloc[:, 1].apply(parse_date)
        filtered_df = existing_df[existing_df['parsed_date'] < ref_date].drop(columns=['parsed_date'])
        final_df = pd.concat([filtered_df, new_df], ignore_index=True)
    else:
        final_df = new_df
    csv_buffer = StringIO()
    final_df.to_csv(csv_buffer, index=False, encoding='utf-8')
    csv_data_final = csv_buffer.getvalue()
    query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    media = MediaIoBaseUpload(StringIO(csv_data_final), mimetype='text/csv')
    if files:
        file_id = files[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        service.files().create(body=file_metadata, media_body=media).execute()

# Función para generar el PDF detallado
def generate_pdf(df, mes, anio, mes_nombre):
    df['parsed_date'] = df['Inicio'].apply(parse_date)
    df_filtered = df[(df['parsed_date'].dt.month == mes) & (df['parsed_date'].dt.year == anio)]
    columns_to_keep = [col for col in df.columns if col not in ['Función', 'Flota', 'parsed_date']]
    df_filtered = df_filtered[columns_to_keep]
    
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    elements = []
    
    # Añadir título
    styles = getSampleStyleSheet()
    title = Paragraph(f"Programación de vuelos del mes de {mes_nombre}", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/><br/>", styles['Normal']))  # Espacio
    
    # Crear tabla
    data = [df_filtered.columns.tolist()] + df_filtered.values.tolist()
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    
    doc.build(elements)
    pdf_buffer.seek(0)
    return pdf_buffer

# Función para generar el PDF sencillo (solo CO)
def generate_filtered_pdf(df, mes, anio, mes_nombre):
    """
    Genera un PDF sencillo con Fecha, Ruta, Turno, agrupando vuelos por día y usando nombres de aeropuertos.
    """
    df['parsed_date'] = df['Inicio'].apply(parse_date)
    # Filtrar por mes, año y filas donde Servicio contiene "CO"
    df_filtered = df[
        (df['parsed_date'].dt.month == mes) & 
        (df['parsed_date'].dt.year == anio) & 
        (df['Servicio'].str.contains("CO", case=False, na=False))
    ]
    
    # Crear columnas personalizadas
    df_filtered = df_filtered.copy()
    df_filtered['Fecha'] = df_filtered['parsed_date'].dt.strftime("%d/%m/%Y")  # Solo fecha sin hora
    df_filtered['Ruta'] = df_filtered['Dep.'] + "-" + df_filtered['Arr.']
    df_filtered['Turno'] = df_filtered['parsed_date'].apply(
        lambda x: "Mañanas" if x.hour < 10 else "Tardes"
    )
    
    # Agrupar por fecha y procesar rutas y turnos
    def format_routes(routes):
        # Convertir las rutas en una lista de aeropuertos con nombres
        airports = []
        for route in routes:
            dep, arr = route.split("-")
            dep_name = AIRPORTS.get(dep, dep)  # Usar el nombre si existe, sino el código
            arr_name = AIRPORTS.get(arr, arr)
            airports.extend([dep_name, arr_name])
        # Eliminar duplicados consecutivos
        unique_route = [airports[0]]
        for airport in airports[1:]:
            if airport != unique_route[-1]:
                unique_route.append(airport)
        return " - ".join(unique_route)
    
    # Ordenar por fecha y hora para tomar el primer turno
    df_filtered = df_filtered.sort_values('parsed_date')
    df_grouped = df_filtered.groupby('Fecha').agg({
        'Ruta': format_routes,
        'Turno': 'first'  # Tomar solo el primer turno del día
    }).reset_index()
    
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    elements = []
    
    # Añadir título
    styles = getSampleStyleSheet()
    title = Paragraph(f"Programación de vuelos del mes de {mes_nombre}", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/><br/>", styles['Normal']))  # Espacio
    
    # Definir el ancho máximo de la tabla con márgenes
    page_width = letter[0]  # 612 puntos
    margin = 72  # 1 pulgada (72 puntos) de margen a cada lado
    table_width = page_width - 2 * margin  # 468 puntos
    
    # Definir anchos de columnas proporcionales
    col_widths = [table_width * 0.2, table_width * 0.6, table_width * 0.2]  # 20%, 60%, 20%
    
    # Crear tabla con ajuste de texto multilínea
    styles = getSampleStyleSheet()
    style_normal = styles['Normal']
    style_normal.fontSize = 10
    style_normal.alignment = 1  # Centrado

    # Convertir datos en una lista de listas con Paragraph para multilínea
    data = [['Fecha', 'Ruta', 'Turno']]  # Encabezados
    for row in df_grouped.values.tolist():
        fecha, ruta, turno = row
        data.append([
            Paragraph(str(fecha), style_normal),
            Paragraph(str(ruta), style_normal),  # Ruta como Paragraph para multilínea
            Paragraph(str(turno), style_normal)
        ])
    
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    # Asegurar que la tabla no exceda el ancho de la página
    table._argW = col_widths  # Forzar anchos de columna
    
    elements.append(table)
    doc.build(elements)
    pdf_buffer.seek(0)
    return pdf_buffer

# Función para actualizar CDU.csv
def update_cdu_csv(data, folder_id, file_name):
    service = get_drive_service()
    new_df = pd.DataFrame([data], columns=["DATE", "FLT NUM", "OUT", "OFF", "ON", "IN"])
    existing_df = download_csv_from_drive(service, folder_id, file_name)
    if existing_df is not None:
        existing_df = existing_df.reindex(columns=["DATE", "FLT NUM", "OUT", "OFF", "ON", "IN"])
        final_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        final_df = new_df
    csv_buffer = StringIO()
    final_df.to_csv(csv_buffer, index=False, encoding='utf-8')
    csv_data_final = csv_buffer.getvalue()
    query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])
    media = MediaIoBaseUpload(StringIO(csv_data_final), mimetype='text/csv')
    if files:
        file_id = files[0]['id']
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        service.files().create(body=file_metadata, media_body=media).execute()
