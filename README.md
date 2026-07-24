# Requisitos Agrocalidad — Bellaflor

Sitio público (GitHub Pages) donde cualquiera con el link elige un **país** y una
**especie** desde el catálogo real de Bellaflor, y el sistema verifica en vivo
los requisitos de comercio exterior en [guia.agrocalidad.gob.ec](https://guia.agrocalidad.gob.ec),
guardando el resultado en Supabase para consultas futuras.

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

## Puesta en marcha (una sola vez)

### 1. Crear el repositorio

Crea un repositorio **público** en GitHub (público para poder usar GitHub Pages
gratis). Sube todos los archivos de esta carpeta **excepto** `.env` (ya está en
`.gitignore`, nunca debe subirse).

### 2. Activar GitHub Pages

`Settings → Pages → Source: Deploy from a branch → Branch: main / (root)`

Tu sitio quedará en `https://<tu-usuario>.github.io/<tu-repo>/`

### 3. Secrets del repositorio (para GitHub Actions)

`Settings → Secrets and variables → Actions → New repository secret`

- `SUPABASE_URL` = `https://kgpzhwocygonppblgmpm.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` = la clave `service_role` del proyecto (Supabase → Project Settings → API Keys → Secret keys)

### 4. Token de GitHub para que Supabase dispare el workflow

1. Ve a GitHub → tu foto de perfil → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Repository access: **Only select repositories** → elige este repositorio
3. Permissions → Repository permissions → **Actions: Read and write**
4. Genera el token y cópialo (empieza con `github_pat_...`)

### 5. Configurar la Edge Function en Supabase

En el [dashboard de Supabase](https://supabase.com/dashboard/project/kgpzhwocygonppblgmpm/functions/trigger-agrocalidad-check/secrets),
agrega estos secrets de la función (o del proyecto, se comparten):

- `GITHUB_TOKEN` = el token que generaste en el paso 4
- `GITHUB_OWNER` = tu usuario u organización de GitHub
- `GITHUB_REPO` = el nombre del repositorio
- `GITHUB_REF` = `main` (o el nombre de tu rama principal, si es distinto)

### 6. Probar

Abre tu sitio (`https://<tu-usuario>.github.io/<tu-repo>/`), elige un país y una
especie, y haz clic en **Verificar en Agrocalidad**. En 30-90 segundos debería
aparecer el resultado en la tabla.

Si algo falla, revisa:
- La pestaña **Actions** del repositorio (ahí se ve si el workflow corrió y por qué falló)
- Los logs de la Edge Function en el dashboard de Supabase (Edge Functions → Logs)
