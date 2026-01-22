---
id: 'cnsa-cryptography'
title: 'CNSA 2.0 Cryptography'
sidebar_position: 5
description: 'Post-quantum cryptography for future-proof security'
tags: ['cnsa', 'cryptography', 'security', 'features']
---

# CNSA 2.0 Quantum-Resistant Cryptography

Post-quantum cryptography for future-proof security.

See [CNSA 2.0 Security](../reference/security-cnsa.md) for complete security documentation.

## Standards Compliance

- **ML-KEM-1024** (FIPS 203): Quantum-resistant key encapsulation
- **ML-DSA-87** (FIPS 204): Quantum-resistant digital signatures
- **SHA-384** (FIPS 180-4): 384-bit secure hashing
- **NSA CNSA 2.0 Compliant**: Future-proof against quantum attacks

## Features

- Hybrid encryption (ML-KEM-1024 + AES-256-GCM)
- Digital signatures for threat reports (ML-DSA-87)
- Secure key management with encrypted keystore
- Archive encryption with quantum resistance
- Database integrity verification

## Usage

```python
from tgarchive.crypto import CNSA20CryptoManager

crypto = CNSA20CryptoManager()
kem_keys = crypto.generate_kem_keypair()
encrypted = crypto.encrypt_data(plaintext, recipient_public_key)
```
