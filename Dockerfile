# Dockerfile para Servicio Web: Asesor de Seguridad en Alta Montaña
# Grupo 1 - Advance Prompt Engineering for Generative IA

FROM python:3.11-slim

# Metadatos del contenedor
LABEL maintainer="Grupo 1 - Advance Prompt Engineering"
LABEL description="Asesor de Seguridad en Alta Montaña con FastAPI y Gemini Pro"

# Variables de entorno para optimización de Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema mínimas requeridas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar requerimientos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación y la interfaz
COPY main.py .
COPY index.html .

# Crear un usuario no privilegiado para ejecución segura
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Exponer el puerto del servicio
EXPOSE 8000

# Healthcheck nativo
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

# Comando de ejecución con Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
