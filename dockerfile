# Utiliser l'image officielle de Playwright (inclut Python et les navigateurs)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY requirements.txt .

# Installer les packages Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'API
COPY api.py .

# Exposer le port pour FastAPI
EXPOSE 8000

# Lancer le serveur web
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]