"""
CNSA 2.0 Key Management

Secure storage and management of post-quantum cryptographic keys.

Features:
- Secure key storage (encrypted with password)
- Key rotation
- Key backup and recovery
- Key lifecycle management

Author: SPECTRA Intelligence System
"""

import os
import json
import base64
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

from .pqc import CNSA20CryptoManager, CNSAKeyPair


class CNSAKeyManager:
    """
    Secure management of CNSA 2.0 cryptographic keys.

    Stores keys encrypted with a user-provided password using:
    - PBKDF2 for password derivation
    - AES-256-GCM for key encryption
    - SHA-384 for integrity checks
    """

    def __init__(self, keystore_path: str):
        """
        Initialize key manager.

        Args:
            keystore_path: Path to encrypted keystore file
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            raise ImportError("cryptography library required for key management")

        self.keystore_path = Path(keystore_path)
        self.crypto = CNSA20CryptoManager()

        # Create directory if it doesn't exist
        self.keystore_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Key manager initialized: {self.keystore_path}")

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """
        Derive AES-256 key from password using PBKDF2.

        Args:
            password: User password
            salt: Random salt (16 bytes)

        Returns:
            32-byte AES key
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA384(),
            length=32,  # 256 bits
            salt=salt,
            iterations=600000  # OWASP recommended (2023)
        )
        return kdf.derive(password.encode('utf-8'))

    def _encrypt_keystore(self, data: bytes, password: str) -> Dict[str, str]:
        """
        Encrypt keystore data with password.

        Returns:
            Dictionary with encrypted data, salt, and nonce (base64)
        """
        # Generate random salt and nonce
        salt = os.urandom(16)
        nonce = os.urandom(12)

        # Derive encryption key from password
        aes_key = self._derive_key(password, salt)

        # Encrypt with AES-256-GCM
        aesgcm = AESGCM(aes_key)
        ciphertext = aesgcm.encrypt(nonce, data, None)

        return {
            "version": "1.0",
            "algorithm": "PBKDF2-SHA384+AES-256-GCM",
            "salt": base64.b64encode(salt).decode('ascii'),
            "nonce": base64.b64encode(nonce).decode('ascii'),
            "ciphertext": base64.b64encode(ciphertext).decode('ascii'),
            "created": datetime.now(timezone.utc).isoformat()
        }

    def _decrypt_keystore(self, encrypted_data: Dict[str, str], password: str) -> bytes:
        """
        Decrypt keystore data with password.

        Args:
            encrypted_data: Dictionary from _encrypt_keystore()
            password: User password

        Returns:
            Decrypted data

        Raises:
            ValueError: If password is incorrect
        """
        # Decode base64
        salt = base64.b64decode(encrypted_data["salt"])
        nonce = base64.b64decode(encrypted_data["nonce"])
        ciphertext = base64.b64decode(encrypted_data["ciphertext"])

        # Derive decryption key
        aes_key = self._derive_key(password, salt)

        # Decrypt
        aesgcm = AESGCM(aes_key)
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext
        except Exception as e:
            raise ValueError("Invalid password or corrupted keystore") from e

    def create_keystore(
        self,
        password: str,
        kem_key_id: str = "master_kem",
        sig_key_id: str = "master_sig"
    ):
        """
        Create new keystore with master keys.

        Args:
            password: Password to encrypt keystore
            kem_key_id: Identifier for KEM key pair
            sig_key_id: Identifier for signature key pair
        """
        if self.keystore_path.exists():
            raise FileExistsError(f"Keystore already exists: {self.keystore_path}")

        # Generate master keys
        logger.info("Generating master key pairs...")
        kem_keys = self.crypto.generate_kem_keypair(key_id=kem_key_id)
        sig_keys = self.crypto.generate_signature_keypair(key_id=sig_key_id)

        # Create keystore data
        keystore_data = {
            "version": "1.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "compliance": "CNSA 2.0",
            "keys": {
                kem_key_id: {
                    "type": "KEM",
                    "algorithm": kem_keys.algorithm,
                    "public_key": base64.b64encode(kem_keys.public_key).decode('ascii'),
                    "secret_key": base64.b64encode(kem_keys.secret_key).decode('ascii'),
                    "created": kem_keys.created,
                    "status": "active"
                },
                sig_key_id: {
                    "type": "SIGNATURE",
                    "algorithm": sig_keys.algorithm,
                    "public_key": base64.b64encode(sig_keys.public_key).decode('ascii'),
                    "secret_key": base64.b64encode(sig_keys.secret_key).decode('ascii'),
                    "created": sig_keys.created,
                    "status": "active"
                }
            },
            "metadata": {
                "last_rotation": None,
                "rotation_interval_days": 365  # Recommended annual rotation
            }
        }

        # Serialize and encrypt
        keystore_json = json.dumps(keystore_data, indent=2)
        encrypted = self._encrypt_keystore(keystore_json.encode('utf-8'), password)

        # Save to file
        with open(self.keystore_path, 'w') as f:
            json.dump(encrypted, f, indent=2)

        logger.info(f"✓ Keystore created: {self.keystore_path}")
        logger.info(f"  KEM key: {kem_key_id}")
        logger.info(f"  Signature key: {sig_key_id}")

    def load_keystore(self, password: str) -> Dict[str, Any]:
        """
        Load and decrypt keystore.

        Args:
            password: Keystore password

        Returns:
            Keystore data dictionary

        Raises:
            FileNotFoundError: If keystore doesn't exist
            ValueError: If password is incorrect
        """
        if not self.keystore_path.exists():
            raise FileNotFoundError(f"Keystore not found: {self.keystore_path}")

        # Load encrypted keystore
        with open(self.keystore_path, 'r') as f:
            encrypted_data = json.load(f)

        # Decrypt
        keystore_json = self._decrypt_keystore(encrypted_data, password)
        keystore_data = json.loads(keystore_json)

        logger.info(f"✓ Keystore loaded: {len(keystore_data['keys'])} keys")
        return keystore_data

    def get_key(self, password: str, key_id: str) -> CNSAKeyPair:
        """
        Retrieve a specific key pair from keystore.

        Args:
            password: Keystore password
            key_id: Key identifier

        Returns:
            CNSAKeyPair

        Raises:
            KeyError: If key not found
        """
        keystore = self.load_keystore(password)

        if key_id not in keystore["keys"]:
            raise KeyError(f"Key not found: {key_id}")

        key_data = keystore["keys"][key_id]

        return CNSAKeyPair(
            public_key=base64.b64decode(key_data["public_key"]),
            secret_key=base64.b64decode(key_data["secret_key"]),
            algorithm=key_data["algorithm"],
            created=key_data["created"],
            key_id=key_id
        )

    def add_key(
        self,
        password: str,
        key_id: str,
        key_type: str,  # "KEM" or "SIGNATURE"
        key_pair: Optional[CNSAKeyPair] = None
    ):
        """
        Add a new key pair to keystore.

        Args:
            password: Keystore password
            key_id: Identifier for new key
            key_type: "KEM" or "SIGNATURE"
            key_pair: Optional pre-generated key pair (generates new if None)
        """
        # Load existing keystore
        keystore = self.load_keystore(password)

        if key_id in keystore["keys"]:
            raise ValueError(f"Key already exists: {key_id}")

        # Generate new key pair if not provided
        if key_pair is None:
            if key_type == "KEM":
                key_pair = self.crypto.generate_kem_keypair(key_id=key_id)
            elif key_type == "SIGNATURE":
                key_pair = self.crypto.generate_signature_keypair(key_id=key_id)
            else:
                raise ValueError(f"Invalid key type: {key_type}")

        # Add to keystore
        keystore["keys"][key_id] = {
            "type": key_type,
            "algorithm": key_pair.algorithm,
            "public_key": base64.b64encode(key_pair.public_key).decode('ascii'),
            "secret_key": base64.b64encode(key_pair.secret_key).decode('ascii'),
            "created": key_pair.created,
            "status": "active"
        }

        # Re-encrypt and save
        keystore_json = json.dumps(keystore, indent=2)
        encrypted = self._encrypt_keystore(keystore_json.encode('utf-8'), password)

        with open(self.keystore_path, 'w') as f:
            json.dump(encrypted, f, indent=2)

        logger.info(f"✓ Added key: {key_id} ({key_type})")

    def rotate_key(self, password: str, key_id: str):
        """
        Rotate a key pair (archive old, generate new).

        Args:
            password: Keystore password
            key_id: Key to rotate
        """
        keystore = self.load_keystore(password)

        if key_id not in keystore["keys"]:
            raise KeyError(f"Key not found: {key_id}")

        old_key = keystore["keys"][key_id]

        # Archive old key
        archive_id = f"{key_id}_archived_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        keystore["keys"][archive_id] = {
            **old_key,
            "status": "archived",
            "archived": datetime.now(timezone.utc).isoformat()
        }

        # Generate new key
        key_type = old_key["type"]
        if key_type == "KEM":
            new_key = self.crypto.generate_kem_keypair(key_id=key_id)
        else:
            new_key = self.crypto.generate_signature_keypair(key_id=key_id)

        # Replace old key
        keystore["keys"][key_id] = {
            "type": key_type,
            "algorithm": new_key.algorithm,
            "public_key": base64.b64encode(new_key.public_key).decode('ascii'),
            "secret_key": base64.b64encode(new_key.secret_key).decode('ascii'),
            "created": new_key.created,
            "status": "active"
        }

        # Update metadata
        keystore["metadata"]["last_rotation"] = datetime.now(timezone.utc).isoformat()

        # Save
        keystore_json = json.dumps(keystore, indent=2)
        encrypted = self._encrypt_keystore(keystore_json.encode('utf-8'), password)

        with open(self.keystore_path, 'w') as f:
            json.dump(encrypted, f, indent=2)

        logger.info(f"✓ Rotated key: {key_id}")
        logger.info(f"  Old key archived as: {archive_id}")

    def list_keys(self, password: str) -> List[Dict[str, Any]]:
        """
        List all keys in keystore.

        Args:
            password: Keystore password

        Returns:
            List of key information dictionaries
        """
        keystore = self.load_keystore(password)

        keys = []
        for key_id, key_data in keystore["keys"].items():
            keys.append({
                "key_id": key_id,
                "type": key_data["type"],
                "algorithm": key_data["algorithm"],
                "created": key_data["created"],
                "status": key_data.get("status", "active")
            })

        return keys

    def export_public_keys(self, password: str, output_file: str):
        """
        Export public keys to a file (for sharing with others).

        Args:
            password: Keystore password
            output_file: Path to output file
        """
        keystore = self.load_keystore(password)

        public_keys = {
            "version": "1.0",
            "compliance": "CNSA 2.0",
            "exported": datetime.now(timezone.utc).isoformat(),
            "keys": {}
        }

        for key_id, key_data in keystore["keys"].items():
            if key_data.get("status") == "active":
                public_keys["keys"][key_id] = {
                    "type": key_data["type"],
                    "algorithm": key_data["algorithm"],
                    "public_key": key_data["public_key"],
                    "created": key_data["created"]
                }

        with open(output_file, 'w') as f:
            json.dump(public_keys, f, indent=2)

        logger.info(f"✓ Exported {len(public_keys['keys'])} public keys to: {output_file}")

    def backup_keystore(self, password: str, backup_path: str):
        """
        Create encrypted backup of keystore.

        Args:
            password: Keystore password
            backup_path: Path for backup file
        """
        import shutil

        # Verify password is correct by loading keystore
        self.load_keystore(password)

        # Copy encrypted keystore
        shutil.copy2(self.keystore_path, backup_path)

        logger.info(f"✓ Keystore backed up to: {backup_path}")


# Example usage
if __name__ == "__main__":
    print("=== CNSA 2.0 Key Management Demo ===\n")

    # Initialize key manager
    manager = CNSAKeyManager("./data/test_keystore.enc")

    # Create keystore with password
    password = "SecurePassword123!@#"

    try:
        manager.create_keystore(password)
        print("✓ Keystore created\n")

        # List keys
        keys = manager.list_keys(password)
        print("Keys in keystore:")
        for key in keys:
            print(f"  - {key['key_id']}: {key['type']} ({key['algorithm']})")
        print()

        # Retrieve a key
        kem_key = manager.get_key(password, "master_kem")
        print(f"✓ Retrieved KEM key: {kem_key.key_id}")
        print(f"  Public key size: {len(kem_key.public_key)} bytes\n")

        # Add new key
        manager.add_key(password, "operational_kem", "KEM")
        print("✓ Added operational KEM key\n")

        # Export public keys
        manager.export_public_keys(password, "./data/public_keys.json")
        print("✓ Exported public keys\n")

        # Backup
        manager.backup_keystore(password, "./data/keystore_backup.enc")
        print("✓ Created backup\n")

        print("=== Key management demo complete! ===")

    except Exception as e:
        print(f"ERROR: {e}")
