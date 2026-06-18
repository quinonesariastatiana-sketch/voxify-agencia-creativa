FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema para moviepy/Pillow
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Puerto
EXPOSE 8080

# Iniciar Flask
CMD ["python", "server.py"]
