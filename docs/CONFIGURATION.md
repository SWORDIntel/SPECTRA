# SPECTRA Configuration Guide

SPECTRA stores operational configuration and runtime states under `data/config/`.

---

## 🔑 Telegram API Credentials

To interact with the Telegram MTProto API, you must obtain an `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org).

Set up `data/config/spectra_config.json`:

```json
{
    "api_id": 1234567,
    "api_hash": "0123456789abcdef0123456789abcdef"
}
```

---

## 👥 Multi-Account Orchestration & Proxies

SPECTRA supports managing multiple Telegram account sessions with dedicated SOCKS5/HTTP proxy rotation to avoid rate limiting and maintain OPSEC.

```json
{
    "api_id": 1234567,
    "api_hash": "0123456789abcdef0123456789abcdef",
    "accounts": [
        {
            "session_name": "worker_node_1",
            "proxy": {
                "proxy_type": "socks5",
                "addr": "127.0.0.1",
                "port": 9050
            }
        }
    ]
}
```

---

## 🧪 Testing Connectivity

Verify your configured account pools and proxy connectivity:

```bash
./spectra accounts --test
```
