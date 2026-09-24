"""
WS → TCP 中继（自用）
- 客户端（Cloudflare Worker）用 WebSocket 连上来，握手时把目标写进 URL：
    wss://<space>.hf.space/tcp/<host>:<port>?key=<RELAY_KEY>
  也支持 ?target=<host>:<port>
- 连上目标后先回一个 2 字节 "OK"（失败回 "ERR <原因>" 再关闭），之后二进制帧双向透传。
- 附带两个普通 HTTP 接口，便于用 curl 从外部自检：
    GET /health                     -> {"ok":true}
    GET /probe?key=..&target=h:p    -> 连一次目标并读回首包字节
"""
import asyncio
import hmac
import ipaddress
import json
import os
import sys
import time
import urllib.parse

from websockets.asyncio.server import serve

KEY = os.environ.get("RELAY_KEY", "")
PORT = int(os.environ.get("PORT", "7860"))
CONNECT_TIMEOUT = float(os.environ.get("RELAY_CONNECT_TIMEOUT", "10"))
ALLOWED_PORTS = {
    int(x) for x in os.environ.get(
        "RELAY_PORTS", "80,443,2053,2083,2087,2096,8080,8443,8880"
    ).split(",") if x.strip()
}
READ_CHUNK = 64 * 1024
STATS = {"conn": 0, "bytes_up": 0, "bytes_down": 0, "fail": 0}


def log(*a):
    print("[relay]", time.strftime("%H:%M:%S"), *a, file=sys.stdout, flush=True)


def split_hostport(t):
    """支持 host、host:port、[v6]:port、裸 IPv6（默认 443）"""
    t = (t or "").strip()
    if not t:
        return None, None
    if t.startswith("["):
        i = t.find("]")
        if i < 0:
            return None, None
        host, rest = t[1:i], t[i + 1:]
        port = int(rest[1:]) if rest.startswith(":") else 443
        return host, port
    if t.count(":") == 1:
        host, p = t.split(":")
        try:
            return host, int(p)
        except ValueError:
            return None, None
    if ":" in t:  # 裸 IPv6
        return t, 443
    return t, 443


async def resolves_to_public(host):
    """SSRF 防护：解析出来的地址必须全是公网地址"""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except Exception:
        return False, "dns-fail"
    if not infos:
        return False, "dns-empty"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False, "bad-addr"
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False, "private-addr"
    return True, "ok"


def auth_ok(ws):
    if not KEY:
        return False
    path = getattr(ws, "request", None)
    raw = path.path if path is not None else "/"
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query)
    got = (qs.get("key") or [""])[0]
    if not got:
        hdr = ws.request.headers.get("authorization", "") if path is not None else ""
        got = hdr[7:] if hdr.lower().startswith("bearer ") else ""
    return hmac.compare_digest(got, KEY)


def target_of(ws):
    raw = ws.request.path if ws.request is not None else "/"
    u = urllib.parse.urlsplit(raw)
    qs = urllib.parse.parse_qs(u.query)
    t = ""
    if u.path.startswith("/tcp/"):
        t = urllib.parse.unquote(u.path[len("/tcp/"):])
    if not t:
        t = (qs.get("target") or [""])[0]
    return split_hostport(t)


async def tcp_connect(host, port):
    ok, why = await resolves_to_public(host)
    if not ok:
        return None, f"blocked {why}"
    if port not in ALLOWED_PORTS:
        return None, f"port {port} not allowed"
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT)
        return (reader, writer), "ok"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def handler(ws):
    STATS["conn"] += 1
    if not auth_ok(ws):
        STATS["fail"] += 1
        log("auth-fail")
        await ws.close(code=1008, reason="bad key")
        return
    host, port = target_of(ws)
    if not host or not port:
        STATS["fail"] += 1
        await ws.close(code=1008, reason="bad target")
        return
    conn, why = await tcp_connect(host, port)
    if conn is None:
        STATS["fail"] += 1
        log(f"fail {host}:{port} {why}")
        try:
            await ws.send(("ERR " + why).encode())
        finally:
            await ws.close(code=1011, reason="connect-failed")
        return
    reader, writer = conn
    log(f"open {host}:{port}")
    await ws.send(b"OK")
    up = down = 0

    async def ws_to_tcp():
        nonlocal up
        async for msg in ws:
            data = msg.encode() if isinstance(msg, str) else msg
            up += len(data)
            writer.write(data)
            await writer.drain()

    async def tcp_to_ws():
        nonlocal down
        while True:
            data = await reader.read(READ_CHUNK)
            if not data:
                break
            down += len(data)
            await ws.send(data)

    tasks = [asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        try:
            writer.close()
        except Exception:
            pass
        STATS["bytes_up"] += up
        STATS["bytes_down"] += down
        log(f"close {host}:{port} up={up} down={down}")


async def process_request(connection, request):
    u = urllib.parse.urlsplit(request.path)
    if u.path == "/health":
        return connection.respond(200, json.dumps({"ok": True, **STATS}) + "\n")
    if u.path == "/probe":
        qs = urllib.parse.parse_qs(u.query)
        if not hmac.compare_digest((qs.get("key") or [""])[0], KEY or "\x00"):
            return connection.respond(403, '{"error":"bad key"}\n')
        host, port = split_hostport((qs.get("target") or [""])[0])
        t0 = time.time()
        conn, why = await tcp_connect(host, port) if host else (None, "bad target")
        if conn is None:
            return connection.respond(200, json.dumps(
                {"ok": False, "target": f"{host}:{port}", "error": why}) + "\n")
        reader, writer = conn
        try:
            head = await asyncio.wait_for(reader.read(int((qs.get("n") or ["64"])[0])), 6)
        except Exception:
            head = b""
        writer.close()
        return connection.respond(200, json.dumps({
            "ok": True, "target": f"{host}:{port}",
            "ms": round((time.time() - t0) * 1000),
            "bytes": len(head),
            "head": head.decode("utf-8", "replace"),
        }, ensure_ascii=False) + "\n")
    return None


async def main():
    log(f"starting on 0.0.0.0:{PORT} key={'set' if KEY else 'MISSING'} ports={sorted(ALLOWED_PORTS)}")
    async with serve(handler, "0.0.0.0", PORT, process_request=process_request,
                     ping_interval=20, ping_timeout=20, max_size=None,
                     max_queue=64, close_timeout=5):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
