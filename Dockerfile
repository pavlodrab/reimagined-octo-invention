FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create volume for persistent DB
VOLUME ["/app/data"]

# Environment defaults (override in docker-compose or -e)
ENV PORT=5000
ENV TELEGRAM_TOKEN=""
ENV MINI_APP_URL=""
ENV SSTATS_TOKEN=""
ENV OWNER_ID=0

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

CMD ["python", "app.py"]
