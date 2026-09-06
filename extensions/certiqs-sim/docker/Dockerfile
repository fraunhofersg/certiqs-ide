FROM python:3.10-slim

WORKDIR /app

COPY python/requirements-ide.txt /app/requirements-ide.txt
RUN pip install --no-cache-dir -r /app/requirements-ide.txt

COPY python/src /app/src
COPY python/config /app/config

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV CERTIQS_HOST=0.0.0.0
ENV CERTIQS_PORT=8011
ENV CERTIQS_CONFIG_ROOT=/app/config
ENV CERTIQS_DEFAULT_CONFIG=bbm92-minimal
ENV CERTIQS_LOG_JSON=false

EXPOSE 8011

CMD ["python", "-m", "certiqs_sim.services.api"]
