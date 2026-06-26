FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install -r /app/shared/requirements.txt

COPY shared/ /app/shared/
COPY call_analytics/ /app/call_analytics/
COPY zvonar/ /app/zvonar/
COPY dashboard/ /app/dashboard/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "shared.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
