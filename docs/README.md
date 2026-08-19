# SPECTRA Documentation

Welcome to the technical documentation for **SPECTRA** (Spectrally-Processing Extraction, Crawling, & Tele-Reconnaissance Archive).

---

## 📚 Table of Contents

- **[CLI Reference](CLI_REFERENCE.md)**: Full command-line interface guide, flags, and operational subcommands — including `tdata2session` for importing logged-in Telegram Desktop / Alternatives accounts.
- **[Architecture & Intelligence Pipeline](ARCHITECTURE.md)**: Technical breakdown of Layer 0 (Discovery), Layer 1 (Profiling), Layer 1.5 (Worker Queue), and Layer 2 (Nexus Analysis).
- **[Configuration & Accounts](CONFIGURATION.md)**: Setting up Telegram MTProto API credentials, multi-account pools, proxy rotation, tdata → session import, and optional search cache (Redis or QIHSE KV).
- **[Rotation Strategies](ROTATION_STRATEGIES.md)**: Complete reference for all 10 account rotation strategies (sequential, random, weighted, smart, FloodWait-adaptive, circuit breaker, latency, sticky, sharded, primary+fallback) and channel de-duplication.

---

## ⚡ Quick Links

- **Root CLI Launcher**: [`../spectra`](../spectra)
- **Project Repository**: [https://github.com/SWORDIntel/SPECTRA](https://github.com/SWORDIntel/SPECTRA)
- **License**: AGPLv3
