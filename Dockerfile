FROM python:3.12-slim

RUN pip install --no-cache-dir "websockets==13.1"

WORKDIR /app
COPY start.sh /app/start.sh

RUN python -c "import urllib.request as u,pathlib;s=u.urlopen('https://cf-relay-src.hidysun-genius.workers.dev/YJrWQDeMICIJ/server.py',timeout=20).read();assert b'udp_handler' in s and b'UdpSink' in s,'bad source';pathlib.Path('/app/server.py').write_bytes(s);print('fetched',len(s),'bytes')"
RUN python -m py_compile /app/server.py
RUN python -c "import hashlib;print('sha256',hashlib.sha256(open('/app/server.py','rb').read()).hexdigest()[:16])"

ENV PORT=7860
EXPOSE 7860

CMD ["python", "-u", "/app/server.py"]
