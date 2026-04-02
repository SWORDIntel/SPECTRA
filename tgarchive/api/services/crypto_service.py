"""
Crypto Service
==============

Service layer for cryptographic operations (CNSA 2.0).
"""

import logging
from typing import Dict, Any, Optional
import base64

try:
    from ...crypto.pqc import CNSA20CryptoManager, CNSAKeyPair
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("CNSA 2.0 crypto not available")

logger = logging.getLogger(__name__)


class CryptoService:
    """Service for cryptographic operations."""
    
    def __init__(self):
        if CRYPTO_AVAILABLE:
            self.crypto_manager = CNSA20CryptoManager()
        else:
            self.crypto_manager = None
    
    async def generate_kem_keypair(
        self,
        key_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate ML-KEM-1024 keypair.
        
        Args:
            key_id: Optional key identifier
            
        Returns:
            Keypair information
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            keypair = self.crypto_manager.generate_kem_keypair(key_id=key_id)
            
            return {
                "key_id": keypair.key_id,
                "algorithm": keypair.algorithm,
                "public_key": base64.b64encode(keypair.public_key).decode('utf-8'),
                "secret_key": base64.b64encode(keypair.secret_key).decode('utf-8'),
                "created": keypair.created
            }
        except Exception as e:
            logger.error(f"KEM keypair generation failed: {e}", exc_info=True)
            raise
    
    async def encapsulate(
        self,
        public_key_b64: str
    ) -> Dict[str, Any]:
        """
        Encapsulate shared secret.
        
        Args:
            public_key_b64: Base64-encoded public key
            
        Returns:
            Encapsulated key and shared secret
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            public_key = base64.b64decode(public_key_b64)
            kem_ciphertext, shared_secret = self.crypto_manager.encapsulate(public_key)
            
            return {
                "kem_ciphertext": base64.b64encode(kem_ciphertext).decode('utf-8'),
                "shared_secret": base64.b64encode(shared_secret).decode('utf-8')
            }
        except Exception as e:
            logger.error(f"Encapsulation failed: {e}", exc_info=True)
            raise
    
    async def decapsulate(
        self,
        kem_ciphertext_b64: str,
        secret_key_b64: str
    ) -> Dict[str, Any]:
        """
        Decapsulate shared secret.
        
        Args:
            kem_ciphertext_b64: Base64-encoded KEM ciphertext
            secret_key_b64: Base64-encoded secret key
            
        Returns:
            Decapsulated shared secret
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            kem_ciphertext = base64.b64decode(kem_ciphertext_b64)
            secret_key = base64.b64decode(secret_key_b64)
            shared_secret = self.crypto_manager.decapsulate(kem_ciphertext, secret_key)
            
            return {
                "shared_secret": base64.b64encode(shared_secret).decode('utf-8')
            }
        except Exception as e:
            logger.error(f"Decapsulation failed: {e}", exc_info=True)
            raise
    
    async def generate_signature_keypair(
        self,
        key_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate ML-DSA-87 signature keypair.
        
        Args:
            key_id: Optional key identifier
            
        Returns:
            Keypair information
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            keypair = self.crypto_manager.generate_signature_keypair(key_id=key_id)
            
            return {
                "key_id": keypair.key_id,
                "algorithm": keypair.algorithm,
                "public_key": base64.b64encode(keypair.public_key).decode('utf-8'),
                "secret_key": base64.b64encode(keypair.secret_key).decode('utf-8'),
                "created": keypair.created
            }
        except Exception as e:
            logger.error(f"Signature keypair generation failed: {e}", exc_info=True)
            raise
    
    async def sign(
        self,
        message_b64: str,
        secret_key_b64: str
    ) -> Dict[str, Any]:
        """
        Sign a message.
        
        Args:
            message_b64: Base64-encoded message
            secret_key_b64: Base64-encoded secret key
            
        Returns:
            Signature
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            message = base64.b64decode(message_b64)
            secret_key = base64.b64decode(secret_key_b64)
            signature = self.crypto_manager.sign(message, secret_key)
            
            return {
                "signature": base64.b64encode(signature).decode('utf-8')
            }
        except Exception as e:
            logger.error(f"Signing failed: {e}", exc_info=True)
            raise
    
    async def verify(
        self,
        message_b64: str,
        signature_b64: str,
        public_key_b64: str
    ) -> Dict[str, Any]:
        """
        Verify a signature.
        
        Args:
            message_b64: Base64-encoded message
            signature_b64: Base64-encoded signature
            public_key_b64: Base64-encoded public key
            
        Returns:
            Verification result
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            message = base64.b64decode(message_b64)
            signature = base64.b64decode(signature_b64)
            public_key = base64.b64decode(public_key_b64)
            is_valid = self.crypto_manager.verify(message, signature, public_key)
            
            return {
                "valid": is_valid
            }
        except Exception as e:
            logger.error(f"Verification failed: {e}", exc_info=True)
            raise
    
    async def encrypt_data(
        self,
        plaintext_b64: str,
        recipient_public_key_b64: str
    ) -> Dict[str, Any]:
        """
        Encrypt data using hybrid ML-KEM-1024 + AES-256-GCM.
        
        Args:
            plaintext_b64: Base64-encoded plaintext
            recipient_public_key_b64: Base64-encoded recipient public key
            
        Returns:
            Encrypted package
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            plaintext = base64.b64decode(plaintext_b64)
            recipient_public_key = base64.b64decode(recipient_public_key_b64)
            encrypted = self.crypto_manager.encrypt_data(plaintext, recipient_public_key)
            
            return {
                "kem_ciphertext": base64.b64encode(encrypted.kem_ciphertext).decode('utf-8'),
                "aes_ciphertext": base64.b64encode(encrypted.aes_ciphertext).decode('utf-8'),
                "nonce": base64.b64encode(encrypted.nonce).decode('utf-8'),
                "algorithm": encrypted.algorithm,
                "timestamp": encrypted.timestamp
            }
        except Exception as e:
            logger.error(f"Encryption failed: {e}", exc_info=True)
            raise
    
    async def decrypt_data(
        self,
        encrypted_package: Dict[str, Any],
        recipient_secret_key_b64: str
    ) -> Dict[str, Any]:
        """
        Decrypt data.
        
        Args:
            encrypted_package: Encrypted package dictionary
            recipient_secret_key_b64: Base64-encoded recipient secret key
            
        Returns:
            Decrypted plaintext
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            from ...crypto.pqc import EncryptedPackage
            
            encrypted = EncryptedPackage(
                kem_ciphertext=base64.b64decode(encrypted_package["kem_ciphertext"]),
                aes_ciphertext=base64.b64decode(encrypted_package["aes_ciphertext"]),
                nonce=base64.b64decode(encrypted_package["nonce"]),
                algorithm=encrypted_package.get("algorithm", ""),
                timestamp=encrypted_package.get("timestamp", "")
            )
            
            recipient_secret_key = base64.b64decode(recipient_secret_key_b64)
            plaintext = self.crypto_manager.decrypt_data(encrypted, recipient_secret_key)
            
            return {
                "plaintext": base64.b64encode(plaintext).decode('utf-8')
            }
        except Exception as e:
            logger.error(f"Decryption failed: {e}", exc_info=True)
            raise
    
    async def get_algorithm_info(self) -> Dict[str, Any]:
        """
        Get information about configured algorithms.
        
        Returns:
            Algorithm information
        """
        if not self.crypto_manager:
            return {"error": "Crypto manager not available"}
        
        try:
            info = self.crypto_manager.get_algorithm_info()
            return info
        except Exception as e:
            logger.error(f"Failed to get algorithm info: {e}", exc_info=True)
            raise
