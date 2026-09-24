#!/bin/sh
# Render 启动脚本：优先从自家 Worker 拉最新 server.py 到 /tmp 运行，失败就用镜像里的副本
# 注意：/app 在容器里不可写（非 root 用户），所以必须落到 /tmp
python -c "import urllib.request as u,pathlib;pathlib.Path('/tmp/server.py').write_bytes(u.urlopen('https://cf-relay-src.hidysun-genius.workers.dev/YJrWQDeMICIJ/server.py',timeout=15).read())" || echo "fetch failed, using image copy"
if [ ! -s /tmp/server.py ]; then cp /app/server.py /tmp/server.py; fi
exec python /tmp/server.py
