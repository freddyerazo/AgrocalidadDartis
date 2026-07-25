"""
Procesa UNA solicitud puntual de la cola public.agrocalidad_requests.
Pensado para correr dentro de GitHub Actions (.github/workflows/consultar.yml),
disparado por la Edge Function de Supabase cada vez que alguien pide una
verificación desde el sitio web (index.html en GitHub Pages).

Uso:
    python worker_ci.py <request_id>

Variables de entorno requeridas (se configuran como Secrets del repositorio
en GitHub Actions):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import os
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright
from supabase import create_client

from agrocalidad_core import CHROME_UA, URL, consultar_producto, obtener_id_pais

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        print("Uso: python worker_ci.py <request_id>")
        sys.exit(1)
    request_id = sys.argv[1]

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    solicitud = (
        client.table("agrocalidad_requests")
        .select("id, trade_type, area_code, species:species_id(id, name, name_agrocalidad), country:country_id(id, name_es)")
        .eq("id", request_id)
        .single()
        .execute()
        .data
    )
    if not solicitud:
        print(f"❌ Solicitud {request_id} no encontrada")
        sys.exit(1)

    especie = solicitud["species"]["name"]
    especie_busqueda = solicitud["species"]["name_agrocalidad"] or especie
    pais = solicitud["country"]["name_es"]
    tipo = solicitud["trade_type"]
    area = solicitud["area_code"]

    print(f"Procesando solicitud {request_id}: {especie} -> {pais} ({tipo}, {area})")
    client.table("agrocalidad_requests").update({"status": "processing"}).eq("id", request_id).execute()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=CHROME_UA)
            page.goto(URL, wait_until="networkidle", timeout=30000)
            pais_id = obtener_id_pais(page, pais)
            resultado = consultar_producto(page, especie_busqueda, tipo, area, pais_id, pais)
            browser.close()

        if resultado["estado"] == "ERROR":
            raise RuntimeError(resultado["requisitos"] or "Error desconocido consultando Agrocalidad")

        fila = {
            "species_id": solicitud["species"]["id"],
            "country_id": solicitud["country"]["id"],
            "trade_type": tipo,
            "area_code": area,
            "matched_product_name": resultado["producto_encontrado"] or None,
            "scientific_name": resultado["nombre_cientifico"] or None,
            "tariff_heading": resultado["partida"] or None,
            "agrocalidad_code": resultado["codigo_agrocalidad"] or None,
            "status": resultado["estado"],
            "requirements": resultado["requisitos"] or None,
            "queried_at": datetime.now().isoformat(),
        }
        guardado = (
            client.table("agrocalidad_requirements")
            .upsert(fila, on_conflict="species_id,country_id,trade_type,area_code")
            .execute()
        )
        requirement_id = guardado.data[0]["id"]

        client.table("agrocalidad_requests").update({
            "status": "done",
            "requirement_id": requirement_id,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", request_id).execute()

        print(f"✅ Listo: {resultado['estado']}")

    except Exception as e:
        print(f"⚠ Error: {e}")
        client.table("agrocalidad_requests").update({
            "status": "error",
            "error_message": str(e)[:500],
            "updated_at": datetime.now().isoformat(),
        }).eq("id", request_id).execute()
        sys.exit(1)


if __name__ == "__main__":
    main()
