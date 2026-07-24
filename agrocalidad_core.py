"""
Lógica compartida para consultar requisitos de comercio exterior en
https://guia.agrocalidad.gob.ec vía un navegador real (Playwright).

El sitio está protegido por Imperva/Incapsula, que bloquea (HTTP 500)
cualquier envío del formulario que no provenga de un navegador real
(curl, requests, proxies CORS, etc. quedan bloqueados). Por eso se controla
un Chromium real: se navega la página, se completa el formulario y se hace
clic exactamente como lo haría una persona.

Usado por:
  - consultar_agrocalidad.py  (uso manual desde línea de comandos)
  - worker_ci.py              (procesa una solicitud puntual, usado por GitHub Actions)
"""

import unicodedata

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PWTimeout

URL = "https://guia.agrocalidad.gob.ec/agrodb/aplicaciones/publico/productos1/consultaRequisitoComercio.php"

AREAS_VALIDAS = {"SA", "SV", "IAP", "IAV", "IAF"}

CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def normalizar(s: str) -> str:
    s = str(s or "").strip().upper()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def obtener_id_pais(page, pais: str) -> str:
    opciones = page.eval_on_selector_all(
        "#pais option", "els => els.map(e => [e.value, e.textContent.trim()])"
    )
    mapa = {normalizar(label): value for value, label in opciones if value}
    pais_norm = normalizar(pais)
    if pais_norm in mapa:
        return mapa[pais_norm]
    # búsqueda parcial si no hay coincidencia exacta
    for label_norm, value in mapa.items():
        if pais_norm in label_norm or label_norm in pais_norm:
            return value
    disponibles = ", ".join(sorted(mapa.keys())[:15]) + "..."
    raise ValueError(f"País '{pais}' no encontrado en Agrocalidad. Ejemplos disponibles: {disponibles}")


def elegir_mejor_match(producto_buscado: str, opciones: list[dict]) -> dict:
    """opciones: [{'id':..., 'label':...}, ...]. Devuelve la más parecida al texto buscado."""
    buscado = normalizar(producto_buscado)
    mejor, mejor_score = opciones[0], -1
    for op in opciones:
        label = normalizar(op["label"])
        if label == buscado:
            return op
        if label.startswith(buscado) or buscado.startswith(label):
            score = min(len(label), len(buscado)) / max(len(label), len(buscado)) + 0.5
        elif buscado in label or label in buscado:
            score = min(len(label), len(buscado)) / max(len(label), len(buscado))
        else:
            score = 0
        if score > mejor_score:
            mejor, mejor_score = op, score
    return mejor


def esperar_contenido(page, selector: str, timeout: int = 15000):
    page.wait_for_function(
        """(sel) => {
            const el = document.querySelector(sel);
            return el && el.innerText.trim().length > 0 && !el.innerText.includes('Cargando');
        }""",
        arg=selector,
        timeout=timeout,
    )


def parsear_requisitos(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    datos = {"nombre_cientifico": "", "partida": "", "codigo_agrocalidad": "", "requisitos": ""}

    for fila in soup.select("fieldset legend"):
        if fila.get_text(strip=True) == "Datos generales":
            tabla = fila.find_parent("fieldset").find("table")
            for tr in tabla.find_all("tr"):
                th, td = tr.find("th"), tr.find("td")
                if not th or not td:
                    continue
                etiqueta = th.get_text(strip=True).lower()
                valor = td.get_text(" ", strip=True)
                if "nombre de producto" in etiqueta:
                    datos["nombre_cientifico"] = valor
                elif "partida recomendada" in etiqueta:
                    datos["partida"] = valor
                elif "código de agrocalidad" in etiqueta or "codigo de agrocalidad" in etiqueta:
                    datos["codigo_agrocalidad"] = valor
            break

    bloques_req = []
    for fieldset in soup.select("fieldset.requisitos"):
        legend = fieldset.find("legend")
        pais_legend = legend.get_text(strip=True) if legend else ""
        items = []
        for tr in fieldset.select("table tr"):
            ordinal = tr.select_one(".ordinal")
            requisito = tr.select_one(".requisito")
            if ordinal and requisito:
                texto = requisito.get_text(" ", strip=True)
                items.append(f"{ordinal.get_text(strip=True)}: {texto}")
        if items:
            bloques_req.append(f"[{pais_legend}] " + " | ".join(items))
    datos["requisitos"] = "  ///  ".join(bloques_req)
    return datos


def consultar_producto(page, producto: str, tipo: str, area: str, pais_id: str, pais_nombre: str) -> dict:
    base = {
        "producto_buscado": producto,
        "producto_encontrado": "",
        "nombre_cientifico": "",
        "partida": "",
        "codigo_agrocalidad": "",
        "estado": "",
        "requisitos": "",
        "pais": pais_nombre,
        "tipo": tipo,
    }

    page.goto(URL, wait_until="networkidle", timeout=30000)
    page.check({"Exportación": "#exportacion", "Importación": "#importacion",
                "Tránsito": "#transito", "Nacional": "#nacional"}[tipo])
    page.select_option("#area", area)
    page.select_option("#pais", pais_id)
    page.fill("#productoN", producto)
    page.click("#buscar")

    try:
        esperar_contenido(page, "#resultadoProducto")
    except PWTimeout:
        base["estado"] = "ERROR"
        base["requisitos"] = "Tiempo de espera agotado buscando el producto"
        return base

    texto_resultado = page.inner_text("#resultadoProducto")
    if "NO EXISTEN COINCIDENCIAS" in texto_resultado.upper():
        base["estado"] = "NO_ENCONTRADO"
        return base

    checkboxes = page.eval_on_selector_all(
        "#resultadoProducto .productoActivar",
        "els => els.map(e => ({id: e.value, label: (document.querySelector(`label[for=\"${e.id}\"]`)?.innerText || '').trim()}))",
    )
    if not checkboxes:
        base["estado"] = "NO_ENCONTRADO"
        return base

    mejor = elegir_mejor_match(producto, checkboxes)
    base["producto_encontrado"] = mejor["label"]
    page.check(f"#resultadoProducto input.productoActivar[value='{mejor['id']}']")
    page.click("#resultadoProducto #buscar")

    try:
        esperar_contenido(page, "#resultadoProducto2")
    except PWTimeout:
        base["estado"] = "ERROR"
        base["requisitos"] = "Tiempo de espera agotado obteniendo requisitos"
        return base

    html2 = page.inner_html("#resultadoProducto2")
    datos = parsear_requisitos(html2)
    base.update({k: v for k, v in datos.items() if k != "requisitos" or v})
    base["requisitos"] = datos["requisitos"]
    base["estado"] = "CON_REQUISITOS" if datos["requisitos"] else "SIN_REQUISITOS_REGISTRADOS"
    return base
