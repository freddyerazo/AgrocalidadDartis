"""
Consulta masiva de requisitos de Agrocalidad (navegador real vía Playwright)
=============================================================================
Uso manual desde línea de comandos. La lógica de scraping vive en
agrocalidad_core.py (compartida con worker_ci.py, usado por GitHub Actions).

Instalación (una sola vez):
    pip install playwright beautifulsoup4 openpyxl supabase python-dotenv
    playwright install chromium

Uso:
    python consultar_agrocalidad.py --pais "Arabia Saudita" --productos ALSTROEMERIA,ROSA,CLAVEL
    python consultar_agrocalidad.py --pais "Estados Unidos" --archivo especies.txt --salida resultados.xlsx
    python consultar_agrocalidad.py --pais "Arabia Saudita" --productos ALSTROEMERIA --visible

Parámetros:
    --pais         Nombre del país destino, tal como aparece en Agrocalidad (obligatorio).
    --productos    Lista de especies separadas por coma.
    --archivo      Alternativa a --productos: un .txt con una especie por línea.
    --tipo         Exportación | Importación | Tránsito | Nacional (default: Exportación).
    --area         SA (Sanidad Animal) | SV (Sanidad Vegetal) | IAP (Prod. agrícolas)
                   | IAV (Prod. pecuarios) | IAF (Prod. fertilizantes). Default: SV.
    --salida       Ruta del archivo de salida .xlsx o .csv (default: resultados_agrocalidad.xlsx).
    --visible      Muestra la ventana del navegador (por defecto corre oculto/headless).
    --sin-supabase No sincronizar resultados con Supabase aunque esté configurado en .env.

Integración con Supabase:
    Si existe un archivo .env (junto a este script) con SUPABASE_URL y
    SUPABASE_SERVICE_ROLE_KEY, cada resultado se sincroniza automáticamente
    con la tabla public.agrocalidad_requirements del proyecto (creando la
    especie/país en public.species / public.countries si aún no existen).
    Sin ese archivo, el script sigue funcionando igual pero solo guarda el
    archivo local (.csv/.xlsx).
"""

import argparse
import csv
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from agrocalidad_core import AREAS_VALIDAS, CHROME_UA, URL, consultar_producto, normalizar, obtener_id_pais

load_dotenv(Path(__file__).with_name(".env"))


def leer_productos(args) -> list[str]:
    if args.archivo:
        return [l.strip() for l in Path(args.archivo).read_text(encoding="utf-8").splitlines() if l.strip()]
    return [p.strip() for p in args.productos.split(",") if p.strip()]


def guardar_resultados(resultados: list[dict], salida: str):
    columnas = ["producto_buscado", "producto_encontrado", "nombre_cientifico", "partida",
                "codigo_agrocalidad", "pais", "tipo", "estado", "requisitos", "fecha_consulta"]
    ruta = Path(salida)
    if ruta.suffix.lower() == ".csv":
        with ruta.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=columnas)
            w.writeheader()
            w.writerows(resultados)
    else:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Resultados"
        ws.append(columnas)
        for r in resultados:
            ws.append([r.get(c, "") for c in columnas])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 28
        wb.save(ruta)


def get_supabase_client():
    """Devuelve un cliente Supabase si hay credenciales en el entorno (.env), si no None."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    from supabase import create_client
    return create_client(url, key)


def normalizar_code(nombre: str) -> str:
    code = normalizar(nombre)
    code = re.sub(r"[^A-Z0-9]+", "_", code).strip("_")
    return code or "SIN_NOMBRE"


def upsert_referencia(client, tabla: str, nombre: str) -> str:
    """Busca la fila por 'code' normalizado en species; la crea si no existe. Devuelve el id."""
    code = normalizar_code(nombre)
    existente = client.table(tabla).select("id").eq("code", code).execute()
    if existente.data:
        return existente.data[0]["id"]
    nuevo = client.table(tabla).insert({"code": code, "name": nombre}).execute()
    return nuevo.data[0]["id"]


def upsert_pais(client, nombre_agrocalidad: str) -> str:
    """Resuelve el país por su nombre exacto en Agrocalidad (columna name_es, ya
    poblada con el catálogo completo de 255 países). Solo crea una fila nueva si
    de verdad no existe, para no duplicar países que ya están en el catálogo con
    otro nombre/código (ej. 'United States' / 'US' para 'Estados Unidos')."""
    existente = client.table("countries").select("id").eq("name_es", nombre_agrocalidad).execute()
    if existente.data:
        return existente.data[0]["id"]
    return upsert_referencia(client, "countries", nombre_agrocalidad)


def guardar_en_supabase(client, resultados: list[dict], tipo: str, area: str) -> tuple[int, int]:
    guardados, fallidos = 0, 0
    for r in resultados:
        if r["estado"] == "ERROR":
            continue
        try:
            species_id = upsert_referencia(client, "species", r["producto_buscado"])
            country_id = upsert_pais(client, r["pais"])
            fila = {
                "species_id": species_id,
                "country_id": country_id,
                "trade_type": tipo,
                "area_code": area,
                "matched_product_name": r["producto_encontrado"] or None,
                "scientific_name": r["nombre_cientifico"] or None,
                "tariff_heading": r["partida"] or None,
                "agrocalidad_code": r["codigo_agrocalidad"] or None,
                "status": r["estado"],
                "requirements": r["requisitos"] or None,
                "queried_at": datetime.now().isoformat(),
            }
            client.table("agrocalidad_requirements").upsert(
                fila, on_conflict="species_id,country_id,trade_type,area_code"
            ).execute()
            guardados += 1
        except Exception as e:
            print(f"  ⚠ Error guardando en Supabase ({r['producto_buscado']}): {e}")
            fallidos += 1
    return guardados, fallidos


def main():
    ap = argparse.ArgumentParser(description="Consulta masiva de requisitos Agrocalidad vía navegador real")
    ap.add_argument("--pais", required=True)
    ap.add_argument("--productos", default="")
    ap.add_argument("--archivo", default="")
    ap.add_argument("--tipo", default="Exportación",
                     choices=["Exportación", "Importación", "Tránsito", "Nacional"])
    ap.add_argument("--area", default="SV", choices=sorted(AREAS_VALIDAS))
    ap.add_argument("--salida", default="resultados_agrocalidad.xlsx")
    ap.add_argument("--visible", action="store_true", help="Muestra el navegador en vez de correr headless")
    ap.add_argument("--sin-supabase", action="store_true",
                     help="No sincronizar resultados con Supabase aunque esté configurado en .env")
    args = ap.parse_args()

    if not args.productos and not args.archivo:
        ap.error("Debes indicar --productos o --archivo")

    productos = leer_productos(args)
    print("=" * 64)
    print(f"  CONSULTA AGROCALIDAD — {args.pais}")
    print(f"  Tipo: {args.tipo} | Área: {args.area} | Productos: {len(productos)}")
    print("=" * 64)

    resultados = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.visible)
        page = browser.new_page(user_agent=CHROME_UA)
        page.goto(URL, wait_until="networkidle", timeout=30000)
        try:
            pais_id = obtener_id_pais(page, args.pais)
        except ValueError as e:
            print(f"❌ {e}")
            browser.close()
            sys.exit(1)

        for i, producto in enumerate(productos, 1):
            print(f"[{i:02d}/{len(productos)}] {producto:<35}", end="", flush=True)
            try:
                r = consultar_producto(page, producto, args.tipo, args.area, pais_id, args.pais)
            except Exception as e:
                r = {"producto_buscado": producto, "producto_encontrado": "", "nombre_cientifico": "",
                     "partida": "", "codigo_agrocalidad": "", "pais": args.pais, "tipo": args.tipo,
                     "estado": "ERROR", "requisitos": str(e)}
            r["fecha_consulta"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            resultados.append(r)
            icono = {"CON_REQUISITOS": "✅", "SIN_REQUISITOS_REGISTRADOS": "➖",
                     "NO_ENCONTRADO": "❓", "ERROR": "⚠"}.get(r["estado"], "❓")
            print(f" {icono} {r['estado']}")

        browser.close()

    guardar_resultados(resultados, args.salida)
    print()
    print(f"💾 Resultados guardados en: {args.salida}")
    conteo = {}
    for r in resultados:
        conteo[r["estado"]] = conteo.get(r["estado"], 0) + 1
    for estado, n in conteo.items():
        print(f"  {estado}: {n}")

    if not args.sin_supabase:
        client = get_supabase_client()
        if client:
            print()
            print("☁️  Sincronizando con Supabase...")
            guardados, fallidos = guardar_en_supabase(client, resultados, args.tipo, args.area)
            print(f"   {guardados} fila(s) sincronizada(s)" + (f", {fallidos} con error" if fallidos else ""))
        else:
            print()
            print("ℹ️  Supabase no configurado (falta .env con SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")


if __name__ == "__main__":
    main()
