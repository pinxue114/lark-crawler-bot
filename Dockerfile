FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py crawler.py ./

EXPOSE 5000

# WARNING: --workers must stay at 1 unless external dedup (e.g. Redis) is added.
# Each worker has its own in-memory event dedup set — multiple workers = duplicate processing.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "2", "--timeout", "30", "bot:app"]
