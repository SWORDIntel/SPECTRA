---
title: Local Control API
---

# Local Control API

SPECTRA exposes a local HTTP control surface for the GUI launcher.

## Standard Format

The machine-facing interface is described with OpenAPI 3.1:

- `/openapi.json`
- `/.well-known/openapi.json`

Interactive local docs are available at:

- `/docs`

## Main Endpoints

- `GET /api/system/status`
- `GET /api/components/health`
- `GET /api/security/warnings`
- `GET /api/v1/context`
- `GET /api/v1/readme`
- `POST /api/components/{component_name}/restart`

## Authentication

If API key protection is enabled, clients can authenticate with either:

- `X-API-Key: <key>`
- `?api_key=<key>`

Browser users can also authenticate through:

- `/login`

## Launcher Example

```bash
python3 -m spectra_app.spectra_gui_launcher \
  --host 127.0.0.1 \
  --port 5000 \
  --api-key-env SPECTRA_GUI_API_KEY
```

## Notes

- The launcher defaults to local-only access.
- The OpenAPI document is the supported integration contract for automation and AI clients.
- Prefer the standard REST resources over scraping HTML pages.
