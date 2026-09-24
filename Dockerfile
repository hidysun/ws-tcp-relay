FROM python:3.12-slim

RUN pip install --no-cache-dir "websockets==13.1"

WORKDIR /app
COPY server.py /app/server.py

ENV PORT=7860
EXPOSE 7860

CMD ["python", "-u", "/app/server.py"]
