# Gestor de Facturas - Autonomos Espana

Aplicacion Streamlit para leer facturas PDF y XML Facturae,
extraer datos contables y exportarlos a Excel y PDF resumen.

---

## Instalacion rapida (en tu ordenador)

### 1. Instala Python 3.10 o superior
Descargalo en https://www.python.org/downloads/

### 2. Guarda los dos archivos en la misma carpeta
- app.py
- requirements.txt

### 3. Abre una terminal en esa carpeta y ejecuta

```
pip install -r requirements.txt
streamlit run app.py
```

Se abrira automaticamente tu navegador en http://localhost:8501

---

## Despliegue en Streamlit Cloud (gratis)

1. Crea una cuenta en https://share.streamlit.io
2. Sube los dos archivos a un repositorio de GitHub
3. En Streamlit Cloud haz clic en "New app"
4. Selecciona tu repositorio
5. En "Main file path" escribe exactamente: app.py
6. Haz clic en Deploy

---

## AVISO DE PRIVACIDAD

Las facturas contienen datos fiscales sensibles: NIF/CIF, importes, nombres de empresas y personas.

Si despliegas esta app en un servidor publico como Streamlit Cloud, cualquier persona con el enlace podra ver los archivos que subas.

Recomendacion: usa una instancia privada o comparte el enlace solo con personas de confianza.

---

## Como usar la app

1. Sube tus facturas en formato .pdf o .xml (Facturae)
2. Haz clic en "Procesar facturas"
3. Revisa y edita la tabla con los datos extraidos
4. Descarga el resultado en Excel o PDF resumen

---

## Columnas que extrae

| Columna | Descripcion |
|---|---|
| Tipo | Factura, Ticket, Factura simplificada, Recibo... |
| Fecha | Fecha de emision en formato dd/mm/aaaa |
| Num Factura | Numero o serie de la factura |
| Nombre Proveedor | Nombre del emisor o proveedor |
| NIF/CIF | Identificacion fiscal |
| Concepto | Categoria del gasto (Seguros, Software, Transporte...) |
| Direccion | Direccion del proveedor |
| CP / Pais | Codigo postal espanol o nombre del pais si es extranjero |
| Base Imponible | Importe antes de impuestos, para el Modelo 303 |
| Tipo IVA % | Porcentaje de IVA aplicado (21, 10, 4...) |
| Porcion IVA | Importe del IVA en euros |
| Tipo Retencion % | Porcentaje de retencion IRPF (7, 15...) |
| Porcion Retencion | Importe retenido en euros |
| Total | Importe total a pagar o cobrar |
| Validacion | OK si los importes cuadran, Revisar si hay diferencia |
| Error | Descripcion del error si no se pudo leer el archivo |

---

## Categorias de gasto disponibles

- Seguros
- Aplicaciones / Software
- Materiales
- Servicios profesionales
- Transporte
- Alojamiento
- Publicidad / Marketing
- Telecomunicaciones
- Suministros
- Formacion
- Gestoria / Asesoria
- Arrendamiento
- Equipos / Hardware
- Otros gastos

La app detecta la categoria automaticamente segun el texto de la factura.
Puedes cambiarla manualmente en la tabla editable.

---

## OCR para PDFs escaneados (opcional)

Si tus PDFs son imagenes escaneadas sin texto seleccionable, activa la opcion OCR en el panel lateral.

Necesitas instalar dependencias adicionales:

```
pip install pytesseract Pillow PyMuPDF
```

Y tambien instalar Tesseract en tu sistema:

Ubuntu o Debian:
```
sudo apt install tesseract-ocr tesseract-ocr-spa
```

macOS:
```
brew install tesseract tesseract-lang
```

Windows:
Descarga el instalador en https://github.com/UB-Mannheim/tesseract/wiki

---

## Formatos soportados

- .pdf con texto nativo
- .pdf escaneado con OCR activado (opcional)
- .xml en formato Facturae v3.2, v3.2.1 y v3.2.2

---

## Problemas frecuentes

No extrae datos de mi factura:
Abre el PDF y prueba a seleccionar texto con el cursor. Si no puedes seleccionar nada, es un PDF escaneado: activa la opcion OCR en el panel lateral.

La validacion dice Revisar:
Los importes no cuadran con una tolerancia de 0.03 euros. Revisa la factura manualmente o corrige los campos directamente en la tabla.

Error XML invalido:
El archivo XML puede no estar en formato Facturae o estar corrupto.

OCR no instalado:
Instala las dependencias opcionales descritas en la seccion OCR de este archivo.

---

## Archivos del proyecto

app.py             - Aplicacion completa en un solo archivo
requirements.txt   - Dependencias de Python
README.md          - Este archivo

---

Desarrollado con Python, Streamlit, pdfplumber, ReportLab y pandas.
