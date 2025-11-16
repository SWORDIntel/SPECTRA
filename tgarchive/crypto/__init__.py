"""
SPECTRA Cryptographic Module

CNSA 2.0 compliant cryptography with post-quantum algorithms:
- ML-KEM-1024 (FIPS 203) - Key encapsulation
- ML-DSA-87 (FIPS 204) - Digital signatures
- SHA-384 (FIPS 180-4) - Hashing

Author: SPECTRA Intelligence System
"""

from typing import Optional

__all__ = [
    "CNSA20CryptoManager",
    "CNSAKeyPair",
    "CNSAKeyManager",
    "CNSA_AVAILABLE"
]

# Check availability of PQC libraries
try:
    import oqs
    CNSA_AVAILABLE = True
except ImportError:
    CNSA_AVAILABLE = False

# Import main classes if available
if CNSA_AVAILABLE:
    from .pqc import CNSA20CryptoManager, CNSAKeyPair
    from .key_manager import CNSAKeyManager
else:
    # Provide stub classes
    class CNSA20CryptoManager:
        def __init__(self):
            raise ImportError(
                "liboqs-python not installed. Install with: pip install liboqs-python"
            )

    class CNSAKeyPair:
        pass

    class CNSAKeyManager:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "liboqs-python not installed. Install with: pip install liboqs-python"
            )
