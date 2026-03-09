FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    linux-perf \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mlviz/ mlviz/
COPY .env .env

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "mlviz.workloads.resnet_main"]
