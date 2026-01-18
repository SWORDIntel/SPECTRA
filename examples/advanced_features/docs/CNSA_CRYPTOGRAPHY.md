# CNSA 2.0 Post-Quantum Cryptography

## Overview

SPECTRA implements **CNSA 2.0 (Commercial National Security Algorithm Suite 2.0)** for quantum-resistant cryptography. This ensures protection against future quantum computing attacks.

## CNSA 2.0 Algorithms

### Key Exchange: ML-KEM-1024

- **Standard**: FIPS 203 (formerly CRYSTALS-Kyber)
- **Security Level**: NIST Level 5 (256-bit quantum security)
- **Key Size**: 1568 bytes (public), 3168 bytes (secret)
- **Use Case**: Encrypting archives and sensitive data

### Digital Signatures: ML-DSA-87

- **Standard**: FIPS 204 (formerly CRYSTALS-Dilithium)
- **Parameter Set**: Dilithium5 (highest security)
- **Key Size**: 2592 bytes (public), 4864 bytes (secret)
- **Use Case**: Signing threat intelligence reports

### Hashing: SHA-384

- **Standard**: FIPS 180-4
- **Hash Size**: 384 bits (48 bytes)
- **Collision Resistance**: 192-bit quantum security
- **Use Case**: Integrity verification, checksums

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│         SPECTRA Crypto Layer (CNSA 2.0)                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  ML-KEM-1024│  │  ML-DSA-87   │  │   SHA-384    │  │
│  │   (PQC KEM) │  │ (PQC Sigs)   │  │   (Hashing)  │  │
│  └─────────────┘  └──────────────┘  └──────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │      Hybrid Cryptography Layer                  │  │
│  │  (PQC + AES-256-GCM for data encryption)      │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Key Management Workflow

### 1. Key Generation

```python
from tgarchive.crypto import CNSA20CryptoManager

crypto = CNSA20CryptoManager()

# Generate KEM key pair (for encryption)
kem_keys = crypto.generate_kem_keypair()
# → CNSAKeyPair(public_key=..., secret_key=..., algorithm="ML-KEM-1024")

# Generate signature key pair (for signing)
sig_keys = crypto.generate_signature_keypair()
# → CNSAKeyPair(public_key=..., secret_key=..., algorithm="ML-DSA-87")
```

### 2. Secure Storage

```python
from tgarchive.crypto import CNSAKeyManager

key_manager = CNSAKeyManager("./data/keystore.enc")

# Create encrypted keystore
key_manager.create_keystore(
    password="SecurePassword123!@#",
    kem_key_id="master_kem",
    sig_key_id="master_sig"
)

# Store keys
key_manager.store_key("master_kem", kem_keys, password)
key_manager.store_key("master_sig", sig_keys, password)
```

### 3. Key Retrieval

```python
# Retrieve keys (requires password)
kem_keys = key_manager.get_key("master_kem", password)
sig_keys = key_manager.get_key("master_sig", password)
```

## Encryption/Decryption Process

### Encrypting Data

```python
# Encrypt archive data
plaintext = archive_data.encode('utf-8')
encrypted = crypto.encrypt_data(plaintext, kem_keys.public_key)

# Result structure:
{
    "kem_ciphertext": b"...",  # Encapsulated key (1568 bytes)
    "aes_ciphertext": b"...",  # Encrypted data
    "nonce": b"...",           # AES nonce (12 bytes)
    "algorithm": "ML-KEM-1024+AES-256-GCM"
}
```

**Process:**
1. **ML-KEM-1024**: Generate shared secret using recipient's public key
2. **Key Derivation**: Derive AES-256 key from shared secret (SHA-384)
3. **AES-256-GCM**: Encrypt data with derived key
4. **Package**: Combine KEM ciphertext + AES ciphertext + nonce

### Decrypting Data

```python
# Decrypt archive data
decrypted = crypto.decrypt_data(encrypted, kem_keys.secret_key)
# → b"original archive data"
```

**Process:**
1. **ML-KEM-1024**: Decapsulate to recover shared secret
2. **Key Derivation**: Derive AES-256 key from shared secret
3. **AES-256-GCM**: Decrypt data with derived key
4. **Return**: Original plaintext

## Digital Signatures

### Creating Signed Packages

```python
# Sign threat intelligence report
report_data = generate_report().encode('utf-8')
signed = crypto.create_signed_package(
    report_data,
    sig_keys.secret_key,
    signer_id="analyst_001"
)

# Result structure:
{
    "data": b"...",            # Original data
    "signature": b"...",       # ML-DSA-87 signature (2592 bytes)
    "hash_sha384": "...",      # SHA-384 hash (hex)
    "algorithm": "ML-DSA-87",
    "signer_id": "analyst_001",
    "timestamp": "2024-06-15T10:30:00Z"
}
```

### Verifying Signatures

```python
# Verify signed package
is_valid = crypto.verify_signed_package(signed, sig_keys.public_key)
# → True if valid, False otherwise
```

**Verification Process:**
1. **Hash Verification**: Compute SHA-384 of data, compare with stored hash
2. **Signature Verification**: Verify ML-DSA-87 signature
3. **Return**: True if both checks pass

## Integration with Archives

### Encrypted Archive Storage

```python
# During archiving
if config["advanced_features"]["cnsa_crypto"]["encrypt_archives"]:
    # Generate or retrieve encryption keys
    kem_keys = key_manager.get_key("archive_kem", password)
    
    # Encrypt archive data
    archive_data = serialize_messages(messages)
    encrypted = crypto.encrypt_data(archive_data, kem_keys.public_key)
    
    # Store encrypted archive
    save_encrypted_archive(encrypted, archive_id)
```

### Signed Reports

```python
# When generating threat reports
if config["advanced_features"]["cnsa_crypto"]["sign_reports"]:
    # Generate or retrieve signing keys
    sig_keys = key_manager.get_key("report_sig", password)
    
    # Sign report
    report = generate_executive_report(profiles)
    signed = crypto.create_signed_package(
        report.encode('utf-8'),
        sig_keys.secret_key,
        signer_id=current_user
    )
    
    # Store signed report
    save_signed_report(signed, report_id)
```

## Database Integrity

### SHA-384 Checksums

```python
# Compute table checksums
def compute_table_checksum(table_name: str) -> str:
    data = export_table_data(table_name)
    return crypto.hash_hex(data.encode('utf-8'))

# Verify integrity
checksums = {
    "messages": compute_table_checksum("messages"),
    "users": compute_table_checksum("users"),
    "threat_scores": compute_table_checksum("threat_scores")
}

# Store checksums for later verification
store_integrity_checksums(checksums)
```

## Configuration

```json
{
  "advanced_features": {
    "cnsa_crypto": {
      "enabled": true,
      "encrypt_archives": false,
      "sign_reports": true,
      "keystore_path": "./data/keystore.enc",
      "key_rotation_days": 365
    }
  }
}
```

## Performance Characteristics

### ML-KEM-1024 Performance

- **Key Generation**: ~0.1-0.5 ms
- **Encapsulation**: ~0.1-0.5 ms
- **Decapsulation**: ~0.1-0.5 ms
- **Overhead**: Minimal for most operations

### ML-DSA-87 Performance

- **Key Generation**: ~0.5-2 ms
- **Signing**: ~1-5 ms
- **Verification**: ~0.5-2 ms
- **Overhead**: Acceptable for report signing

### SHA-384 Performance

- **Hashing**: ~100-500 MB/s (CPU dependent)
- **Overhead**: Negligible

## Security Considerations

### Key Storage

- **Encrypted Keystore**: Keys stored encrypted with user password
- **Access Control**: Only authorized users can access keys
- **Backup**: Secure backup of keystore required

### Key Rotation

- **Annual Rotation**: Recommended to rotate keys annually
- **Migration**: Old keys archived for historical decryption
- **Forward Secrecy**: New keys don't compromise old data

### Quantum Resistance

- **Future-Proof**: Protection against future quantum attacks
- **NIST Standards**: Compliant with FIPS 203/204
- **Security Level**: 256-bit quantum security

## Troubleshooting

### Key Generation Failures

- **Check liboqs-python**: Ensure library is installed
- **Verify Entropy**: System must have sufficient entropy
- **Check Permissions**: Ensure write access to keystore directory

### Encryption/Decryption Errors

- **Verify Keys**: Ensure correct key pair used
- **Check Data Format**: Ensure data is bytes, not string
- **Verify Algorithm**: Ensure consistent algorithm usage

### Signature Verification Failures

- **Check Public Key**: Ensure correct public key used
- **Verify Data Integrity**: Data may have been modified
- **Check Timestamp**: Signature may have expired
