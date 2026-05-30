FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PORT=8080
ENV TELEGRAM_TOKEN=""
ENV MINI_APP_URL=""
ENV SSTATS_TOKEN=""
ENV OWNER_ID=0

EXPOSE 8080

CMD gunicorn --bind 0.0.0.0:$PORT --workers 2 app:app
