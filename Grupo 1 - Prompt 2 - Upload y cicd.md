Actúa como un Senior DevOps / Cloud Engineer. Toma el proyecto ya reconstruido en el directorio actual y encárgate de:
1) Versionarlo y subirlo a GitHub usando mis credenciales.
2) Desplegar la aplicación en Google Cloud Platform (Google Cloud Run) y verificar que quede operativa en producción.

Ejecuta los pasos en orden y detente solo si necesitas que te proporcione datos faltantes (como el nombre del repositorio, Project ID de GCP o autorización interactiva).

## FASE 1: Control de Versiones y Subida a GitHub
1. **Higiene de seguridad:** Verifica que `.gitignore` excluya `.env`, `.venv/`, `__pycache__/`, credenciales (`*.json`, `*.pem`) y archivos temporales. Confirma que no existan API keys ni tokens hardcodeados en el código.
2. **Inicialización Git:**
   * Si no existe `.git`, ejecuta `git init` y usa `main` como rama principal.
   * Verifica `git config user.name` y `git config user.email`. Si no están configurados, pregúntame los valores o configúralos según mi entorno local.
3. **Autenticación y Repositorio Remoto:**
   * Comprueba si tengo `gh` (GitHub CLI) autenticado (`gh auth status`), llaves SSH configuradas (`ssh -T git@github.com`) o un credential helper activo.
   * Si no hay sesión ni remoto configurado, pídeme la URL del repositorio o crea uno nuevo con `gh repo create` tras confirmar conmigo el nombre y visibilidad (público/privado).
   * Nunca guardes tokens PAT en archivos del repositorio ni en el historial de Git; si se usa HTTPS con token, utiliza el credential helper o una variable de entorno temporal en la sesión.
4. **Flujo de Ramas y Commit:**
   * Crea un commit limpio con todos los archivos del proyecto.
   * Sube la rama `main` a `origin` (`git push -u origin main`) y crea también la rama `development` sincronizada si se trabajará con flujo de PRs.
5. **CI/CD (Opcional):** Crea `.github/workflows/cloudrun-deploy.yml` preparado para construir y desplegar a Cloud Run cuando se haga merge a `main` (documentando en el `README.md` los Secrets de GitHub necesarios: `GCP_PROJECT_ID`, `GCP_SA_KEY` o Workload Identity, y `GEMINI_API_KEY`).

## FASE 2: Despliegue en Google Cloud Platform (Cloud Run)
1. **Validación de CLI y Proyecto:**
   * Verifica si `gcloud` está instalado y autenticado (`gcloud auth list`). Si no está instalado o autenticado, indícame el comando exacto o pasos mínimos para iniciar sesión.
   * Verifica el proyecto activo (`gcloud config get-value project`). Si no hay uno definido, lístame los proyectos disponibles (`gcloud projects list`) o pídeme el `PROJECT_ID`.
2. **Habilitación de APIs en GCP:**
   Habilita los servicios necesarios si aún no lo están:
   * `run.googleapis.com`
   * `cloudbuild.googleapis.com`
   * `artifactregistry.googleapis.com`
3. **Configuración de Variables / Secretos:**
   * Pídeme la `GEMINI_API_KEY` (o léela de `.env` local sin imprimirla en logs ni subirla a Git) para inyectarla de forma segura en Cloud Run (preferiblemente con Secret Manager o `--set-env-vars` en el despliegue).
4. **Build y Deploy en Cloud Run:**
   * Verifica que el `Dockerfile` escuche en `${PORT:-8080}` (puerto estándar de Cloud Run).
   * Despliega directamente desde el código fuente usando:
     `gcloud run deploy mountain-safety-advisor --source . --region <REGION> --platform managed --allow-unauthenticated --port 8080`
     (usa `us-central1` o `southamerica-west1` si no especifico otra región).
5. **Verificación Post-Despliegue:**
   * Obtén la URL pública generada por Cloud Run.
   * Ejecuta pruebas contra la URL pública (`curl` a `/api/health`, `/` y `/planificador`) y confirma que respondan HTTP 200 y que `gemini_api_configured` sea `true` (si se configuró la key).
   * Entrégame un resumen final con: URL del repositorio en GitHub, URL pública de Cloud Run y estado de las verificaciones.