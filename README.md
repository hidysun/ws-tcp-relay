# ws-tcp-relay

A tiny WebSocket → TCP relay, built so that a Cloudflare Worker can reach
destinations whose IP ranges Workers are not allowed to connect to directly.

## Usage

- Tunnel: `wss://<host>/tcp/<target-host>:<port>?key=<RELAY_KEY>`
- Health: `GET /health`
- Probe: `GET /probe?key=<RELAY_KEY>&target=example.com:443`

After the WebSocket handshake the server sends a 2-byte preamble: `OK` on success,
or `ERR <reason>` followed by a close. After `OK`, binary frames are piped both ways.

## Environment

- `RELAY_KEY` (required) shared secret
- `PORT` (default `7860`)
- `RELAY_PORTS` (default `80,443,2053,2083,2087,2096,8080,8443,8880`)

Private, loopback and reserved targets are refused.
