FROM python:3.12-slim

RUN pip install --no-cache-dir "websockets==13.1"

WORKDIR /app
COPY server.py /app/server.py
COPY start.sh /app/start.sh

ENV PORT=7860
EXPOSE 7860

CMD ["sh", "/app/start.sh"]
