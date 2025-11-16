"""
Post-Quantum Cryptography Implementation (CNSA 2.0)

Implements NIST-standardized post-quantum algorithms:
- ML-KEM-1024 (Module-Lattice-Based Key Encapsulation) - FIPS 203
- ML-DSA-87 (Module-Lattice-Based Digital Signatures) - FIPS 204
- SHA-384 (Secure Hash Algorithm) - FIPS 180-4

These algorithms are quantum-resistant and approved for NSA CNSA 2.0 compliance.

Author: SPECTRA Intelligence System
"""

import os
import hashlib
import logging
from dataclasses import dataclass
from typing import Tuple, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Try to import liboqs (Open Quantum Safe)
try:
    from oqs import KeyEncapsulation, Signature
    OQS_AVAILABLE = True
except ImportError:
    OQS_AVAILABLE = False
    logger.warning("liboqs-python not available. Install with: pip install liboqs-python")

# Import cryptography for AES-GCM
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    logger.warning("cryptography not available. Install with: pip install cryptography")


@dataclass
class CNSAKeyPair:
    """CNSA 2.0 compliant key pair."""
    public_key: bytes
    secret_key: bytes
    algorithm: str  # "ML-KEM-1024" or "ML-DSA-87"
    created: str  # ISO 8601 timestamp
    key_id: Optional[str] = None  # Optional key identifier


@dataclass
class EncryptedPackage:
    """Encrypted data package."""
    kem_ciphertext: bytes  # Encapsulated shared secret
    aes_ciphertext: bytes  # Encrypted data
    nonce: bytes  # AES-GCM nonce
    algorithm: str  # Crypto algorithm used
    timestamp: str  # When encrypted


@dataclass
class SignedPackage:
    """Digitally signed data package."""
    data: bytes  # Original data
    signature: bytes  # ML-DSA-87 signature
    hash_sha384: str  # SHA-384 hash (hex)
    algorithm: str  # Signature algorithm
    timestamp: str  # When signed
    signer_id: Optional[str] = None  # Optional signer identifier


class CNSA20CryptoManager:
    """
    CNSA 2.0 compliant cryptographic operations.

    Provides post-quantum cryptography for:
    - Encryption (ML-KEM-1024 + AES-256-GCM hybrid)
    - Digital signatures (ML-DSA-87)
    - Hashing (SHA-384)

    All operations are quantum-resistant per NSA guidelines.
    """

    def __init__(self):
        if not OQS_AVAILABLE:
            raise ImportError(
                "liboqs-python is required for CNSA 2.0 cryptography.\n"
                "Install with: pip install liboqs-python"
            )

        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError(
                "cryptography library is required.\n"
                "Install with: pip install cryptography"
            )

        # CNSA 2.0 algorithm selections
        self.kem_algorithm = "ML-KEM-1024"  # FIPS 203 (formerly Kyber1024)
        self.sig_algorithm = "ML-DSA-87"    # FIPS 204 (formerly Dilithium5)
        self.hash_algorithm = "sha384"      # FIPS 180-4

        # Verify algorithms are available
        self._verify_algorithms()

        logger.info("CNSA 2.0 Crypto Manager initialized")
        logger.info(f"  - KEM: {self.kem_algorithm}")
        logger.info(f"  - Signature: {self.sig_algorithm}")
        logger.info(f"  - Hash: {self.hash_algorithm}")

    def _verify_algorithms(self):
        """Verify that required algorithms are available in liboqs."""
        # Check KEM algorithm
        if not KeyEncapsulation.is_kem_enabled(self.kem_algorithm):
            available_kems = KeyEncapsulation.get_enabled_KEM_mechanisms()
            raise ValueError(
                f"KEM algorithm '{self.kem_algorithm}' not available.\n"
                f"Available KEMs: {available_kems}"
            )

        # Check signature algorithm
        if not Signature.is_sig_enabled(self.sig_algorithm):
            available_sigs = Signature.get_enabled_sig_mechanisms()
            raise ValueError(
                f"Signature algorithm '{self.sig_algorithm}' not available.\n"
                f"Available signatures: {available_sigs}"
            )

        logger.debug("✓ All CNSA 2.0 algorithms verified as available")

    # ========================================================================
    # KEY ENCAPSULATION (ML-KEM-1024)
    # ========================================================================

    def generate_kem_keypair(self, key_id: Optional[str] = None) -> CNSAKeyPair:
        """
        Generate ML-KEM-1024 key pair for encryption.

        Returns:
            CNSAKeyPair with public and secret keys
        """
        kem = KeyEncapsulation(self.kem_algorithm)

        # Generate key pair
        public_key = kem.generate_keypair()
        secret_key = kem.export_secret_key()

        return CNSAKeyPair(
            public_key=public_key,
            secret_key=secret_key,
            algorithm=self.kem_algorithm,
            created=datetime.now(timezone.utc).isoformat(),
            key_id=key_id
        )

    def encapsulate(self, public_key: bytes) -> Tuple[bytes, bytes]:
        """
        Encapsulate a shared secret using recipient's public key.

        Args:
            public_key: Recipient's ML-KEM-1024 public key

        Returns:
            (kem_ciphertext, shared_secret)
            - kem_ciphertext: Encapsulated key (send to recipient)
            - shared_secret: Shared secret (use for encryption)
        """
        kem = KeyEncapsulation(self.kem_algorithm)
        ciphertext, shared_secret = kem.encap_secret(public_key)
        return ciphertext, shared_secret

    def decapsulate(self, kem_ciphertext: bytes, secret_key: bytes) -> bytes:
        """
        Decapsulate to recover shared secret.

        Args:
            kem_ciphertext: Encapsulated key from sender
            secret_key: Recipient's ML-KEM-1024 secret key

        Returns:
            shared_secret: Recovered shared secret
        """
        kem = KeyEncapsulation(self.kem_algorithm, secret_key)
        shared_secret = kem.decap_secret(kem_ciphertext)
        return shared_secret

    # ========================================================================
    # DIGITAL SIGNATURES (ML-DSA-87)
    # ========================================================================

    def generate_signature_keypair(self, key_id: Optional[str] = None) -> CNSAKeyPair:
        """
        Generate ML-DSA-87 key pair for signing.

        Returns:
            CNSAKeyPair with public and secret keys
        """
        signer = Signature(self.sig_algorithm)

        # Generate key pair
        public_key = signer.generate_keypair()
        secret_key = signer.export_secret_key()

        return CNSAKeyPair(
            public_key=public_key,
            secret_key=secret_key,
            algorithm=self.sig_algorithm,
            created=datetime.now(timezone.utc).isoformat(),
            key_id=key_id
        )

    def sign(self, message: bytes, secret_key: bytes) -> bytes:
        """
        Sign a message with ML-DSA-87.

        Args:
            message: Data to sign
            secret_key: Signer's ML-DSA-87 secret key

        Returns:
            signature: Digital signature
        """
        signer = Signature(self.sig_algorithm, secret_key)
        signature = signer.sign(message)
        return signature

    def verify(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        """
        Verify ML-DSA-87 signature.

        Args:
            message: Original data
            signature: Digital signature to verify
            public_key: Signer's ML-DSA-87 public key

        Returns:
            True if signature is valid, False otherwise
        """
        verifier = Signature(self.sig_algorithm)
        try:
            is_valid = verifier.verify(message, signature, public_key)
            return is_valid
        except Exception as e:
            logger.warning(f"Signature verification failed: {e}")
            return False

    # ========================================================================
    # HASHING (SHA-384)
    # ========================================================================

    def hash(self, data: bytes) -> bytes:
        """
        Compute SHA-384 hash.

        Args:
            data: Data to hash

        Returns:
            Hash digest (48 bytes)
        """
        return hashlib.sha384(data).digest()

    def hash_hex(self, data: bytes) -> str:
        """
        Compute SHA-384 hash (hex string).

        Args:
            data: Data to hash

        Returns:
            Hash digest as hex string
        """
        return hashlib.sha384(data).hexdigest()

    def hash_file(self, file_path: str) -> str:
        """
        Compute SHA-384 hash of a file.

        Args:
            file_path: Path to file

        Returns:
            Hash digest as hex string
        """
        sha384 = hashlib.sha384()

        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha384.update(chunk)

        return sha384.hexdigest()

    # ========================================================================
    # HYBRID ENCRYPTION (ML-KEM-1024 + AES-256-GCM)
    # ========================================================================

    def encrypt_data(
        self,
        plaintext: bytes,
        recipient_public_key: bytes
    ) -> EncryptedPackage:
        """
        Encrypt data using hybrid ML-KEM-1024 + AES-256-GCM.

        Process:
        1. Use ML-KEM-1024 to establish quantum-resistant shared secret
        2. Derive AES-256 key from shared secret using SHA-384
        3. Encrypt data with AES-256-GCM

        Args:
            plaintext: Data to encrypt
            recipient_public_key: Recipient's ML-KEM-1024 public key

        Returns:
            EncryptedPackage with all components needed for decryption
        """
        # Step 1: Encapsulate shared secret with ML-KEM-1024
        kem_ciphertext, shared_secret = self.encapsulate(recipient_public_key)

        # Step 2: Derive AES-256 key from shared secret using SHA-384
        # Use first 256 bits (32 bytes) of SHA-384 hash
        aes_key = hashlib.sha384(shared_secret).digest()[:32]

        # Step 3: Encrypt with AES-256-GCM
        aesgcm = AESGCM(aes_key)
        nonce = os.urandom(12)  # 96-bit nonce for GCM mode
        aes_ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        return EncryptedPackage(
            kem_ciphertext=kem_ciphertext,
            aes_ciphertext=aes_ciphertext,
            nonce=nonce,
            algorithm=f"{self.kem_algorithm}+AES-256-GCM",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def decrypt_data(
        self,
        encrypted_package: EncryptedPackage,
        recipient_secret_key: bytes
    ) -> bytes:
        """
        Decrypt data using hybrid ML-KEM-1024 + AES-256-GCM.

        Args:
            encrypted_package: Encrypted data package
            recipient_secret_key: Recipient's ML-KEM-1024 secret key

        Returns:
            plaintext: Decrypted data
        """
        # Step 1: Decapsulate to recover shared secret
        shared_secret = self.decapsulate(
            encrypted_package.kem_ciphertext,
            recipient_secret_key
        )

        # Step 2: Derive AES-256 key (same as encryption)
        aes_key = hashlib.sha384(shared_secret).digest()[:32]

        # Step 3: Decrypt with AES-256-GCM
        aesgcm = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(
            encrypted_package.nonce,
            encrypted_package.aes_ciphertext,
            None
        )

        return plaintext

    # ========================================================================
    # SIGNED DATA PACKAGES
    # ========================================================================

    def create_signed_package(
        self,
        data: bytes,
        signing_key: bytes,
        signer_id: Optional[str] = None
    ) -> SignedPackage:
        """
        Create a signed data package with integrity verification.

        Args:
            data: Data to sign
            signing_key: Signer's ML-DSA-87 secret key
            signer_id: Optional identifier for signer

        Returns:
            SignedPackage with data, signature, and hash
        """
        # Compute SHA-384 hash
        data_hash = self.hash_hex(data)

        # Sign the data with ML-DSA-87
        signature = self.sign(data, signing_key)

        return SignedPackage(
            data=data,
            signature=signature,
            hash_sha384=data_hash,
            algorithm=self.sig_algorithm,
            timestamp=datetime.now(timezone.utc).isoformat(),
            signer_id=signer_id
        )

    def verify_signed_package(
        self,
        signed_package: SignedPackage,
        public_key: bytes
    ) -> bool:
        """
        Verify signed package integrity and authenticity.

        Checks:
        1. Data integrity (SHA-384 hash matches)
        2. Signature validity (ML-DSA-87 verification)

        Args:
            signed_package: Package to verify
            public_key: Signer's ML-DSA-87 public key

        Returns:
            True if valid and authentic, False otherwise
        """
        # Check hash integrity
        computed_hash = self.hash_hex(signed_package.data)
        if computed_hash != signed_package.hash_sha384:
            logger.warning("Hash mismatch - data may be corrupted or tampered")
            return False

        # Verify signature
        is_valid = self.verify(
            signed_package.data,
            signed_package.signature,
            public_key
        )

        if not is_valid:
            logger.warning("Invalid signature - authenticity cannot be verified")

        return is_valid

    # ========================================================================
    # COMBINED OPERATIONS
    # ========================================================================

    def encrypt_and_sign(
        self,
        data: bytes,
        recipient_kem_public_key: bytes,
        sender_sig_secret_key: bytes,
        sender_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Encrypt data and sign the encrypted package.

        Provides both confidentiality (encryption) and authenticity (signature).

        Args:
            data: Data to protect
            recipient_kem_public_key: Recipient's ML-KEM-1024 public key
            sender_sig_secret_key: Sender's ML-DSA-87 secret key
            sender_id: Optional sender identifier

        Returns:
            Dictionary with encrypted and signed package
        """
        # Encrypt the data
        encrypted = self.encrypt_data(data, recipient_kem_public_key)

        # Sign the encrypted package (sign the ciphertext + nonce)
        package_to_sign = encrypted.kem_ciphertext + encrypted.aes_ciphertext + encrypted.nonce
        signature = self.sign(package_to_sign, sender_sig_secret_key)

        return {
            "encrypted": encrypted,
            "signature": signature,
            "sender_id": sender_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def verify_and_decrypt(
        self,
        signed_encrypted_package: Dict[str, Any],
        recipient_kem_secret_key: bytes,
        sender_sig_public_key: bytes
    ) -> Optional[bytes]:
        """
        Verify signature and decrypt data.

        Args:
            signed_encrypted_package: Package from encrypt_and_sign()
            recipient_kem_secret_key: Recipient's ML-KEM-1024 secret key
            sender_sig_public_key: Sender's ML-DSA-87 public key

        Returns:
            Decrypted data if valid, None if signature verification fails
        """
        encrypted: EncryptedPackage = signed_encrypted_package["encrypted"]
        signature: bytes = signed_encrypted_package["signature"]

        # Verify signature first
        package_to_verify = encrypted.kem_ciphertext + encrypted.aes_ciphertext + encrypted.nonce
        if not self.verify(package_to_verify, signature, sender_sig_public_key):
            logger.error("Signature verification failed - rejecting package")
            return None

        # Signature valid, proceed with decryption
        plaintext = self.decrypt_data(encrypted, recipient_kem_secret_key)
        return plaintext

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def get_algorithm_info(self) -> Dict[str, Any]:
        """Get information about configured algorithms."""
        return {
            "kem": {
                "algorithm": self.kem_algorithm,
                "standard": "FIPS 203",
                "security_level": "NIST Level 5 (256-bit quantum)",
                "public_key_size": len(self.generate_kem_keypair().public_key),
                "secret_key_size": len(self.generate_kem_keypair().secret_key)
            },
            "signature": {
                "algorithm": self.sig_algorithm,
                "standard": "FIPS 204",
                "security_level": "NIST Level 5 (256-bit quantum)",
                "public_key_size": len(self.generate_signature_keypair().public_key),
                "secret_key_size": len(self.generate_signature_keypair().secret_key)
            },
            "hash": {
                "algorithm": self.hash_algorithm.upper(),
                "standard": "FIPS 180-4",
                "output_size": 48  # 384 bits = 48 bytes
            },
            "compliance": "CNSA 2.0",
            "quantum_resistant": True
        }


# Example usage
if __name__ == "__main__":
    print("=== CNSA 2.0 Cryptography Demo ===\n")

    try:
        # Initialize crypto manager
        crypto = CNSA20CryptoManager()

        # Show algorithm info
        info = crypto.get_algorithm_info()
        print("Algorithm Information:")
        print(f"  KEM: {info['kem']['algorithm']} ({info['kem']['standard']})")
        print(f"  Signature: {info['signature']['algorithm']} ({info['signature']['standard']})")
        print(f"  Hash: {info['hash']['algorithm']} ({info['hash']['standard']})")
        print(f"  Quantum Resistant: {info['quantum_resistant']}\n")

        # Generate key pairs
        print("Generating key pairs...")
        recipient_kem = crypto.generate_kem_keypair(key_id="recipient_001")
        sender_sig = crypto.generate_signature_keypair(key_id="sender_001")
        print(f"✓ KEM key pair generated (pub: {len(recipient_kem.public_key)} bytes)")
        print(f"✓ Signature key pair generated (pub: {len(sender_sig.public_key)} bytes)\n")

        # Test encryption
        plaintext = b"Classified intelligence data - Eyes Only"
        print(f"Encrypting: {plaintext.decode()}")

        encrypted = crypto.encrypt_data(plaintext, recipient_kem.public_key)
        print(f"✓ Encrypted with {encrypted.algorithm}")
        print(f"  KEM ciphertext: {len(encrypted.kem_ciphertext)} bytes")
        print(f"  AES ciphertext: {len(encrypted.aes_ciphertext)} bytes\n")

        # Test decryption
        decrypted = crypto.decrypt_data(encrypted, recipient_kem.secret_key)
        print(f"Decrypted: {decrypted.decode()}")
        print(f"✓ Decryption successful: {plaintext == decrypted}\n")

        # Test signing
        print("Creating signed package...")
        signed = crypto.create_signed_package(plaintext, sender_sig.secret_key, signer_id="analyst_007")
        print(f"✓ Signed with {signed.algorithm}")
        print(f"  Signature: {len(signed.signature)} bytes")
        print(f"  SHA-384: {signed.hash_sha384}\n")

        # Test verification
        print("Verifying signature...")
        is_valid = crypto.verify_signed_package(signed, sender_sig.public_key)
        print(f"✓ Signature valid: {is_valid}\n")

        # Test combined encrypt + sign
        print("Testing combined encrypt and sign...")
        combined = crypto.encrypt_and_sign(
            plaintext,
            recipient_kem.public_key,
            sender_sig.secret_key,
            sender_id="sender_001"
        )
        print("✓ Data encrypted and signed\n")

        # Test verify + decrypt
        print("Testing verify and decrypt...")
        decrypted2 = crypto.verify_and_decrypt(
            combined,
            recipient_kem.secret_key,
            sender_sig.public_key
        )
        print(f"✓ Verification and decryption successful: {decrypted2 == plaintext}\n")

        print("=== All CNSA 2.0 operations successful! ===")

    except ImportError as e:
        print(f"ERROR: {e}")
        print("\nTo use CNSA 2.0 cryptography, install:")
        print("  pip install liboqs-python cryptography")
