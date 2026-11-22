FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

# Przy pierwszym starcie wczytuje 18 303 AED z data/pl_aed.geojson (przy kolejnych pomija import)
CMD ["sh", "-c", "python import_poland_geojson.py --if-empty && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
