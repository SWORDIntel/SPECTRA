# SPECTRA Advanced Features

This directory contains comprehensive documentation and demonstration of SPECTRA's advanced features:

1. **Vector Database Integration** - Semantic search using QIHSE
2. **CNSA 2.0 Post-Quantum Cryptography** - Quantum-resistant encryption and signatures
3. **Temporal Analysis** - Activity pattern detection and timezone inference
4. **Attribution Engine** - Writing style analysis and cross-platform correlation

## Quick Start

Run the demonstration script:

```bash
python examples/advanced_features/demo.py
```

## Configuration

Advanced features are controlled via `spectra_config.json`. See `config/example_advanced_config.json` for a complete example.

Enable features by adding the `advanced_features` section to your configuration:

```json
{
  "advanced_features": {
    "enabled": true,
    "vector_database": {
      "backend": "qihse",
      "auto_index_messages": true
    },
    "cnsa_crypto": {
      "enabled": true
    },
    "threat_analysis": {
      "temporal_analysis": true,
      "attribution_engine": true
    }
  }
}
```

## Documentation

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System architecture and data flow
- **[VECTOR_DATABASE.md](docs/VECTOR_DATABASE.md)** - Vector storage and semantic search
- **[CNSA_CRYPTOGRAPHY.md](docs/CNSA_CRYPTOGRAPHY.md)** - Post-quantum cryptography
- **[TEMPORAL_ANALYSIS.md](docs/TEMPORAL_ANALYSIS.md)** - Activity pattern analysis
- **[ATTRIBUTION_ENGINE.md](docs/ATTRIBUTION_ENGINE.md)** - Cross-platform correlation

## Integration

These features are automatically integrated into SPECTRA's archiving workflow when enabled in configuration. Messages are automatically indexed for semantic search, and threat analysis runs in the background during archiving operations.

## Requirements

Install advanced feature dependencies:

```bash
pip install -r requirements-advanced.txt
```

Key dependencies:
- `sentence-transformers` - For embedding generation
- `liboqs-python` - For CNSA 2.0 cryptography
- `cryptography` - For key management
- QIHSE library - For vector search acceleration
