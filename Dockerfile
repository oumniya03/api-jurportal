# Utilisation de l'image officielle Playwright qui contient Python et les navigateurs
FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app

# Copie et installation des dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code fusionné
COPY api.py .

# Railway injecte automatiquement le port dans la variable $PORT
# On lance sur 0.0.0.0 pour l'accessibilité réseau
CMD uvicorn api:app --host 0.0.0.0 --port $PORT
