# app.py — Lector de Facturas de Autónomos (España)
# Ejecutar con: streamlit run app.py

import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from dateutil import parser as dateparser

# ── ReportLab ──────────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import cm

# ── Configuración de página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Lector de Facturas · España",
    page_icon="🧾",
    layout="wide",
)

# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES GENERALES
# ══════════════════════════════════════════════════════════════════════════════

def parse_amount(text: str) -> float | None:
    """Convierte '1.234,56' o '1234.56' a float. Devuelve None si falla."""
    if not text:
        return None
    text = str(text).strip()
    # Formato español: puntos como miles, coma como decimal
    if re.search(r'\d\.\d{3},', text):
        text = text.replace('.', '').replace(',', '.')
    elif ',' in text and '.' not in text:
        text = text.replace(',', '.')
    elif ',' in text and '.' in text:
        # Último separador decide
        if text.rfind(',') > text.rfind('.'):
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    text = re.sub(r'[^\d.\-]', '', text)
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(text: str) -> str:
    """Devuelve 'dd/mm/aaaa' o '' si falla."""
    if not text:
        return ''
    try:
        dt = dateparser.parse(text, dayfirst=True)
        return dt.strftime('%d/%m/%Y') if dt else ''
    except Exception:
        return ''


def safe_float(val) -> float:
    """Convierte a float con seguridad."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def validate_invoice(row: dict) -> str:
    """Comprueba base + IVA - retención - descuento ≈ total (tolerancia 0.03€)."""
    base = safe_float(row.get('base_imponible'))
    cuota = safe_float(row.get('cuota_iva'))
    retencion = safe_float(row.get('importe_retencion'))
    descuento = safe_float(row.get('descuento'))
    total = safe_float(row.get('total'))
    if total == 0:
        return ''
    calculado = base + cuota - retencion - descuento
    return 'OK' if abs(calculado - total) <= 0.03 else 'Revisar'


# ══════════════════════════════════════════════════════════════════════════════
# PARSER PDF
# ══════════════════════════════════════════════════════════════════════════════

PATTERNS = {
    'fecha': [
        r'fecha[^:\n]*[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})',
        r'(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})',
    ],
    'numero': [
        r'n[uú]mero\s*(?:de\s*)?factura[^:\n]*[:\s]+([A-Z0-9\-/]+)',
        r'factura\s*n[uú]m\.?[^:\n]*[:\s]+([A-Z0-9\-/]+)',
        r'n\.?º?\s*factura[^:\n]*[:\s]+([A-Z0-9\-/]+)',
        r'invoice\s*n[o.]?[^:\n]*[:\s]+([A-Z0-9\-/]+)',
        r'^\s*([A-Z]{1,3}[\-/]?\d{4}[\-/]\d{3,6})\s*$',
        r'([A-Z]{0,3}\d{4,})',
    ],
    'nif': [
        r'(?:nif|cif|n\.i\.f|c\.i\.f)[:\s.]+([A-Z0-9]{7,11})',
        r'\b([A-Z]\d{7}[A-Z0-9])\b',
        r'\b(\d{8}[A-Z])\b',
    ],
    'base': [
        r'base\s*imponible[^:\n€$]*[:\s€$]+([\d.,]+)',
        r'base[^:\n€$]*[:\s€$]+([\d.,]+)',
        r'subtotal[^:\n€$]*[:\s€$]+([\d.,]+)',
    ],
    'pct_iva': [
        r'i\.?v\.?a\.?\s*[\(%]?\s*([\d,\.]+)\s*[\(%]',
        r'([\d,\.]+)\s*%\s*i\.?v\.?a',
        r'tipo\s*(?:de\s*)?i\.?v\.?a[^:\n]*[:\s]+([\d,\.]+)',
    ],
    'cuota_iva': [
        r'cuota\s*i\.?v\.?a[^:\n€$]*[:\s€$]+([\d.,]+)',
        r'i\.?v\.?a[^:\n€$%]*[:\s€$]+([\d.,]+)',
        r'importe\s*i\.?v\.?a[^:\n€$]*[:\s€$]+([\d.,]+)',
    ],
    'pct_retencion': [
        r'retenci[oó]n\s*[\(%]?\s*([\d,\.]+)\s*[\(%]',
        r'irpf\s*[\(%]?\s*([\d,\.]+)\s*[\(%]',
        r'([\d,\.]+)\s*%\s*(?:retenci[oó]n|irpf)',
    ],
    'importe_retencion': [
        r'retenci[oó]n[^:\n€$%]*[:\s€$]+([\d.,]+)',
        r'irpf[^:\n€$%]*[:\s€$]+([\d.,]+)',
    ],
    'total': [
        r'total\s*(?:a\s*pagar|factura|general|neto)?[^:\n€$]*[:\s€$]+([\d.,]+)',
        r'importe\s*total[^:\n€$]*[:\s€$]+([\d.,]+)',
        r'total\s*invoice[^:\n€$]*[:\s€$]+([\d.,]+)',
    ],
    'descuento': [
        r'descuento[^:\n€$%]*[:\s€$]+([\d.,]+)',
        r'dto\.?[^:\n€$%]*[:\s€$]+([\d.,]+)',
    ],
}


def extract_with_patterns(text: str, key: str) -> str:
    """Prueba múltiples regex para un campo y devuelve el primer match."""
    for pat in PATTERNS.get(key, []):
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return ''


def extract_counterpart_name(text: str, invoice_type: str) -> str:
    """Intenta extraer nombre de cliente o proveedor."""
    patterns_client = [
        r'cliente[^:\n]*[:\s]+([^\n]{3,60})',
        r'facturado\s*a[^:\n]*[:\s]+([^\n]{3,60})',
        r'bill\s*to[^:\n]*[:\s]+([^\n]{3,60})',
    ]
    patterns_prov = [
        r'proveedor[^:\n]*[:\s]+([^\n]{3,60})',
        r'emisor[^:\n]*[:\s]+([^\n]{3,60})',
        r'vendedor[^:\n]*[:\s]+([^\n]{3,60})',
    ]
    patterns = patterns_client if invoice_type in ('emitida', 'auto') else patterns_prov
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ''


def extract_text_pdfplumber(file_bytes: bytes) -> str:
    """Extrae texto de un PDF con pdfplumber."""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [p.extract_text() or '' for p in pdf.pages]
            return '\n'.join(pages)
    except Exception as e:
        return ''


def extract_text_ocr(file_bytes: bytes) -> str:
    """OCR opcional con pytesseract + PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        texts = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            texts.append(pytesseract.image_to_string(img, lang='spa+eng'))
        return '\n'.join(texts)
    except ImportError:
        return '__OCR_NOT_INSTALLED__'
    except Exception:
        return ''


def parse_pdf(file_bytes: bytes, filename: str, invoice_type: str, use_ocr: bool) -> dict:
    """Parsea un PDF y devuelve dict con los campos contables."""
    result = _empty_row(filename, invoice_type)
    ocr_warning = False

    text = extract_text_pdfplumber(file_bytes)
    if len(text.strip()) < 200 and use_ocr:
        ocr_text = extract_text_ocr(file_bytes)
        if ocr_text == '__OCR_NOT_INSTALLED__':
            ocr_warning = True
        elif ocr_text:
            text = ocr_text

    if len(text.strip()) < 10:
        result['error'] = 'PDF sin texto legible. Activa OCR o verifica el archivo.'
        return result

    text_lower = text.lower()

    raw_fecha = extract_with_patterns(text_lower, 'fecha') or extract_with_patterns(text, 'fecha')
    result['fecha_emision'] = parse_date(raw_fecha)
    result['numero_factura'] = extract_with_patterns(text, 'numero')
    result['nif_contraparte'] = extract_with_patterns(text, 'nif')
    result['nombre_contraparte'] = extract_counterpart_name(text, invoice_type)

    base_raw = extract_with_patterns(text_lower, 'base') or extract_with_patterns(text, 'base')
    result['base_imponible'] = parse_amount(base_raw)

    pct_iva_raw = extract_with_patterns(text_lower, 'pct_iva')
    result['pct_iva'] = parse_amount(pct_iva_raw)

    cuota_raw = extract_with_patterns(text_lower, 'cuota_iva') or extract_with_patterns(text, 'cuota_iva')
    result['cuota_iva'] = parse_amount(cuota_raw)

    pct_ret_raw = extract_with_patterns(text_lower, 'pct_retencion')
    result['pct_retencion'] = parse_amount(pct_ret_raw)

    ret_raw = extract_with_patterns(text_lower, 'importe_retencion') or extract_with_patterns(text, 'importe_retencion')
    result['importe_retencion'] = parse_amount(ret_raw)

    total_raw = extract_with_patterns(text_lower, 'total') or extract_with_patterns(text, 'total')
    result['total'] = parse_amount(total_raw)

    desc_raw = extract_with_patterns(text_lower, 'descuento')
    result['descuento'] = parse_amount(desc_raw)

    if ocr_warning:
        result['error'] = (result['error'] or '') + ' OCR no instalado; resultado sin OCR.'

    result['validacion'] = validate_invoice(result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PARSER XML FACTURAE
# ══════════════════════════════════════════════════════════════════════════════

FACTURAE_NS = [
    'http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xsd',
    'http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_1.xsd',
    'http://www.facturae.gob.es/formato/Versiones/Facturaev3_2.xsd',
    '',
]


def _xml_find(root: ET.Element, *paths) -> str:
    """Busca varios paths posibles (con y sin namespace) y devuelve el primero."""
    for ns in FACTURAE_NS:
        prefix = '{' + ns + '}' if ns else ''
        for path in paths:
            # Añadir prefijo a cada segmento
            ns_path = '/'.join(prefix + seg for seg in path.split('/'))
            el = root.find('.//' + ns_path)
            if el is not None and el.text:
                return el.text.strip()
    return ''


def parse_xml(file_bytes: bytes, filename: str, invoice_type: str) -> dict:
    """Parsea un XML Facturae y devuelve dict con campos contables."""
    result = _empty_row(filename, invoice_type)
    try:
        root = ET.fromstring(file_bytes)
    except ET.ParseError as e:
        result['error'] = f'XML inválido: {e}'
        return result

    # Fecha e identificación
    raw_fecha = _xml_find(root, 'IssueDate')
    result['fecha_emision'] = parse_date(raw_fecha)

    serie = _xml_find(root, 'InvoiceSeriesCode')
    numero = _xml_find(root, 'InvoiceNumber')
    result['numero_factura'] = f"{serie}-{numero}" if serie and numero else (numero or serie)

    # Contraparte según tipo
    if invoice_type in ('emitida', 'auto'):
        nif = _xml_find(root, 'BuyerParty/TaxIdentification/TaxIdentificationNumber')
        name = (_xml_find(root, 'BuyerParty/LegalEntity/CorporateName') or
                _xml_find(root, 'BuyerParty/Individual/Name'))
    else:
        nif = _xml_find(root, 'SellerParty/TaxIdentification/TaxIdentificationNumber')
        name = (_xml_find(root, 'SellerParty/LegalEntity/CorporateName') or
                _xml_find(root, 'SellerParty/Individual/Name'))

    result['nif_contraparte'] = nif
    result['nombre_contraparte'] = name

    # Importes globales
    total_raw = (_xml_find(root, 'InvoiceTotals/TotalGrossAmount') or
                 _xml_find(root, 'InvoiceTotals/TotalInvoiceAmount') or
                 _xml_find(root, 'TotalAmount'))
    result['total'] = parse_amount(total_raw)

    base_raw = (_xml_find(root, 'InvoiceTotals/TotalTaxableBase') or
                _xml_find(root, 'TaxableBaseAmount') or
                _xml_find(root, 'TaxableBaseTotalAmount'))
    result['base_imponible'] = parse_amount(base_raw)

    # IVA (primer bloque TaxRate / TaxAmount)
    pct_raw = _xml_find(root, 'Tax/TaxRate')
    result['pct_iva'] = parse_amount(pct_raw)

    cuota_raw = _xml_find(root, 'Tax/TaxAmount/TotalAmount')
    if not cuota_raw:
        cuota_raw = _xml_find(root, 'TaxAmount')
    result['cuota_iva'] = parse_amount(cuota_raw)

    # Retención / IRPF
    ret_pct = _xml_find(root, 'WithholdingTax/WithholdingTaxRate')
    result['pct_retencion'] = parse_amount(ret_pct)

    ret_imp = _xml_find(root, 'WithholdingTax/WithholdingTaxAmount/TotalAmount')
    result['importe_retencion'] = parse_amount(ret_imp)

    # Descuento global
    desc_raw = _xml_find(root, 'GeneralDiscounts/Discount/DiscountAmount/TotalAmount')
    result['descuento'] = parse_amount(desc_raw)

    result['validacion'] = validate_invoice(result)
    return result


def extract_iva_detail_xml(file_bytes: bytes, filename: str) -> list[dict]:
    """Extrae detalle de múltiples tramos IVA de un XML Facturae."""
    details = []
    try:
        root = ET.fromstring(file_bytes)
    except ET.ParseError:
        return details
    for ns in FACTURAE_NS:
        prefix = '{' + ns + '}' if ns else ''
        taxes = root.findall('.//' + prefix + 'Tax')
        if taxes:
            for tax in taxes:
                def tf(tag):
                    el = tax.find('.//' + prefix + tag)
                    return el.text.strip() if el is not None and el.text else ''
                details.append({
                    'archivo': filename,
                    'iva_porcentaje': parse_amount(tf('TaxRate')),
                    'base': parse_amount(tf('TaxableBase') or tf('TaxableBaseAmount')),
                    'cuota': parse_amount(tf('TaxAmount') or tf('TotalAmount')),
                    'raw_line': f"TaxRate={tf('TaxRate')} Base={tf('TaxableBase')} Cuota={tf('TaxAmount')}",
                })
            break
    return details


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

COLUMNS = [
    'archivo', 'tipo', 'fecha_emision', 'numero_factura', 'nombre_contraparte',
    'nif_contraparte', 'base_imponible', 'pct_iva', 'cuota_iva',
    'pct_retencion', 'importe_retencion', 'descuento', 'total',
    'validacion', 'error',
]

COLUMNS_DISPLAY = {
    'archivo': 'Archivo',
    'tipo': 'Tipo',
    'fecha_emision': 'Fecha',
    'numero_factura': 'Nº Factura',
    'nombre_contraparte': 'Contraparte',
    'nif_contraparte': 'NIF/CIF',
    'base_imponible': 'Base (€)',
    'pct_iva': 'IVA %',
    'cuota_iva': 'Cuota IVA (€)',
    'pct_retencion': 'Ret. %',
    'importe_retencion': 'Retención (€)',
    'descuento': 'Descuento (€)',
    'total': 'Total (€)',
    'validacion': 'Validación',
    'error': 'Error',
}


def _empty_row(filename: str, invoice_type: str) -> dict:
    row = {c: None for c in COLUMNS}
    row['archivo'] = filename
    row['tipo'] = invoice_type
    row['error'] = ''
    return row


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTACIÓN EXCEL
# ══════════════════════════════════════════════════════════════════════════════

def to_excel(df: pd.DataFrame, iva_details: list[dict]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_renamed = df.rename(columns=COLUMNS_DISPLAY)
        df_renamed.to_excel(writer, sheet_name='Facturas', index=False)

        # Autoajuste columnas
        ws = writer.sheets['Facturas']
        for col_cells in ws.columns:
            max_len = max((len(str(c.value or '')) for c in col_cells), default=8)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 2, 40)

        # Hoja detalle IVA si hay múltiples tramos
        if iva_details:
            df_iva = pd.DataFrame(iva_details)
            df_iva.to_excel(writer, sheet_name='DetalleIVA', index=False)

    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTACIÓN PDF RESUMEN
# ══════════════════════════════════════════════════════════════════════════════

PDF_COLS = ['archivo', 'tipo', 'fecha_emision', 'numero_factura', 'nombre_contraparte',
            'base_imponible', 'cuota_iva', 'importe_retencion', 'total', 'validacion', 'error']
PDF_HEADERS = ['Archivo', 'Tipo', 'Fecha', 'Nº Factura', 'Contraparte',
               'Base €', 'IVA €', 'Ret. €', 'Total €', 'Valid.', 'Error']


def _fmt(val) -> str:
    if val is None or val == '' or (isinstance(val, float) and pd.isna(val)):
        return ''
    if isinstance(val, float):
        return f"{val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    s = str(val)
    return s[:30] + '…' if len(s) > 30 else s


def to_pdf_summary(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1*cm, rightMargin=1*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )
    styles = getSampleStyleSheet()
    elements = []

    # Título
    elements.append(Paragraph("Resumen de Facturas", styles['Title']))
    elements.append(Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 0.4*cm))

    # Tabla
    table_data = [PDF_HEADERS]
    for _, row in df.iterrows():
        table_data.append([_fmt(row.get(c)) for c in PDF_COLS])

    col_widths = [3.5*cm, 1.8*cm, 2.2*cm, 3*cm, 4.5*cm,
                  2.2*cm, 2.0*cm, 2.0*cm, 2.2*cm, 1.5*cm, 3*cm]

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F3F4')]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#BDC3C7')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (5, 1), (8, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    # Colorear filas con "Revisar" o con error
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        if row.get('validacion') == 'Revisar':
            t.setStyle(TableStyle([('BACKGROUND', (9, i), (9, i), colors.HexColor('#FADBD8'))]))
        if row.get('error'):
            t.setStyle(TableStyle([('BACKGROUND', (10, i), (10, i), colors.HexColor('#FDEBD0'))]))

    elements.append(t)

    # Totales
    elements.append(Spacer(1, 0.5*cm))
    try:
        total_base = df['base_imponible'].apply(safe_float).sum()
        total_iva = df['cuota_iva'].apply(safe_float).sum()
        total_ret = df['importe_retencion'].apply(safe_float).sum()
        total_tot = df['total'].apply(safe_float).sum()
        resumen = (f"TOTALES → Base: {_fmt(total_base)} €  |  "
                   f"IVA: {_fmt(total_iva)} €  |  "
                   f"Retención: {_fmt(total_ret)} €  |  "
                   f"Total: {_fmt(total_tot)} €")
        elements.append(Paragraph(resumen, styles['Normal']))
    except Exception:
        pass

    doc.build(elements)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# INTERFAZ STREAMLIT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    st.title("🧾 Lector de Facturas de Autónomos · España")
    st.caption("Extrae datos contables de facturas PDF/XML y exporta a Excel o PDF resumen.")

    # Aviso de privacidad
    st.warning(
        "⚠️ **Privacidad:** Las facturas contienen datos fiscales sensibles (NIF, importes, etc.). "
        "Si usas una instancia pública de esta app, asegúrate de que el servidor es de confianza. "
        "Para uso profesional, despliégala de forma privada.",
        icon="🔒",
    )

    # ── Sidebar ─────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Configuración")
        invoice_type = st.selectbox(
            "Tipo de factura",
            options=['emitida', 'recibida', 'auto'],
            index=0,
            help="Emitida: tú eres el emisor. Recibida: tú eres el receptor. Auto: la app intenta deducirlo.",
        )
        use_ocr = st.checkbox(
            "Activar OCR si el PDF parece escaneado (opcional)",
            value=False,
            help="Requiere pytesseract, PyMuPDF y Tesseract instalados.",
        )
        st.divider()
        st.markdown("**Campos extraídos:**")
        st.markdown(
            "Fecha · Nº Factura · Contraparte · NIF/CIF · "
            "Base imponible · % IVA · Cuota IVA · "
            "% IRPF · Retención · Total · Descuento · Validación"
        )

    # ── Upload ───────────────────────────────────────────────────────────────
    uploaded_files = st.file_uploader(
        "Sube tus facturas (.pdf y/o .xml Facturae)",
        type=['pdf', 'xml'],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info("👆 Sube al menos un archivo PDF o XML Facturae para comenzar.")
        return

    # ── Procesar ─────────────────────────────────────────────────────────────
    if st.button("▶️ Procesar facturas", type="primary"):
        rows = []
        iva_details = []

        progress = st.progress(0, text="Procesando...")
        total_files = len(uploaded_files)

        for i, f in enumerate(uploaded_files):
            progress.progress((i + 1) / total_files, text=f"Procesando: {f.name}")
            file_bytes = f.read()
            ext = f.name.rsplit('.', 1)[-1].lower()

            if ext == 'pdf':
                row = parse_pdf(file_bytes, f.name, invoice_type, use_ocr)
            elif ext == 'xml':
                row = parse_xml(file_bytes, f.name, invoice_type)
                iva_details.extend(extract_iva_detail_xml(file_bytes, f.name))
            else:
                row = _empty_row(f.name, invoice_type)
                row['error'] = 'Formato no soportado.'

            rows.append(row)

        progress.empty()

        df = pd.DataFrame(rows, columns=COLUMNS)
        st.session_state['df'] = df
        st.session_state['iva_details'] = iva_details
        st.success(f"✅ {total_files} archivo(s) procesado(s).")

    # ── Mostrar tabla editable ────────────────────────────────────────────────
    if 'df' in st.session_state:
        df = st.session_state['df']
        iva_details = st.session_state.get('iva_details', [])

        st.subheader("📋 Datos extraídos (edita si es necesario)")

        # Métricas rápidas
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Facturas", len(df))
        col2.metric("Base total (€)", f"{df['base_imponible'].apply(safe_float).sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
        col3.metric("IVA total (€)", f"{df['cuota_iva'].apply(safe_float).sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
        col4.metric("Total (€)", f"{df['total'].apply(safe_float).sum():,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))

        # Tabla editable
        edited_df = st.data_editor(
            df,
            column_config={
                'archivo': st.column_config.TextColumn('Archivo', disabled=True),
                'tipo': st.column_config.SelectboxColumn('Tipo', options=['emitida', 'recibida', 'auto']),
                'fecha_emision': st.column_config.TextColumn('Fecha'),
                'numero_factura': st.column_config.TextColumn('Nº Factura'),
                'nombre_contraparte': st.column_config.TextColumn('Contraparte'),
                'nif_contraparte': st.column_config.TextColumn('NIF/CIF'),
                'base_imponible': st.column_config.NumberColumn('Base (€)', format="%.2f"),
                'pct_iva': st.column_config.NumberColumn('IVA %', format="%.1f"),
                'cuota_iva': st.column_config.NumberColumn('Cuota IVA (€)', format="%.2f"),
                'pct_retencion': st.column_config.NumberColumn('Ret. %', format="%.1f"),
                'importe_retencion': st.column_config.NumberColumn('Ret. (€)', format="%.2f"),
                'descuento': st.column_config.NumberColumn('Dto. (€)', format="%.2f"),
                'total': st.column_config.NumberColumn('Total (€)', format="%.2f"),
                'validacion': st.column_config.TextColumn('Valid.', disabled=True),
                'error': st.column_config.TextColumn('Error', disabled=True),
            },
            use_container_width=True,
            num_rows="dynamic",
            key='editor',
        )

        # Recalcular validación tras edición
        for idx, row in edited_df.iterrows():
            edited_df.at[idx, 'validacion'] = validate_invoice(row.to_dict())

        # Alertas de validación
        revisiones = edited_df[edited_df['validacion'] == 'Revisar']
        errores = edited_df[edited_df['error'].astype(str).str.len() > 0]
        if not revisiones.empty:
            st.warning(f"⚠️ {len(revisiones)} factura(s) con discrepancias en importes (columna 'Validación': Revisar).")
        if not errores.empty:
            st.error(f"❌ {len(errores)} archivo(s) con errores de parseo.")

        # Detalle IVA
        if iva_details:
            with st.expander(f"🔍 Detalle de tramos IVA ({len(iva_details)} registros)"):
                st.dataframe(pd.DataFrame(iva_details), use_container_width=True)

        st.divider()
        st.subheader("⬇️ Exportar")

        col_a, col_b = st.columns(2)

        with col_a:
            try:
                excel_bytes = to_excel(edited_df, iva_details)
                st.download_button(
                    label="📊 Descargar Excel (.xlsx)",
                    data=excel_bytes,
                    file_name=f"facturas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Error generando Excel: {e}")

        with col_b:
            try:
                pdf_bytes = to_pdf_summary(edited_df)
                st.download_button(
                    label="📄 Descargar PDF resumen",
                    data=pdf_bytes,
                    file_name=f"resumen_facturas_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime='application/pdf',
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Error generando PDF: {e}")


if __name__ == '__main__':
    main()
