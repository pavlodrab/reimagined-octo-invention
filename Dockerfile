FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment defaults (override via Railway variables)
ENV PORT=5000
ENV TELEGRAM_TOKEN=""
ENV MINI_APP_URL=""
ENV SSTATS_TOKEN=""
ENV OWNER_ID=0

EXPOSE 5000

CMD ["python", "app.py"]
