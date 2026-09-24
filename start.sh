#!/bin/sh
# Render 启动脚本：优先从自家 Worker 拉最新 server.py，失败就用镜像里的副本
python -c "import urllib.request as u,pathlib;pathlib.Path('/app/server.py').write_bytes(u.urlopen('https://cf-relay-src.hidysun-genius.workers.dev/YJrWQDeMICIJ/server.py',timeout=15).read())" || echo "fetch failed, using image copy"
exec python /app/server.py
