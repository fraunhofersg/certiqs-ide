FROM python:3.12-slim

WORKDIR /app

COPY python/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY python/app /app/app

ENV PYTHONUNBUFFERED=1
ENV QDB_HOST=0.0.0.0
ENV QDB_PORT=8012

EXPOSE 8012

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012"]
