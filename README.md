# Requisitos Agrocalidad — Bellaflor

Sitio público (GitHub Pages) donde cualquiera con el link elige un **país** y una
**especie** desde el catálogo real de Bellaflor, y el sistema verifica en vivo
los requisitos de comercio exterior en [guia.agrocalidad.gob.ec](https://guia.agrocalidad.gob.ec),
guardando el resultado en Supabase para consultas futuras.

## Estado actual — ✅ Operativo (verificado 2026-07-24)

- **Sitio publicado:** https://freddyerazo.github.io/AgrocalidadDartis/
- **Repositorio:** https://github.com/freddyerazo/AgrocalidadDartis
- **Proyecto Supabase:** `logistica-dashboard` (`kgpzhwocygonppblgmpm`)
- Flujo probado de punta a punta con el sitio real publicado (país: Perú,
  especie: LAVANDA): la solicitud se creó, el workflow de GitHub Actions
  corrió, Playwright consultó el sitio real de Agrocalidad, y el resultado
  quedó guardado y visible en la tabla — tiempo total ≈ 50 segundos.
- Catálogo cargado en Supabase: **55 especies** activas, **255 países**
  (catálogo completo real de Agrocalidad, con `name_es` = nombre exacto tal
  como aparece en el sitio), **63 verificaciones** guardadas hasta el momento
  (incluye una corrida masiva de las 55 especies contra Chile).
- Los 5 pasos de configuración de la sección "Puesta en marcha" ya están
  completados en este repositorio/proyecto — quedan documentados aquí por si
  hay que rehacerlos (ej. rotar el token de GitHub, o replicar en otro repo).

## Cómo funciona

El sitio de Agrocalidad bloquea cualquier consulta automatizada que no venga de
un navegador real (protección Imperva/Incapsula), así que la verificación no
puede hacerse desde el navegador del usuario ni desde un servidor "normal".
Por eso el flujo es:

```
index.html (GitHub Pages)
   │  usuario elige país + especie, clic en "Verificar"
   ▼
Supabase Edge Function "trigger-agrocalidad-check"
   │  crea la solicitud en agrocalidad_requests
   │  dispara el workflow de GitHub Actions (workflow_dispatch)
   ▼
GitHub Actions (.github/workflows/consultar.yml)
   │  levanta un Chromium real con Playwright (worker_ci.py)
   │  navega el sitio de Agrocalidad como lo haría una persona
   │  guarda el resultado en agrocalidad_requirements
   ▼
index.html sondea la solicitud y muestra el resultado (~30-90 segundos)
```

## Archivos

| Archivo | Para qué |
|---|---|
| `index.html` | Frontend público (se publica con GitHub Pages) |
| `agrocalidad_core.py` | Lógica de scraping compartida (Playwright) |
| `worker_ci.py` | Procesa una solicitud puntual — lo ejecuta GitHub Actions |
| `consultar_agrocalidad.py` | Herramienta de línea de comandos para consultas manuales/masivas |
| `.github/workflows/consultar.yml` | Workflow que corre `worker_ci.py` en la nube de GitHub |
| `requirements.txt` | Dependencias Python |
| `.env` (no versionado) | `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` para uso local de `consultar_agrocalidad.py` |

No forman parte de este sistema (quedan solo como referencia local, no se subieron
al repositorio): `agrocalidad_consulta.html` y `actualizar_agrocalidad.py` —
intentos previos que no funcionaban por el bloqueo anti-bot del sitio.

## Esquema en Supabase (proyecto `logistica-dashboard`)

- `public.species` — catálogo de especies de Bellaflor (55 filas activas), con columna
  `name_agrocalidad` (nombre exacto tal como aparece en el catálogo de Agrocalidad,
  para especies cuyo nombre en Bellaflor no coincide directamente — ver
  "Limitaciones conocidas")
- `public.countries` — catálogo de países; se agregó la columna `name_es` con el
  nombre exacto de Agrocalidad (255 países, conciliados con los que ya existían
  en inglés para no duplicar — ej. `US`/"United States" tiene `name_es`="Estados Unidos")
- `public.agrocalidad_requirements` — resultados verificados (especie + país +
  tipo + área → requisitos), con `UNIQUE(species_id, country_id, trade_type, area_code)`
- `public.agrocalidad_requests` — cola de solicitudes desde el sitio público
  (`pending` → `processing` → `done`/`error`), con RLS: el público solo puede
  `SELECT` e `INSERT` (nunca `UPDATE`/`DELETE`)

## Puesta en marcha (referencia — ya completado en este proyecto)

### 1. Repositorio

https://github.com/freddyerazo/AgrocalidadDartis

### 2. GitHub Pages

`Settings → Pages → Source: Deploy from a branch → Branch: main / (root)`
→ https://freddyerazo.github.io/AgrocalidadDartis/

### 3. Secrets del repositorio (para GitHub Actions)

`Settings → Secrets and variables → Actions → New repository secret`

- `SUPABASE_URL` = `https://kgpzhwocygonppblgmpm.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` = la clave `service_role` del proyecto (Supabase → Project Settings → API Keys → Secret keys)

### 4. Token de GitHub para que Supabase dispare el workflow

1. GitHub → foto de perfil → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Repository access: **Only select repositories** → `freddyerazo/AgrocalidadDartis`
3. Permissions → Repository permissions → **Actions: Read and write**
4. Generar y copiar el token (empieza con `github_pat_...`)

### 5. Secrets de la Edge Function en Supabase

Dashboard del proyecto → **Edge Functions** → `trigger-agrocalidad-check` → **Secrets**
(o **Project Settings → Edge Functions** si se comparten a nivel de proyecto):

- `GITHUB_TOKEN` = el token del paso 4
- `GITHUB_OWNER` = `freddyerazo`
- `GITHUB_REPO` = `AgrocalidadDartis`
- `GITHUB_REF` = `main`

### 6. Probar

Abrir el sitio, elegir país + especie, clic en **Verificar en Agrocalidad**.
Resultado esperado en 30-90 segundos.

Si algo falla, revisar:
- Pestaña **Actions** del repositorio (ahí se ve si el workflow corrió y por qué falló)
- Logs de la Edge Function en el dashboard de Supabase (Edge Functions → Logs)
- Tabla `agrocalidad_requests` en Supabase — columna `error_message` tiene el detalle

## Limitaciones conocidas

- Algunas especies del catálogo de Bellaflor están en inglés (ej. `CARNATION`)
  mientras que el catálogo de Agrocalidad tiene el nombre en español (ej.
  "Clavel"). Se resuelve con la columna `species.name_agrocalidad`: si está
  definida, `consultar_agrocalidad.py` y `worker_ci.py` la usan como término de
  búsqueda en vez del nombre de Bellaflor (ver función `resolver_terminos_busqueda`
  / lectura de `name_agrocalidad` en `worker_ci.py`). Todas las 55 especies del
  catálogo fueron revisadas una por una (confirmado con Bellaflor) y quedaron
  con `name_agrocalidad` definido, salvo dos sin equivalente en Agrocalidad:
  `BOUQUETS` (producto compuesto, no una especie) y `SALVIA` (no existe en el
  catálogo de Agrocalidad).
  Nota: tener `name_agrocalidad` definido no garantiza `CON_REQUISITOS` para
  todos los países — algunas especies (ej. `ARALIA`, `ASPARAGUS`, `COPROSMA`,
  `ECHINACEA`, `HEBE`, `MARIGOLD`, `OXYPETALUM`, `PITTOSPORUM VARIEGATA`,
  `SCHEFFLERA`) existen en Agrocalidad pero sin datos registrados para Chile
  específicamente, aunque sí los tengan para otros países (ej. Estados Unidos).
- El tiempo de respuesta (30-90 s, a veces más) es inherente a tener que abrir
  un navegador real cada vez — no hay forma de acelerarlo sin cambiar de
  arquitectura (ver sección "Cómo funciona").

## Próximos pasos posibles (no implementados)

- Consultar más de un país/especie a la vez desde el sitio (hoy es de a uno)
- Exportar la tabla de resultados a CSV/Excel desde el propio sitio
- Sinónimos de especies (inglés/español/científico) para reducir `NO_ENCONTRADO`
