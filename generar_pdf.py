# generar_pdf.py
# Convierte Markdown a PDF con estilo profesional (visual del documento definitivo)
# Usa weasyprint para renderizado CSS completo.

import os
import markdown
from weasyprint import HTML

# Hoja de estilos CSS que replica la estética del PDF definitivo
CSS_ESTILOS = """
    @page {
        size: A4;
        margin: 1.5cm 1.3cm 1.8cm 1.3cm;
        @bottom-right {
            content: "Gemelo Digital de Ambulancia — Horizonte Cero  |  Pág. " counter(page);
            font-family: 'Source Sans Pro', Arial, Helvetica, sans-serif;
            font-size: 7pt;
            color: #7f8c8d;
        }
        @bottom-left {
            content: "Equipo Días Gracias Tres  |  HPE CDS TC 2026";
            font-family: 'Source Sans Pro', Arial, Helvetica, sans-serif;
            font-size: 7pt;
            color: #7f8c8d;
        }
    }
    body {
        font-family: 'Source Sans Pro', Arial, Helvetica, sans-serif;
        font-size: 9.5pt;
        line-height: 1.35;
        color: #333333;
    }
    h1 {
        color: #0a6e8a;
        font-size: 18pt;
        font-weight: 700;
        margin-top: 0.5cm;
        margin-bottom: 0.2cm;
        border-bottom: 2px solid #0a6e8a;
        padding-bottom: 3pt;
    }
    h2 {
        color: #0a6e8a;
        font-size: 14pt;
        font-weight: 700;
        margin-top: 0.4cm;
        margin-bottom: 0.15cm;
    }
    h3 {
        color: #0a6e8a;
        font-size: 11.5pt;
        font-weight: 600;
        margin-top: 0.3cm;
        margin-bottom: 0.1cm;
    }
    h4 {
        color: #2c3e50;
        font-size: 10pt;
        font-weight: 600;
        margin-top: 0.25cm;
        margin-bottom: 0.1cm;
    }
    p {
        margin-bottom: 0.2cm;
        text-align: justify;
    }
    blockquote {
        border-left: 4px solid #0a6e8a;
        margin: 0.3cm 0;
        padding: 0.25cm 0.5cm;
        color: #1a1a2e;
        background: #e8f4f8;
        border-radius: 0 4pt 4pt 0;
    }
    blockquote p, blockquote table {
        margin: 0.1cm 0;
    }
    blockquote strong {
        color: #0a6e8a;
    }
    blockquote table {
        width: 100%;
        border-collapse: collapse;
        font-size: 9pt;
        margin-top: 0.15cm;
    }
    blockquote th {
        background-color: #0a6e8a;
        color: #ffffff;
        font-weight: 600;
        padding: 4pt 6pt;
    }
    blockquote td {
        background-color: transparent;
        border-bottom: 0.5px solid #b0cdd8;
        padding: 3pt 6pt;
        vertical-align: middle;
    }
    ol, ul {
        margin-left: 0.4cm;
        margin-bottom: 0.2cm;
        line-height: 1.3;
    }
    li {
        margin-bottom: 0.05cm;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 0.25cm 0;
        font-size: 8.5pt;
    }
    th {
        background-color: #0a6e8a;
        color: #ffffff;
        font-weight: 600;
        text-align: left;
        padding: 4pt 6pt;
    }
    td {
        border-bottom: 0.5px solid #d5d8dc;
        padding: 3pt 6pt;
        vertical-align: top;
    }
    tr:nth-child(even) td {
        background-color: #f9fafb;
    }
    pre {
        background-color: #f4f6f7;
        border: 1px solid #d5d8dc;
        border-radius: 3pt;
        padding: 5pt 8pt;
        font-size: 7.5pt;
        line-height: 1.25;
        overflow-x: auto;
        white-space: pre-wrap;
        word-wrap: break-word;
    }
    code {
        font-family: 'Source Code Pro', 'Courier New', monospace;
        font-size: 8pt;
        background-color: #eef1f3;
        padding: 1pt 2pt;
        border-radius: 2pt;
    }
    pre code {
        background: none;
        padding: 0;
        font-size: 7.5pt;
    }
    hr {
        border: none;
        border-top: 1px solid #d5d8dc;
        margin: 0.3cm 0;
    }
    a {
        color: #0a6e8a;
        text-decoration: none;
    }
    strong {
        color: #2c3e50;
    }
    img {
        max-width: 100%;
        width: 100%;
        height: auto;
        display: block;
        margin: 0.3cm auto;
    }
    figure {
        margin: 0.3cm 0;
        page-break-inside: avoid;
    }
    figcaption {
        font-size: 8pt;
        color: #555555;
        text-align: center;
        font-style: italic;
        margin-top: 0.1cm;
    }
    em {
        display: block;
        font-size: 8pt;
        color: #555555;
        text-align: center;
        font-style: italic;
        margin-top: 0.1cm;
        margin-bottom: 0.2cm;
    }
"""


def generar_pdf(md_path, pdf_path):
    # 1. Leer el archivo Markdown
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 2. Convertir Markdown a HTML con extensiones
    html_body = markdown.markdown(md_text, extensions=['tables', 'fenced_code'])

    # 3. Combinar HTML completo con estilos CSS
    html_completo = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>{CSS_ESTILOS}</style>
</head>
<body>
{html_body}
</body>
</html>"""

    # 4. Generar el PDF con WeasyPrint (base_url necesario para resolver rutas de imágenes relativas)
    base_url = "file://" + os.path.abspath(os.path.dirname(md_path)) + "/"
    HTML(string=html_completo, base_url=base_url).write_pdf(pdf_path)
    print(f"PDF generado con éxito: {pdf_path}")


# Ejecución
if __name__ == "__main__":
    archivo_entrada = "gemelo_digital_ambulancia_POC.md"
    archivo_salida = "gemelo_digital_ambulancia_POC_estilizado.pdf"
    generar_pdf(archivo_entrada, archivo_salida)