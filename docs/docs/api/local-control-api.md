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

Browser users authenticate through the WebAuthn login surface at:

- `/login`

The browser session created there is the supported control path for the local console. For automation, prefer the OpenAPI-described JSON endpoints and session-aware clients instead of scraping the HTML UI.

## Launcher Example

```bash
python3 -m spectra_app.spectra_gui_launcher \
  --host 127.0.0.1 \
  --port 5000
```

## Notes

- The launcher defaults to local-only access.
- First-run bootstrap uses `SPECTRA_BOOTSTRAP_SECRET` and the first enrolled operator becomes the admin.
- The OpenAPI document is the supported integration contract for automation and AI clients.
- Prefer the standard REST resources over scraping HTML pages.
