# Dockerfile para Servicio Web: Asesor de Seguridad en Alta Montaña

FROM python:3.11-slim

# Metadatos del contenedor
LABEL maintainer="Mountain Safety Advisor"
LABEL description="Asesor de Seguridad en Alta Montaña con FastAPI y Experto IA"

# Variables de entorno para optimización de Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

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
COPY planificador.html .

# Crear un usuario no privilegiado para ejecución segura
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Exponer el puerto del servicio (Cloud Run utiliza 8080 por defecto)
EXPOSE 8080

# Comando de ejecución con Uvicorn leyendo la variable PORT de Cloud Run
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
