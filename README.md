# Memharbor Token Server

Django-based token server for Agora RTC + Cloud Recording, exposed via `memory-harbor.delight-house.org`.

## What It Does
- Issues Agora RTC tokens (1:1 voice call use case)
- Proxies Agora Cloud Recording REST APIs (acquire/start/stop)

## Endpoints
Base URL: `https://memory-harbor.delight-house.org`

- `POST /api/token`
  - Body: `channel` (required), `uid` (int) or `user_account` (string), `role` (publisher/subscriber), `expire` (seconds)
  - Default `expire`: 86400 seconds (24h), capped at 86400

- `POST /api/recording/acquire`
  - Body: `cname` or `channel`, `uid`, optional `clientRequest`

- `POST /api/recording/start`
  - Body: `resourceId`, `cname` or `channel`, `uid`, `mode` (default `individual`), `clientRequest`

- `POST /api/recording/stop`
  - Body: `resourceId`, `sid`, `cname` or `channel`, `uid`, `mode` (default `individual`), optional `clientRequest`

- `GET /api/health`

## Environment Variables
Defined in root `.env` (shared with docker-compose):

- `AGORA_APP_ID`
- `AGORA_APP_CERT`
- `AGORA_CUSTOMER_ID`
- `AGORA_CUSTOMER_SECRET`
- `AGORA_CLOUD_RECORDING_BASE_URL` (default: `https://api.sd-rtn.com`)
- `MEMHARBOR_SECRET_KEY` (optional, defaults to an unsafe dev key)
- `MEMHARBOR_DEBUG` (`1` to enable debug)

## Docker (Prod)
Service name: `memharbor_server`

- `docker-compose.prod.yml` includes the service and exposes it through nginx at
  `memory-harbor.delight-house.org`.

## Local Dev
If you want to run locally without docker:

```bash
cd memharbor_server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8001
```

## Notes
- Cloud Recording uses Agora REST API with HTTP Basic Auth.
- `clientRequest` is currently passed through as-is to Agora.
