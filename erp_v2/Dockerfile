FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir 'psycopg[binary]==3.2.13' 'fastapi==0.115.12' 'uvicorn==0.34.2'
COPY . /app
CMD ["python", "server.py"]
