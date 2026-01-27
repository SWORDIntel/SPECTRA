"""
Crypto API Routes
=================

CNSA 2.0 cryptographic operations endpoints.
"""

import asyncio
import logging
from flask import request, jsonify

from . import crypto_bp
from ..security import require_auth, rate_limit
from ..services import CryptoService

logger = logging.getLogger(__name__)

# Global service instance
_crypto_service: CryptoService = None


def init_crypto_routes(app):
    """Initialize crypto routes with dependencies."""
    global _crypto_service
    
    _crypto_service = CryptoService()
    
    app.register_blueprint(crypto_bp, url_prefix='/api/crypto')


@crypto_bp.route('/kem/generate', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def generate_kem_keypair():
    """
    Generate ML-KEM-1024 keypair.
    
    Request JSON:
        {
            "key_id": "optional_key_id"
        }
    
    Returns:
        {
            "key_id": "...",
            "algorithm": "ML-KEM-1024",
            "public_key": "base64...",
            "secret_key": "base64..."
        }
    """
    try:
        data = request.get_json() or {}
        key_id = data.get('key_id')
        
        result = asyncio.run(_crypto_service.generate_kem_keypair(key_id))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"KEM keypair generation failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/kem/encapsulate', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def encapsulate():
    """
    Encapsulate shared secret.
    
    Request JSON:
        {
            "public_key": "base64..."
        }
    
    Returns:
        {
            "kem_ciphertext": "base64...",
            "shared_secret": "base64..."
        }
    """
    try:
        data = request.get_json() or {}
        public_key_b64 = data.get('public_key')
        
        if not public_key_b64:
            return jsonify({'error': 'public_key is required'}), 400
        
        result = asyncio.run(_crypto_service.encapsulate(public_key_b64))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Encapsulation failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/kem/decapsulate', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def decapsulate():
    """
    Decapsulate shared secret.
    
    Request JSON:
        {
            "kem_ciphertext": "base64...",
            "secret_key": "base64..."
        }
    
    Returns:
        {
            "shared_secret": "base64..."
        }
    """
    try:
        data = request.get_json() or {}
        kem_ciphertext_b64 = data.get('kem_ciphertext')
        secret_key_b64 = data.get('secret_key')
        
        if not kem_ciphertext_b64 or not secret_key_b64:
            return jsonify({'error': 'kem_ciphertext and secret_key are required'}), 400
        
        result = asyncio.run(_crypto_service.decapsulate(kem_ciphertext_b64, secret_key_b64))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Decapsulation failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/signature/generate', methods=['POST'])
@require_auth
@rate_limit(limit=10, per='user')
def generate_signature_keypair():
    """
    Generate ML-DSA-87 signature keypair.
    
    Request JSON:
        {
            "key_id": "optional_key_id"
        }
    
    Returns:
        {
            "key_id": "...",
            "algorithm": "ML-DSA-87",
            "public_key": "base64...",
            "secret_key": "base64..."
        }
    """
    try:
        data = request.get_json() or {}
        key_id = data.get('key_id')
        
        result = asyncio.run(_crypto_service.generate_signature_keypair(key_id))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Signature keypair generation failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/signature/sign', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def sign():
    """
    Sign a message.
    
    Request JSON:
        {
            "message": "base64...",
            "secret_key": "base64..."
        }
    
    Returns:
        {
            "signature": "base64..."
        }
    """
    try:
        data = request.get_json() or {}
        message_b64 = data.get('message')
        secret_key_b64 = data.get('secret_key')
        
        if not message_b64 or not secret_key_b64:
            return jsonify({'error': 'message and secret_key are required'}), 400
        
        result = asyncio.run(_crypto_service.sign(message_b64, secret_key_b64))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Signing failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/signature/verify', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def verify():
    """
    Verify a signature.
    
    Request JSON:
        {
            "message": "base64...",
            "signature": "base64...",
            "public_key": "base64..."
        }
    
    Returns:
        {
            "valid": true
        }
    """
    try:
        data = request.get_json() or {}
        message_b64 = data.get('message')
        signature_b64 = data.get('signature')
        public_key_b64 = data.get('public_key')
        
        if not all([message_b64, signature_b64, public_key_b64]):
            return jsonify({'error': 'message, signature, and public_key are required'}), 400
        
        result = asyncio.run(_crypto_service.verify(message_b64, signature_b64, public_key_b64))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/encrypt', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def encrypt_data():
    """
    Encrypt data using hybrid ML-KEM-1024 + AES-256-GCM.
    
    Request JSON:
        {
            "plaintext": "base64...",
            "recipient_public_key": "base64..."
        }
    
    Returns:
        {
            "kem_ciphertext": "base64...",
            "aes_ciphertext": "base64...",
            "nonce": "base64..."
        }
    """
    try:
        data = request.get_json() or {}
        plaintext_b64 = data.get('plaintext')
        recipient_public_key_b64 = data.get('recipient_public_key')
        
        if not plaintext_b64 or not recipient_public_key_b64:
            return jsonify({'error': 'plaintext and recipient_public_key are required'}), 400
        
        result = asyncio.run(_crypto_service.encrypt_data(plaintext_b64, recipient_public_key_b64))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Encryption failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/decrypt', methods=['POST'])
@require_auth
@rate_limit(limit=20, per='user')
def decrypt_data():
    """
    Decrypt data.
    
    Request JSON:
        {
            "encrypted_package": {
                "kem_ciphertext": "base64...",
                "aes_ciphertext": "base64...",
                "nonce": "base64..."
            },
            "recipient_secret_key": "base64..."
        }
    
    Returns:
        {
            "plaintext": "base64..."
        }
    """
    try:
        data = request.get_json() or {}
        encrypted_package = data.get('encrypted_package')
        recipient_secret_key_b64 = data.get('recipient_secret_key')
        
        if not encrypted_package or not recipient_secret_key_b64:
            return jsonify({'error': 'encrypted_package and recipient_secret_key are required'}), 400
        
        result = asyncio.run(_crypto_service.decrypt_data(encrypted_package, recipient_secret_key_b64))
        
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Decryption failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@crypto_bp.route('/algorithms', methods=['GET'])
@require_auth
@rate_limit(limit=50)
def get_algorithm_info():
    """
    Get information about configured algorithms.
    
    Returns:
        {
            "kem": {...},
            "signature": {...},
            "hash": {...}
        }
    """
    try:
        result = asyncio.run(_crypto_service.get_algorithm_info())
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Failed to get algorithm info: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
