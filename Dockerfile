FROM python:3.11-slim

# System deps for garmindb (mysqlclient) and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmariadb-dev \
    curl \
    cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data directories (overridden by volume mounts in compose)
RUN mkdir -p /data/garmin /data/garth /data/zwift_workouts /data/logs \
             /data/workout_imports /config/workouts

# Non-root user — run with minimal privileges
RUN adduser --disabled-password --gecos "" --home /home/appuser appuser \
    && chown -R appuser:appuser /app /data /config

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

USER appuser

CMD ["python", "main.py", "--daemon"]
