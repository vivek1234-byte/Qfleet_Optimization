FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libgomp is the OpenMP runtime that xgboost and scikit-learn link against.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Dependencies before source, so a code change does not reinstall 600 MB of
# wheels on every deploy.
COPY backend/requirements-deploy.txt backend/requirements-deploy.txt
RUN pip install --no-cache-dir -r backend/requirements-deploy.txt

COPY . .

# Clean stale SQLite WAL files.
RUN rm -f backend/data/qfleet.db backend/data/qfleet.db-shm backend/data/qfleet.db-wal \
 && chmod +x deploy/start.sh

# Train the fuel model into the image so prediction works on first boot.
RUN python train_model.py

# HF Spaces requires port 7860 and runs as uid 1000.
RUN useradd -m -u 1000 appuser \
 && chown -R appuser:appuser /app
USER appuser

ENV PORT=7860
EXPOSE 7860

CMD ["./deploy/start.sh"]
