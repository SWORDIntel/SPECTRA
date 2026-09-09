"""
MSNET (MEMSHADOW) Protocol v3 Python FFI Bindings
=================================================

Python ctypes wrapper for MSNET C library (libmemshadow.so) providing:
- Core binary protocol header packing/unpacking (32-byte header)
- HMAC-SHA384 message integrity verification
- PQC CSNA2.0 ZKP challenge-response handshake authentication
- Session management, timeout handling, and key rotation
- Peer management with health scoring, heartbeat tracking, and ban management
- PQC hybrid key generation and key exchange
- Epidemic gossip protocol for decentralized swarm node discovery
"""

import ctypes
import os
import sys
from ctypes import (
    c_void_p, c_size_t, c_double, c_float, c_uint8, c_uint16, c_uint32, c_uint64,
    c_bool, POINTER, Structure, c_int, byref, c_char_p, c_char, create_string_buffer
)
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Protocol Constants
MEMSHADOW_MAGIC = 0x4D53485700000000  # "MSHW" padded to 8 bytes
MEMSHADOW_VERSION_MAJOR = 3
MEMSHADOW_VERSION_MINOR = 0
MEMSHADOW_HEADER_SIZE = 32
MEMSHADOW_MAX_PAYLOAD_NORMAL = 16 * 1024 * 1024  # 16MB
MEMSHADOW_MAX_PAYLOAD_FILE_TRANSFER = 24 * 1024 * 1024  # 24MB

MEMSHADOW_SESSION_ID_SIZE = 32
MEMSHADOW_SESSION_KEY_SIZE = 32
MEMSHADOW_SESSION_MAX = 1024
MEMSHADOW_PEER_MAX = 256

# Message Types (memshadow_msg_type_t)
MSG_HEARTBEAT = 0x0001
MSG_ACK = 0x0002
MSG_NACK = 0x0003
MSG_ERROR = 0x0003
MSG_HANDSHAKE = 0x0004
MSG_DISCONNECT = 0x0005

MSG_PSYCH_ASSESSMENT = 0x0100
MSG_DARK_TRIAD_UPDATE = 0x0101
MSG_RISK_UPDATE = 0x0102
MSG_NEURO_UPDATE = 0x0103
MSG_TMI_UPDATE = 0x0104
MSG_COGARCH_UPDATE = 0x0105
MSG_COGNITIVE_UPDATE = 0x0105
MSG_FULL_PSYCH = 0x0106
MSG_PSYCH_THREAT_ALERT = 0x0110
MSG_PSYCH_ANOMALY = 0x0111
MSG_PSYCH_RISK_THRESHOLD = 0x0112

MSG_THREAT_REPORT = 0x0201
MSG_INTEL_REPORT = 0x0202
MSG_KNOWLEDGE_UPDATE = 0x0203
MSG_BRAIN_INTEL_REPORT = 0x0204
MSG_INTEL_PROPAGATE = 0x0205

MSG_MEMORY_STORE = 0x0301
MSG_MEMORY_QUERY = 0x0302
MSG_MEMORY_RESPONSE = 0x0303
MSG_MEMORY_SYNC = 0x0304
MSG_VECTOR_SYNC = 0x0305

MSG_NODE_REGISTER = 0x0401
MSG_NODE_DEREGISTER = 0x0402
MSG_QUERY_DISTRIBUTE = 0x0403
MSG_BRAIN_QUERY = 0x0403
MSG_QUERY_RESPONSE = 0x0404

MSG_IMPROVEMENT_ANNOUNCE = 0x0501
MSG_IMPROVEMENT_REQUEST = 0x0502
MSG_IMPROVEMENT_PAYLOAD = 0x0503
MSG_IMPROVEMENT_ACK = 0x0504
MSG_IMPROVEMENT_REJECT = 0x0505
MSG_IMPROVEMENT_METRICS = 0x0506

MSG_FILE_TRANSFER_START = 0x0601
MSG_FILE_TRANSFER_CHUNK = 0x0602
MSG_FILE_TRANSFER_END = 0x0603
MSG_FILE_TRANSFER_ABORT = 0x0604
MSG_FILE_TRANSFER_REQUEST = 0x0605

MSG_TELEMETRY = 0x0701
MSG_CONTROL = 0x0702
MSG_HEADER_ONLY = 0x0703
MSG_PAYLOAD_ONLY = 0x0704
MSG_DATA = 0x07FF

# Message Flags (memshadow_flags_t)
FLAG_NONE = 0x0000
FLAG_ENCRYPTED = 0x0001
FLAG_COMPRESSED = 0x0002
FLAG_BATCHED = 0x0004
FLAG_REQUIRES_ACK = 0x0008
FLAG_FRAGMENTED = 0x0010
FLAG_LAST_FRAGMENT = 0x0020
FLAG_FROM_KERNEL = 0x0040
FLAG_HIGH_CONFIDENCE = 0x0080
FLAG_HAS_EXTENSION = 0x0100
FLAG_ECC_ENABLED = 0x0200
FLAG_DUAL_STREAM = 0x0400
FLAG_TELEMETRY_MODE = 0x0800
FLAG_INTEGRITY_CHECK = 0x1000
FLAG_STEGANOGRAPHIC = 0x2000
FLAG_TRAFFIC_SHAPED = 0x4000
FLAG_QUANTUM_RESISTANT = 0x4000
FLAG_TEMPORAL_QUEUED = 0x8000
FLAG_QUANTUM_ENTANGLED = 0x10000
FLAG_MORPHIC_ADAPTED = 0x20000

# Priority Levels (memshadow_priority_t)
PRIORITY_LOW = 0
PRIORITY_NORMAL = 1
PRIORITY_HIGH = 2
PRIORITY_CRITICAL = 3
PRIORITY_EMERGENCY = 4
PRIORITY_LOWEST = PRIORITY_LOW

# Error Codes (memshadow_error_code_t)
ERR_INVALID_MAGIC = 0x0001
ERR_INVALID_VERSION = 0x0002
ERR_INVALID_HEADER = 0x0003
ERR_INVALID_PAYLOAD = 0x0004
ERR_INVALID_MESSAGE_TYPE = 0x0005
ERR_MESSAGE_TOO_LARGE = 0x0008
ERR_INVALID_SIGNATURE = 0x0101
ERR_AUTHENTICATION_FAILED = 0x0102
ERR_KEY_EXCHANGE_FAILED = 0x0106
ERR_PEER_NOT_FOUND = 0x0201
ERR_CONNECTION_FAILED = 0x0203
ERR_NAT_TRAVERSAL_FAILED = 0x0205
ERR_HANDSHAKE_TIMEOUT = 0x0301
ERR_VERSION_INCOMPATIBLE = 0x0306
ERR_RATE_LIMIT_EXCEEDED = 0x0401
ERR_FILE_TRANSFER_FAILED = 0x0601
ERR_COMPRESSION_FAILED = 0x0608
ERR_HARDWARE_UNAVAILABLE = 0x060A
ERR_INTERNAL_ERROR = 0x0A01

# Handshake States (memshadow_handshake_state_t)
HANDSHAKE_IDLE = 0
HANDSHAKE_HELLO_SENT = 1
HANDSHAKE_HELLO_ACK_SENT = 2
HANDSHAKE_CHALLENGE_RESPONSE_SENT = 3
HANDSHAKE_ESTABLISHED = 4
HANDSHAKE_FAILED = 5

# Handshake Steps (memshadow_handshake_step_t)
HANDSHAKE_STEP_HELLO = 0x01
HANDSHAKE_STEP_HELLO_ACK = 0x02
HANDSHAKE_STEP_CHALLENGE_RESPONSE = 0x03
HANDSHAKE_STEP_SESSION_ESTABLISHED = 0x04
HANDSHAKE_STEP_SESSION_REJECT = 0x05

# Capabilities
MEMSHADOW_CAP_PQC = 1 << 0
MEMSHADOW_CAP_VLAN_RELAY = 1 << 1
MEMSHADOW_CAP_DPI_EVASION = 1 << 2
MEMSHADOW_CAP_TRAFFIC_RESIST = 1 << 3
MEMSHADOW_CAP_COVERT_VLAN = 1 << 4
MEMSHADOW_CAP_HUB_FINGERPRINT = 1 << 5
MEMSHADOW_CAP_TLS_EXTENSIONS = 1 << 6
MEMSHADOW_CAP_GOSSIP = 1 << 7
MEMSHADOW_CAP_PFS = 1 << 8
MEMSHADOW_CAP_ZKP = 1 << 9
MEMSHADOW_CAP_TEMPORAL = 1 << 10
MEMSHADOW_CAP_QUANTUM_ENTANGLE = 1 << 11
MEMSHADOW_CAP_MORPHIC = 1 << 12
MEMSHADOW_CAP_RDMA = 1 << 13
MEMSHADOW_CAP_DUAL_STREAM = 1 << 14
MEMSHADOW_CAP_ECC = 1 << 15
MEMSHADOW_CAP_ALL = 0xFFFF

# Session States (memshadow_session_state_t)
SESSION_ACTIVE = 0
SESSION_IDLE = 1
SESSION_EXPIRED = 2
SESSION_CLOSING = 3

# Peer Statuses (memshadow_peer_status_t)
PEER_CONNECTED = 0
PEER_CONNECTING = 1
PEER_DISCONNECTED = 2
PEER_BANNED = 3
PEER_UNREACHABLE = 4

# Peer Selection Strategies (memshadow_selection_strategy_t)
SELECT_BEST_HEALTH = 0
SELECT_ROUND_ROBIN = 1
SELECT_RANDOM = 2
SELECT_LOWEST_LATENCY = 3
SELECT_HIGHEST_BANDWIDTH = 4

# PQC Algorithms (memshadow_pqc_algorithm_t)
PQC_ALGORITHM_CLASSICAL_ONLY = 0
PQC_ALGORITHM_HYBRID_X25519_KYBER = 1
PQC_ALGORITHM_HYBRID_ECDSA_DILITHIUM = 2
PQC_ALGORITHM_PQC_ONLY = 3
PQC_ALGORITHM_BFV_HOMOMORPHIC = 4
PQC_ALGORITHM_CKKS_HOMOMORPHIC = 5
PQC_ALGORITHM_TFHE_HOMOMORPHIC = 6
PQC_ALGORITHM_HYBRID_BFV_CLASSICAL = 7
PQC_ALGORITHM_HYBRID_CKKS_CLASSICAL = 8

# PQC Error Codes (memshadow_pqc_error_t)
PQC_SUCCESS = 0
PQC_ERROR_INVALID_ALGORITHM = -1
PQC_ERROR_INVALID_KEY = -2
PQC_ERROR_ENCRYPTION_FAILED = -3
PQC_ERROR_DECRYPTION_FAILED = -4
PQC_ERROR_OPERATION_FAILED = -5
PQC_ERROR_OUT_OF_MEMORY = -6
PQC_ERROR_INVALID_PARAMETERS = -7
PQC_ERROR_NOISE_BUDGET_EXHAUSTED = -8

# Gossip Message Types (memshadow_gossip_message_type_t)
GOSSIP_MSG_HEARTBEAT = 0
GOSSIP_MSG_PEER_DISCOVERY = 1
GOSSIP_MSG_ROUTE_UPDATE = 2
GOSSIP_MSG_DATA_BROADCAST = 3
GOSSIP_MSG_FAILURE_DETECTION = 4
GOSSIP_MSG_METADATA_SYNC = 5


# ============================================================================
# Ctypes Structure Definitions
# ============================================================================

class memshadow_header_t(Structure):
    """Protocol Header Structure (32 bytes binary layout)."""
    _fields_ = [
        ("magic", c_uint64),          # 8 bytes - Protocol magic (MEMSHADOW_MAGIC)
        ("version", c_uint16),        # 2 bytes - Protocol version (major << 8 | minor)
        ("priority", c_uint16),       # 2 bytes - Message priority
        ("msg_type", c_uint16),       # 2 bytes - Message type
        ("flags_batch", c_uint16),    # 2 bytes - Flags (low) + batch_count (high)
        ("payload_len", c_uint32),    # 4 bytes - Payload length
        ("timestamp_ns", c_uint64),   # 8 bytes - Nanosecond timestamp
        ("sequence_num", c_uint32),   # 4 bytes - Sequence number
    ]

MemshadowHeader = memshadow_header_t


class memshadow_version_t(Structure):
    """Protocol Version Structure."""
    _fields_ = [
        ("major", c_uint8),
        ("minor", c_uint8),
    ]

MemshadowVersion = memshadow_version_t


class memshadow_handshake_ctx_t(Structure):
    """Handshake Context Structure."""
    _fields_ = [
        ("state", c_int),                             # memshadow_handshake_state_t
        ("local_capabilities", c_uint32),             # Local capability bitmask
        ("peer_capabilities", c_uint32),              # Peer capability bitmask
        ("negotiated_capabilities", c_uint32),          # Negotiated capabilities
        ("local_version", c_uint16),                  # Local protocol version
        ("peer_version", c_uint16),                   # Peer protocol version
        ("challenge", c_uint8 * 32),                  # 32-byte challenge nonce
        ("session_id", c_uint8 * 16),                 # 16-byte session identifier
        ("session_key", c_uint8 * 32),                # 32-byte derived session key
        ("peer_node_id", c_char * 64),                # Peer node identifier string
        ("timeout_ms", c_uint32),                     # Handshake timeout in ms
        ("started_at_ns", c_uint64),                  # Handshake start timestamp (ns)
        ("has_session_key", c_bool),                  # True if session key is valid
    ]

MemshadowHandshakeCtx = memshadow_handshake_ctx_t


class memshadow_session_t(Structure):
    """Session Structure."""
    _fields_ = [
        ("session_id", c_char * (MEMSHADOW_SESSION_ID_SIZE + 1)),
        ("peer_id", c_char * 64),
        ("state", c_int),                             # memshadow_session_state_t
        ("created_at_ns", c_uint64),
        ("last_activity_ns", c_uint64),
        ("timeout_ms", c_uint64),
        ("session_key", c_uint8 * MEMSHADOW_SESSION_KEY_SIZE),
        ("hmac_key", c_uint8 * MEMSHADOW_SESSION_KEY_SIZE),
        ("key_rotation_count", c_uint64),
        ("messages_sent", c_uint64),
        ("messages_received", c_uint64),
        ("bytes_sent", c_uint64),
        ("bytes_received", c_uint64),
    ]

MemshadowSession = memshadow_session_t


class memshadow_session_stats_t(Structure):
    """Session Statistics Structure."""
    _fields_ = [
        ("active", c_uint32),
        ("idle", c_uint32),
        ("expired", c_uint32),
        ("closing", c_uint32),
        ("total_messages_sent", c_uint64),
        ("total_messages_received", c_uint64),
        ("total_bytes_sent", c_uint64),
        ("total_bytes_received", c_uint64),
    ]

MemshadowSessionStats = memshadow_session_stats_t


class memshadow_session_manager_t(Structure):
    """Session Manager Structure."""
    _fields_ = [
        ("sessions", memshadow_session_t * MEMSHADOW_SESSION_MAX),
        ("session_count", c_uint32),
        ("default_timeout_ms", c_uint64),
        ("key_rotation_interval_ms", c_uint64),
    ]

MemshadowSessionManager = memshadow_session_manager_t


class memshadow_peer_health_t(Structure):
    """Peer Health Structure."""
    _fields_ = [
        ("latency_ms", c_double),
        ("packet_loss", c_double),
        ("bandwidth_bps", c_uint64),
        ("last_ping_ns", c_uint64),
        ("ping_failures", c_uint32),
        ("max_ping_failures", c_uint32),
    ]

MemshadowPeerHealth = memshadow_peer_health_t


class memshadow_peer_info_t(Structure):
    """Peer Information Structure."""
    _fields_ = [
        ("node_id", c_char * 64),
        ("address_ipv4", c_uint32),
        ("port", c_uint16),
        ("status", c_int),                            # memshadow_peer_status_t
        ("health", memshadow_peer_health_t),
        ("capabilities", c_uint32),
        ("version", c_uint16),
        ("connected_since_ns", c_uint64),
        ("messages_sent", c_uint64),
        ("messages_received", c_uint64),
        ("bytes_sent", c_uint64),
        ("bytes_received", c_uint64),
    ]

MemshadowPeerInfo = memshadow_peer_info_t


class memshadow_peer_manager_t(Structure):
    """Peer Manager Structure."""
    _fields_ = [
        ("peers", memshadow_peer_info_t * MEMSHADOW_PEER_MAX),
        ("peer_count", c_uint16),
        ("max_peers", c_uint16),
        ("ping_interval_ms", c_uint32),
        ("ban_duration_ms", c_uint64),
        ("strategy", c_int),                          # memshadow_selection_strategy_t
        ("round_robin_index", c_uint16),
    ]

MemshadowPeerManager = memshadow_peer_manager_t


class memshadow_pqc_manager_t(Structure):
    """PQC Manager Structure."""
    _fields_ = [
        ("algorithm", c_int),                         # memshadow_pqc_algorithm_t
        ("internal_state", c_void_p),
    ]

MemshadowPqcManager = memshadow_pqc_manager_t


class memshadow_hybrid_keypair_t(Structure):
    """Hybrid Keypair Structure."""
    _fields_ = [
        ("classical_private_key", POINTER(c_uint8)),
        ("classical_private_key_size", c_size_t),
        ("classical_public_key", POINTER(c_uint8)),
        ("classical_public_key_size", c_size_t),
        ("pqc_private_key", POINTER(c_uint8)),
        ("pqc_private_key_size", c_size_t),
        ("pqc_public_key", POINTER(c_uint8)),
        ("pqc_public_key_size", c_size_t),
        ("he_public_key", POINTER(c_uint8)),
        ("he_public_key_size", c_size_t),
        ("he_private_key", POINTER(c_uint8)),
        ("he_private_key_size", c_size_t),
        ("he_evaluation_key", POINTER(c_uint8)),
        ("he_evaluation_key_size", c_size_t),
        ("he_relinearization_key", POINTER(c_uint8)),
        ("he_relinearization_key_size", c_size_t),
        ("he_galois_key", POINTER(c_uint8)),
        ("he_galois_key_size", c_size_t),
        ("algorithm", c_int),
    ]

MemshadowHybridKeypair = memshadow_hybrid_keypair_t


class memshadow_homomorphic_ciphertext_t(Structure):
    """Homomorphic Ciphertext Structure."""
    _fields_ = [
        ("ciphertext", POINTER(c_uint8)),
        ("ciphertext_size", c_size_t),
        ("algorithm", c_int),
        ("scale", c_double),
        ("level", c_uint32),
        ("noise_budget", c_uint32),
    ]

MemshadowHomomorphicCiphertext = memshadow_homomorphic_ciphertext_t


class memshadow_gossip_peer_t(Structure):
    """Gossip Peer Information Structure."""
    _fields_ = [
        ("peer_id", c_char_p),
        ("address", c_char_p),
        ("port", c_uint16),
        ("last_seen", c_uint64),
        ("heartbeat_count", c_uint32),
        ("suspicion_level", c_float),
    ]

MemshadowGossipPeer = memshadow_gossip_peer_t


class memshadow_gossip_message_t(Structure):
    """Gossip Message Structure."""
    _fields_ = [
        ("id", c_uint8 * 16),
        ("msg_type", c_int),                          # memshadow_gossip_message_type_t
        ("sender_id", c_char_p),
        ("payload", POINTER(c_uint8)),
        ("payload_size", c_size_t),
        ("timestamp", c_uint64),
        ("ttl", c_uint32),
        ("hop_count", c_uint32),
    ]

MemshadowGossipMessage = memshadow_gossip_message_t


class memshadow_gossip_manager_t(Structure):
    """Gossip Manager Structure."""
    _fields_ = [
        ("node_id", c_char_p),
        ("peers", POINTER(memshadow_gossip_peer_t)),
        ("peer_count", c_size_t),
        ("peer_capacity", c_size_t),
        ("seen_messages", c_void_p),
        ("seen_timestamps", POINTER(c_uint64)),
        ("seen_count", c_size_t),
        ("seen_capacity", c_size_t),
        ("outgoing_queue", POINTER(memshadow_gossip_message_t)),
        ("outgoing_count", c_size_t),
        ("outgoing_capacity", c_size_t),
        ("fan_out", c_uint32),
        ("gossip_interval_ms", c_uint64),
        ("last_gossip_time", c_uint64),
        ("random_seed", c_uint32),
    ]

MemshadowGossipManager = memshadow_gossip_manager_t


class memshadow_gossip_outgoing_message_t(Structure):
    """Outgoing Gossip Message Container Structure."""
    _fields_ = [
        ("peer_id", c_char_p),
        ("message", memshadow_gossip_message_t),
    ]

MemshadowGossipOutgoingMessage = memshadow_gossip_outgoing_message_t


class memshadow_gossip_statistics_t(Structure):
    """Gossip Statistics Structure."""
    _fields_ = [
        ("total_peers", c_size_t),
        ("seen_messages", c_size_t),
        ("queued_messages", c_size_t),
        ("suspected_failures", c_size_t),
    ]

MemshadowGossipStatistics = memshadow_gossip_statistics_t


# ============================================================================
# Library Loading and Binding Initialization
# ============================================================================

def _load_msnet_library():
    """Load MSNET shared library (libmemshadow.so)."""
    possible_paths = []
    for env_name in ("MSNET_LIB_PATH", "MEMSHADOW_LIB_PATH"):
        if os.getenv(env_name):
            possible_paths.append(Path(os.environ[env_name]))

    spectra_root = Path(__file__).resolve().parent.parent.parent
    possible_paths.extend([
        spectra_root / "tgarchive" / "native" / "msnet" / "libmemshadow.so",
        spectra_root / "native" / "msnet" / "libmemshadow.so",
        spectra_root / "libs" / "msnet" / "libmemshadow.so",
        Path("/usr/local/lib/libmemshadow.so"),
        Path("/usr/lib/libmemshadow.so"),
        Path("libmemshadow.so"),
    ])

    for lib_path in possible_paths:
        if lib_path.exists():
            try:
                mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
                lib = ctypes.CDLL(str(lib_path), mode=mode)
                logger.info(f"Loaded MSNET library from {lib_path}")
                return lib
            except OSError as e:
                logger.debug(f"Failed to load {lib_path}: {e}")
                continue

    try:
        mode = getattr(os, "RTLD_GLOBAL", 0) | getattr(os, "RTLD_NOW", 0)
        lib = ctypes.CDLL("libmemshadow.so", mode=mode)
        logger.info("Loaded MSNET library from system path")
        return lib
    except OSError:
        logger.warning("MSNET (libmemshadow.so) library not found. Swarming features will be unavailable.")
        return None


_msnet_lib = _load_msnet_library()

if _msnet_lib is not None:
    # ── Protocol Core ────────────────────────────────────────────────────────
    _msnet_lib.memshadow_pack_header.argtypes = [
        POINTER(memshadow_header_t), POINTER(c_uint8), c_size_t
    ]
    _msnet_lib.memshadow_pack_header.restype = c_int

    _msnet_lib.memshadow_unpack_header.argtypes = [
        POINTER(c_uint8), c_size_t, POINTER(memshadow_header_t)
    ]
    _msnet_lib.memshadow_unpack_header.restype = c_int

    _msnet_lib.memshadow_validate_header.argtypes = [POINTER(memshadow_header_t)]
    _msnet_lib.memshadow_validate_header.restype = c_bool

    _msnet_lib.memshadow_pack_message.argtypes = [
        POINTER(memshadow_header_t),
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_size_t),
        POINTER(c_uint8),
        c_size_t,
    ]
    _msnet_lib.memshadow_pack_message.restype = c_int

    _msnet_lib.memshadow_unpack_message.argtypes = [
        POINTER(c_uint8),
        c_size_t,
        POINTER(memshadow_header_t),
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_size_t),
        POINTER(c_uint8),
        c_size_t,
    ]
    _msnet_lib.memshadow_unpack_message.restype = c_int

    _msnet_lib.memshadow_compute_hmac.argtypes = [
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
    ]
    _msnet_lib.memshadow_compute_hmac.restype = c_int

    _msnet_lib.memshadow_verify_hmac.argtypes = [
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
    ]
    _msnet_lib.memshadow_verify_hmac.restype = c_int

    _msnet_lib.memshadow_get_timestamp_ns.argtypes = []
    _msnet_lib.memshadow_get_timestamp_ns.restype = c_uint64

    _msnet_lib.memshadow_get_next_sequence.argtypes = [POINTER(c_uint32)]
    _msnet_lib.memshadow_get_next_sequence.restype = c_uint32

    _msnet_lib.memshadow_create_error_message.argtypes = [
        c_int, c_char_p, POINTER(c_uint8), c_size_t, POINTER(c_size_t)
    ]
    _msnet_lib.memshadow_create_error_message.restype = c_int

    _msnet_lib.memshadow_parse_error_message.argtypes = [
        POINTER(c_uint8), c_size_t, POINTER(c_int), c_char_p, c_size_t
    ]
    _msnet_lib.memshadow_parse_error_message.restype = c_int

    _msnet_lib.memshadow_get_error_message.argtypes = [c_int]
    _msnet_lib.memshadow_get_error_message.restype = c_char_p

    _msnet_lib.memshadow_check_version_compatibility.argtypes = [
        POINTER(memshadow_version_t), POINTER(memshadow_version_t)
    ]
    _msnet_lib.memshadow_check_version_compatibility.restype = c_int

    _msnet_lib.memshadow_compress.argtypes = [
        POINTER(c_uint8), c_size_t, POINTER(c_uint8), c_size_t, POINTER(c_size_t), c_int
    ]
    _msnet_lib.memshadow_compress.restype = c_int

    _msnet_lib.memshadow_decompress.argtypes = [
        POINTER(c_uint8), c_size_t, POINTER(c_uint8), c_size_t, POINTER(c_size_t), c_int
    ]
    _msnet_lib.memshadow_decompress.restype = c_int

    _msnet_lib.memshadow_detect_kanzi.argtypes = []
    _msnet_lib.memshadow_detect_kanzi.restype = c_bool

    _msnet_lib.memshadow_detect_qatzip.argtypes = []
    _msnet_lib.memshadow_detect_qatzip.restype = c_bool

    _msnet_lib.memshadow_get_preferred_compression.argtypes = []
    _msnet_lib.memshadow_get_preferred_compression.restype = c_int

    # ── Handshake ────────────────────────────────────────────────────────────
    _msnet_lib.memshadow_handshake_init.argtypes = [
        POINTER(memshadow_handshake_ctx_t), c_uint32
    ]
    _msnet_lib.memshadow_handshake_init.restype = None

    _msnet_lib.memshadow_handshake_create_hello.argtypes = [
        POINTER(memshadow_handshake_ctx_t),
        c_char_p,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_size_t),
    ]
    _msnet_lib.memshadow_handshake_create_hello.restype = c_int

    _msnet_lib.memshadow_handshake_process_hello.argtypes = [
        POINTER(memshadow_handshake_ctx_t),
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_size_t),
    ]
    _msnet_lib.memshadow_handshake_process_hello.restype = c_int

    _msnet_lib.memshadow_handshake_process_hello_ack.argtypes = [
        POINTER(memshadow_handshake_ctx_t),
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_size_t),
    ]
    _msnet_lib.memshadow_handshake_process_hello_ack.restype = c_int

    _msnet_lib.memshadow_handshake_process_challenge_response.argtypes = [
        POINTER(memshadow_handshake_ctx_t),
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_size_t),
    ]
    _msnet_lib.memshadow_handshake_process_challenge_response.restype = c_int

    _msnet_lib.memshadow_handshake_is_timed_out.argtypes = [
        POINTER(memshadow_handshake_ctx_t)
    ]
    _msnet_lib.memshadow_handshake_is_timed_out.restype = c_bool

    _msnet_lib.memshadow_handshake_reset.argtypes = [
        POINTER(memshadow_handshake_ctx_t)
    ]
    _msnet_lib.memshadow_handshake_reset.restype = None

    _msnet_lib.memshadow_handshake_get_negotiated_caps.argtypes = [
        POINTER(memshadow_handshake_ctx_t)
    ]
    _msnet_lib.memshadow_handshake_get_negotiated_caps.restype = c_uint32

    _msnet_lib.memshadow_handshake_get_session_key.argtypes = [
        POINTER(memshadow_handshake_ctx_t)
    ]
    _msnet_lib.memshadow_handshake_get_session_key.restype = POINTER(c_uint8)

    # ── Session Management ───────────────────────────────────────────────────
    _msnet_lib.memshadow_session_manager_init.argtypes = [
        POINTER(memshadow_session_manager_t), c_uint64
    ]
    _msnet_lib.memshadow_session_manager_init.restype = None

    _msnet_lib.memshadow_session_create.argtypes = [
        POINTER(memshadow_session_manager_t),
        c_char_p,
        POINTER(c_uint8),
        POINTER(c_uint8),
        c_char_p,
    ]
    _msnet_lib.memshadow_session_create.restype = c_int

    _msnet_lib.memshadow_session_close.argtypes = [
        POINTER(memshadow_session_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_session_close.restype = c_int

    _msnet_lib.memshadow_session_find.argtypes = [
        POINTER(memshadow_session_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_session_find.restype = POINTER(memshadow_session_t)

    _msnet_lib.memshadow_session_find_by_peer.argtypes = [
        POINTER(memshadow_session_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_session_find_by_peer.restype = POINTER(memshadow_session_t)

    _msnet_lib.memshadow_session_tick.argtypes = [
        POINTER(memshadow_session_manager_t)
    ]
    _msnet_lib.memshadow_session_tick.restype = None

    _msnet_lib.memshadow_session_cleanup_expired.argtypes = [
        POINTER(memshadow_session_manager_t)
    ]
    _msnet_lib.memshadow_session_cleanup_expired.restype = None

    _msnet_lib.memshadow_session_record_send.argtypes = [
        POINTER(memshadow_session_t), c_uint64
    ]
    _msnet_lib.memshadow_session_record_send.restype = None

    _msnet_lib.memshadow_session_record_receive.argtypes = [
        POINTER(memshadow_session_t), c_uint64
    ]
    _msnet_lib.memshadow_session_record_receive.restype = None

    _msnet_lib.memshadow_session_rotate_key.argtypes = [
        POINTER(memshadow_session_t), POINTER(c_uint8), POINTER(c_uint8)
    ]
    _msnet_lib.memshadow_session_rotate_key.restype = c_int

    _msnet_lib.memshadow_session_get_stats.argtypes = [
        POINTER(memshadow_session_manager_t), POINTER(memshadow_session_stats_t)
    ]
    _msnet_lib.memshadow_session_get_stats.restype = None

    _msnet_lib.memshadow_session_active_count.argtypes = [
        POINTER(memshadow_session_manager_t)
    ]
    _msnet_lib.memshadow_session_active_count.restype = c_uint32

    # ── Peer Management ──────────────────────────────────────────────────────
    _msnet_lib.memshadow_peer_manager_init.argtypes = [
        POINTER(memshadow_peer_manager_t), c_uint16
    ]
    _msnet_lib.memshadow_peer_manager_init.restype = None

    _msnet_lib.memshadow_peer_add.argtypes = [
        POINTER(memshadow_peer_manager_t), POINTER(memshadow_peer_info_t)
    ]
    _msnet_lib.memshadow_peer_add.restype = c_int

    _msnet_lib.memshadow_peer_remove.argtypes = [
        POINTER(memshadow_peer_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_peer_remove.restype = c_int

    _msnet_lib.memshadow_peer_find.argtypes = [
        POINTER(memshadow_peer_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_peer_find.restype = POINTER(memshadow_peer_info_t)

    _msnet_lib.memshadow_peer_select.argtypes = [
        POINTER(memshadow_peer_manager_t)
    ]
    _msnet_lib.memshadow_peer_select.restype = POINTER(memshadow_peer_info_t)

    _msnet_lib.memshadow_peer_connect.argtypes = [
        POINTER(memshadow_peer_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_peer_connect.restype = None

    _msnet_lib.memshadow_peer_disconnect.argtypes = [
        POINTER(memshadow_peer_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_peer_disconnect.restype = None

    _msnet_lib.memshadow_peer_ban.argtypes = [
        POINTER(memshadow_peer_manager_t), c_char_p
    ]
    _msnet_lib.memshadow_peer_ban.restype = None

    _msnet_lib.memshadow_peer_tick.argtypes = [
        POINTER(memshadow_peer_manager_t)
    ]
    _msnet_lib.memshadow_peer_tick.restype = None

    _msnet_lib.memshadow_peer_record_ping.argtypes = [
        POINTER(memshadow_peer_info_t), c_double
    ]
    _msnet_lib.memshadow_peer_record_ping.restype = None

    _msnet_lib.memshadow_peer_record_ping_failure.argtypes = [
        POINTER(memshadow_peer_info_t)
    ]
    _msnet_lib.memshadow_peer_record_ping_failure.restype = None

    _msnet_lib.memshadow_peer_is_healthy.argtypes = [
        POINTER(memshadow_peer_health_t)
    ]
    _msnet_lib.memshadow_peer_is_healthy.restype = c_bool

    _msnet_lib.memshadow_peer_health_score.argtypes = [
        POINTER(memshadow_peer_health_t)
    ]
    _msnet_lib.memshadow_peer_health_score.restype = c_double

    _msnet_lib.memshadow_peer_connected_count.argtypes = [
        POINTER(memshadow_peer_manager_t)
    ]
    _msnet_lib.memshadow_peer_connected_count.restype = c_uint16

    # ── Post-Quantum Cryptography (PQC) ──────────────────────────────────────
    _msnet_lib.memshadow_pqc_init.argtypes = [
        POINTER(POINTER(memshadow_pqc_manager_t)), c_int
    ]
    _msnet_lib.memshadow_pqc_init.restype = c_int

    _msnet_lib.memshadow_pqc_generate_keypair.argtypes = [
        POINTER(memshadow_pqc_manager_t), POINTER(memshadow_hybrid_keypair_t)
    ]
    _msnet_lib.memshadow_pqc_generate_keypair.restype = c_int

    _msnet_lib.memshadow_pqc_cleanup.argtypes = [
        POINTER(memshadow_pqc_manager_t)
    ]
    _msnet_lib.memshadow_pqc_cleanup.restype = None

    _msnet_lib.memshadow_pqc_key_exchange.argtypes = [
        POINTER(memshadow_pqc_manager_t),
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        c_size_t,
        POINTER(c_uint8),
        POINTER(c_size_t),
    ]
    _msnet_lib.memshadow_pqc_key_exchange.restype = c_int

    _msnet_lib.memshadow_hybrid_keypair_init.argtypes = [
        POINTER(memshadow_hybrid_keypair_t), c_int
    ]
    _msnet_lib.memshadow_hybrid_keypair_init.restype = c_int

    _msnet_lib.memshadow_hybrid_keypair_cleanup.argtypes = [
        POINTER(memshadow_hybrid_keypair_t)
    ]
    _msnet_lib.memshadow_hybrid_keypair_cleanup.restype = None

    _msnet_lib.memshadow_pqc_error_message.argtypes = [c_int]
    _msnet_lib.memshadow_pqc_error_message.restype = c_char_p

    _msnet_lib.memshadow_homomorphic_ciphertext_init.argtypes = [
        POINTER(memshadow_homomorphic_ciphertext_t), c_int
    ]
    _msnet_lib.memshadow_homomorphic_ciphertext_init.restype = c_int

    _msnet_lib.memshadow_homomorphic_ciphertext_cleanup.argtypes = [
        POINTER(memshadow_homomorphic_ciphertext_t)
    ]
    _msnet_lib.memshadow_homomorphic_ciphertext_cleanup.restype = None

    _msnet_lib.memshadow_homomorphic_ciphertext_can_operate.argtypes = [
        POINTER(memshadow_homomorphic_ciphertext_t)
    ]
    _msnet_lib.memshadow_homomorphic_ciphertext_can_operate.restype = c_bool

    # ── Gossip Protocol ──────────────────────────────────────────────────────
    _msnet_lib.memshadow_gossip_manager_init.argtypes = [
        POINTER(POINTER(memshadow_gossip_manager_t)),
        c_char_p,
        c_uint32,
        c_uint64,
    ]
    _msnet_lib.memshadow_gossip_manager_init.restype = c_int

    _msnet_lib.memshadow_gossip_manager_add_peer.argtypes = [
        POINTER(memshadow_gossip_manager_t),
        memshadow_gossip_peer_t,
    ]
    _msnet_lib.memshadow_gossip_manager_add_peer.restype = c_int

    _msnet_lib.memshadow_gossip_manager_remove_peer.argtypes = [
        POINTER(memshadow_gossip_manager_t),
        c_char_p,
    ]
    _msnet_lib.memshadow_gossip_manager_remove_peer.restype = c_bool

    _msnet_lib.memshadow_gossip_manager_broadcast_message.argtypes = [
        POINTER(memshadow_gossip_manager_t),
        c_int,
        POINTER(c_uint8),
        c_size_t,
        c_uint32,
    ]
    _msnet_lib.memshadow_gossip_manager_broadcast_message.restype = c_int

    _msnet_lib.memshadow_gossip_manager_receive_message.argtypes = [
        POINTER(memshadow_gossip_manager_t),
        memshadow_gossip_message_t,
        c_char_p,
    ]
    _msnet_lib.memshadow_gossip_manager_receive_message.restype = c_int

    _msnet_lib.memshadow_gossip_manager_perform_gossip_round.argtypes = [
        POINTER(memshadow_gossip_manager_t),
        POINTER(POINTER(memshadow_gossip_outgoing_message_t)),
        POINTER(c_size_t),
    ]
    _msnet_lib.memshadow_gossip_manager_perform_gossip_round.restype = c_int

    _msnet_lib.memshadow_gossip_manager_cleanup.argtypes = [
        POINTER(memshadow_gossip_manager_t)
    ]
    _msnet_lib.memshadow_gossip_manager_cleanup.restype = None

    _msnet_lib.memshadow_gossip_peer_init.argtypes = [
        POINTER(memshadow_gossip_peer_t),
        c_char_p,
        c_char_p,
        c_uint16,
    ]
    _msnet_lib.memshadow_gossip_peer_init.restype = c_int

    _msnet_lib.memshadow_gossip_peer_cleanup.argtypes = [
        POINTER(memshadow_gossip_peer_t)
    ]
    _msnet_lib.memshadow_gossip_peer_cleanup.restype = None

    _msnet_lib.memshadow_gossip_peer_update_last_seen.argtypes = [
        POINTER(memshadow_gossip_peer_t)
    ]
    _msnet_lib.memshadow_gossip_peer_update_last_seen.restype = None

    _msnet_lib.memshadow_gossip_peer_increase_suspicion.argtypes = [
        POINTER(memshadow_gossip_peer_t)
    ]
    _msnet_lib.memshadow_gossip_peer_increase_suspicion.restype = None

    _msnet_lib.memshadow_gossip_peer_is_suspected_failed.argtypes = [
        POINTER(memshadow_gossip_peer_t), c_float
    ]
    _msnet_lib.memshadow_gossip_peer_is_suspected_failed.restype = c_bool

    _msnet_lib.memshadow_gossip_message_init.argtypes = [
        POINTER(memshadow_gossip_message_t), c_int, c_char_p, POINTER(c_uint8), c_size_t, c_uint32
    ]
    _msnet_lib.memshadow_gossip_message_init.restype = c_int

    _msnet_lib.memshadow_gossip_message_cleanup.argtypes = [
        POINTER(memshadow_gossip_message_t)
    ]
    _msnet_lib.memshadow_gossip_message_cleanup.restype = None

    _msnet_lib.memshadow_gossip_message_is_expired.argtypes = [
        POINTER(memshadow_gossip_message_t)
    ]
    _msnet_lib.memshadow_gossip_message_is_expired.restype = c_bool

    _msnet_lib.memshadow_gossip_message_decrement_ttl.argtypes = [
        POINTER(memshadow_gossip_message_t)
    ]
    _msnet_lib.memshadow_gossip_message_decrement_ttl.restype = None

    _msnet_lib.memshadow_gossip_message_id_equals.argtypes = [
        POINTER(c_uint8), POINTER(c_uint8)
    ]
    _msnet_lib.memshadow_gossip_message_id_equals.restype = c_bool

    _msnet_lib.memshadow_gossip_outgoing_messages_cleanup.argtypes = [
        POINTER(memshadow_gossip_outgoing_message_t), c_size_t
    ]
    _msnet_lib.memshadow_gossip_outgoing_messages_cleanup.restype = None

    _msnet_lib.memshadow_gossip_manager_run_failure_detection.argtypes = [
        POINTER(memshadow_gossip_manager_t)
    ]
    _msnet_lib.memshadow_gossip_manager_run_failure_detection.restype = c_int

    _msnet_lib.memshadow_gossip_manager_get_statistics.argtypes = [
        POINTER(memshadow_gossip_manager_t), POINTER(memshadow_gossip_statistics_t)
    ]
    _msnet_lib.memshadow_gossip_manager_get_statistics.restype = None

    _msnet_lib.memshadow_gossip_manager_cleanup_old_messages.argtypes = [
        POINTER(memshadow_gossip_manager_t), c_uint64
    ]
    _msnet_lib.memshadow_gossip_manager_cleanup_old_messages.restype = None

    _msnet_lib.memshadow_gossip_manager_perform_anti_entropy.argtypes = [
        POINTER(memshadow_gossip_manager_t), c_void_p, c_size_t, POINTER(POINTER(memshadow_gossip_message_t)), POINTER(c_size_t)
    ]
    _msnet_lib.memshadow_gossip_manager_perform_anti_entropy.restype = c_int


def msnet_available() -> bool:
    """Check if MSNET native library is available."""
    return _msnet_lib is not None


def memshadow_available() -> bool:
    """Check if MEMSHADOW native library is available (alias for msnet_available)."""
    return msnet_available()


def memshadow_init() -> bool:
    """Initialize MSNET runtime and check availability."""
    return msnet_available()


def get_msnet_version() -> str:
    """Get MSNET protocol version string."""
    return f"{MEMSHADOW_VERSION_MAJOR}.{MEMSHADOW_VERSION_MINOR}"


def get_msnet_build_info() -> str:
    """Get MSNET build information string."""
    if not msnet_available():
        return "MSNET not available"
    return "libmemshadow v3.0 (scalar C, PQC CSNA2.0, OpenSSL, zlib)"


# ============================================================================
# Protocol Core Functions
# ============================================================================

def memshadow_pack_header(header: memshadow_header_t, buffer: Optional[bytearray] = None) -> bytes:
    """
    Pack a 32-byte header structure to big-endian binary.

    Args:
        header: memshadow_header_t structure
        buffer: Optional preallocated bytearray (at least 32 bytes)

    Returns:
        32-byte header bytes
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    out_buf = (c_uint8 * MEMSHADOW_HEADER_SIZE)()
    res = _msnet_lib.memshadow_pack_header(byref(header), out_buf, MEMSHADOW_HEADER_SIZE)
    if res != MEMSHADOW_HEADER_SIZE:
        raise ValueError(f"Failed to pack MSNET header: error {res}")
    return bytes(out_buf)


def memshadow_unpack_header(buffer: bytes) -> memshadow_header_t:
    """
    Unpack a 32-byte binary header into a memshadow_header_t structure.

    Args:
        buffer: Raw bytes (at least 32 bytes)

    Returns:
        memshadow_header_t instance
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if len(buffer) < MEMSHADOW_HEADER_SIZE:
        raise ValueError(f"Buffer too small: {len(buffer)} < {MEMSHADOW_HEADER_SIZE}")

    c_buf = (c_uint8 * len(buffer)).from_buffer_copy(buffer)
    header = memshadow_header_t()
    res = _msnet_lib.memshadow_unpack_header(c_buf, len(buffer), byref(header))
    if res != 0:
        raise ValueError(f"Failed to unpack MSNET header: error {res}")
    return header


def memshadow_validate_header(header: memshadow_header_t) -> bool:
    """Validate magic and version of an unpacked header."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return bool(_msnet_lib.memshadow_validate_header(byref(header)))


def memshadow_compute_hmac(data: bytes, key: bytes) -> bytes:
    """
    Compute HMAC-SHA384 for message data (48 bytes output).

    Args:
        data: Input message data bytes
        key: Secret HMAC key bytes

    Returns:
        48-byte HMAC output
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    data_buf = (c_uint8 * len(data)).from_buffer_copy(data) if data else None
    key_buf = (c_uint8 * len(key)).from_buffer_copy(key) if key else None
    hmac_out = (c_uint8 * 48)()

    res = _msnet_lib.memshadow_compute_hmac(
        data_buf, len(data), key_buf, len(key), hmac_out, 48
    )
    if res != 0:
        raise ValueError(f"Failed to compute HMAC: error {res}")
    return bytes(hmac_out)


def memshadow_verify_hmac(data: bytes, key: bytes, expected_hmac: bytes) -> bool:
    """
    Verify HMAC-SHA384 integrity tag.

    Args:
        data: Input message data bytes
        key: Secret HMAC key bytes
        expected_hmac: Received HMAC tag (48 bytes)

    Returns:
        True if verification succeeded, False otherwise
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    data_buf = (c_uint8 * len(data)).from_buffer_copy(data) if data else None
    key_buf = (c_uint8 * len(key)).from_buffer_copy(key) if key else None
    hmac_buf = (c_uint8 * len(expected_hmac)).from_buffer_copy(expected_hmac)

    res = _msnet_lib.memshadow_verify_hmac(
        data_buf, len(data), key_buf, len(key), hmac_buf, len(expected_hmac)
    )
    return res == 0


def memshadow_get_timestamp_ns() -> int:
    """Get current monotonic timestamp in nanoseconds."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_get_timestamp_ns())


def memshadow_get_next_sequence(sequence_counter: int) -> Tuple[int, int]:
    """
    Get next sequence number and updated counter.

    Args:
        sequence_counter: Current sequence counter integer

    Returns:
        (sequence_number, next_counter) tuple
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    c_counter = c_uint32(sequence_counter)
    seq = _msnet_lib.memshadow_get_next_sequence(byref(c_counter))
    return int(seq), int(c_counter.value)


def memshadow_pack_message(
    header: memshadow_header_t,
    payload: bytes = b"",
    integrity_key: Optional[bytes] = None
) -> bytes:
    """
    Pack full message (header + payload + optional HMAC).

    Args:
        header: Message header structure
        payload: Message payload bytes
        integrity_key: Optional HMAC key for FLAG_INTEGRITY_CHECK

    Returns:
        Framed message bytes
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    max_buf_len = MEMSHADOW_HEADER_SIZE + len(payload) + (48 if integrity_key else 0)
    out_buf = (c_uint8 * max_buf_len)()
    out_size = c_size_t(0)

    p_buf = (c_uint8 * len(payload)).from_buffer_copy(payload) if payload else None
    k_buf = (c_uint8 * len(integrity_key)).from_buffer_copy(integrity_key) if integrity_key else None
    k_len = len(integrity_key) if integrity_key else 0

    res = _msnet_lib.memshadow_pack_message(
        byref(header),
        p_buf,
        len(payload),
        out_buf,
        max_buf_len,
        byref(out_size),
        k_buf,
        k_len
    )
    if res != 0:
        raise ValueError(f"Failed to pack MSNET message: error {res}")
    return bytes(out_buf[:out_size.value])


def memshadow_unpack_message(
    buffer: bytes,
    integrity_key: Optional[bytes] = None
) -> Tuple[memshadow_header_t, bytes]:
    """
    Unpack full message and verify optional HMAC.

    Args:
        buffer: Raw message bytes
        integrity_key: Optional HMAC key

    Returns:
        (header, payload) tuple
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if len(buffer) < MEMSHADOW_HEADER_SIZE:
        raise ValueError(f"Buffer too short: {len(buffer)} < {MEMSHADOW_HEADER_SIZE}")

    c_buf = (c_uint8 * len(buffer)).from_buffer_copy(buffer)
    header = memshadow_header_t()
    payload_buf = (c_uint8 * len(buffer))()
    payload_size = c_size_t(0)

    k_buf = (c_uint8 * len(integrity_key)).from_buffer_copy(integrity_key) if integrity_key else None
    k_len = len(integrity_key) if integrity_key else 0

    res = _msnet_lib.memshadow_unpack_message(
        c_buf,
        len(buffer),
        byref(header),
        payload_buf,
        len(buffer),
        byref(payload_size),
        k_buf,
        k_len
    )
    if res != 0:
        raise ValueError(f"Failed to unpack MSNET message: error {res}")
    return header, bytes(payload_buf[:payload_size.value])


# Framing Aliases
memshadow_send = memshadow_pack_message
memshadow_recv = memshadow_unpack_message


def memshadow_create_error_message(error_code: int, details: str = "") -> bytes:
    """Create binary error message payload."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    buf = (c_uint8 * 512)()
    out_size = c_size_t(0)
    details_bytes = details.encode("utf-8") if details else b""
    res = _msnet_lib.memshadow_create_error_message(
        error_code, details_bytes, buf, 512, byref(out_size)
    )
    if res != 0:
        raise ValueError(f"Failed to create error message: error {res}")
    return bytes(buf[:out_size.value])


def memshadow_parse_error_message(buffer: bytes) -> Tuple[int, str]:
    """Parse binary error message payload into (error_code, details)."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    c_buf = (c_uint8 * len(buffer)).from_buffer_copy(buffer)
    err_code = c_int(0)
    details_buf = create_string_buffer(512)
    res = _msnet_lib.memshadow_parse_error_message(
        c_buf, len(buffer), byref(err_code), details_buf, 512
    )
    if res != 0:
        raise ValueError(f"Failed to parse error message: error {res}")
    return int(err_code.value), details_buf.value.decode("utf-8", errors="replace")


def memshadow_get_error_message(error_code: int) -> str:
    """Get human-readable description of MSNET error code."""
    if _msnet_lib is None:
        return f"Unknown error {error_code}"
    ptr = _msnet_lib.memshadow_get_error_message(error_code)
    if ptr:
        return ptr.decode("utf-8")
    return f"Unknown error {error_code}"


def memshadow_check_version_compatibility(local_version: Tuple[int, int], peer_version: Tuple[int, int]) -> int:
    """Check version compatibility between local node and peer node."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    l_ver = memshadow_version_t(local_version[0], local_version[1])
    p_ver = memshadow_version_t(peer_version[0], peer_version[1])
    return int(_msnet_lib.memshadow_check_version_compatibility(byref(l_ver), byref(p_ver)))


def memshadow_compress(data: bytes, compression_type: int = 2) -> bytes:
    """Compress payload data using zlib/Kanzi/QAT."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if not data:
        return b""
    in_buf = (c_uint8 * len(data)).from_buffer_copy(data)
    out_max = max(len(data) * 2, 512)
    out_buf = (c_uint8 * out_max)()
    comp_size = c_size_t(0)
    res = _msnet_lib.memshadow_compress(
        in_buf, len(data), out_buf, out_max, byref(comp_size), compression_type
    )
    if res != 0:
        raise ValueError(f"Failed to compress MSNET data: error {res}")
    return bytes(out_buf[:comp_size.value])


def memshadow_decompress(data: bytes, output_size: int, compression_type: int = 2) -> bytes:
    """Decompress payload data."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if not data:
        return b""
    in_buf = (c_uint8 * len(data)).from_buffer_copy(data)
    out_buf = (c_uint8 * output_size)()
    decomp_size = c_size_t(0)
    res = _msnet_lib.memshadow_decompress(
        in_buf, len(data), out_buf, output_size, byref(decomp_size), compression_type
    )
    if res != 0:
        raise ValueError(f"Failed to decompress MSNET data: error {res}")
    return bytes(out_buf[:decomp_size.value])


# ============================================================================
# Handshake Functions
# ============================================================================

def memshadow_handshake_init(ctx: memshadow_handshake_ctx_t, capabilities: int = MEMSHADOW_CAP_ALL) -> None:
    """Initialize handshake context with local capabilities."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_handshake_init(byref(ctx), capabilities)


def memshadow_handshake_create_hello(ctx: memshadow_handshake_ctx_t, node_id: str) -> bytes:
    """Create HELLO message payload (client -> server)."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    buf = (c_uint8 * 512)()
    out_size = c_size_t(0)
    res = _msnet_lib.memshadow_handshake_create_hello(
        byref(ctx), node_id.encode("utf-8"), buf, 512, byref(out_size)
    )
    if res != 0:
        raise ValueError(f"Failed to create handshake HELLO: error {res}")
    return bytes(buf[:out_size.value])


def memshadow_handshake_process_hello(ctx: memshadow_handshake_ctx_t, hello_data: bytes) -> bytes:
    """Process incoming HELLO and generate HELLO_ACK response (server side)."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    c_in = (c_uint8 * len(hello_data)).from_buffer_copy(hello_data)
    buf = (c_uint8 * 512)()
    out_size = c_size_t(0)
    res = _msnet_lib.memshadow_handshake_process_hello(
        byref(ctx), c_in, len(hello_data), buf, 512, byref(out_size)
    )
    if res != 0:
        raise ValueError(f"Failed to process handshake HELLO: error {res}")
    return bytes(buf[:out_size.value])


def memshadow_handshake_process_hello_ack(
    ctx: memshadow_handshake_ctx_t,
    ack_data: bytes,
    hmac_key: bytes
) -> bytes:
    """Process incoming HELLO_ACK and generate CHALLENGE_RESPONSE (client side)."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    c_in = (c_uint8 * len(ack_data)).from_buffer_copy(ack_data)
    c_key = (c_uint8 * len(hmac_key)).from_buffer_copy(hmac_key)
    buf = (c_uint8 * 512)()
    out_size = c_size_t(0)
    res = _msnet_lib.memshadow_handshake_process_hello_ack(
        byref(ctx), c_in, len(ack_data), c_key, len(hmac_key), buf, 512, byref(out_size)
    )
    if res != 0:
        raise ValueError(f"Failed to process HELLO_ACK: error {res}")
    return bytes(buf[:out_size.value])


def memshadow_handshake_process_challenge_response(
    ctx: memshadow_handshake_ctx_t,
    response_data: bytes,
    hmac_key: bytes
) -> bytes:
    """Process incoming CHALLENGE_RESPONSE and generate SESSION_ESTABLISHED (server side)."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    c_in = (c_uint8 * len(response_data)).from_buffer_copy(response_data)
    c_key = (c_uint8 * len(hmac_key)).from_buffer_copy(hmac_key)
    buf = (c_uint8 * 512)()
    out_size = c_size_t(0)
    res = _msnet_lib.memshadow_handshake_process_challenge_response(
        byref(ctx), c_in, len(response_data), c_key, len(hmac_key), buf, 512, byref(out_size)
    )
    if res != 0:
        raise ValueError(f"Failed to process CHALLENGE_RESPONSE: error {res}")
    return bytes(buf[:out_size.value])


def memshadow_handshake_is_timed_out(ctx: memshadow_handshake_ctx_t) -> bool:
    """Check if handshake context has timed out."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return bool(_msnet_lib.memshadow_handshake_is_timed_out(byref(ctx)))


def memshadow_handshake_reset(ctx: memshadow_handshake_ctx_t) -> None:
    """Reset handshake state."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_handshake_reset(byref(ctx))


def memshadow_handshake_get_negotiated_caps(ctx: memshadow_handshake_ctx_t) -> int:
    """Get bitmask of negotiated capabilities."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_handshake_get_negotiated_caps(byref(ctx)))


def memshadow_handshake_get_session_key(ctx: memshadow_handshake_ctx_t) -> Optional[bytes]:
    """Get 32-byte session key if established, else None."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    ptr = _msnet_lib.memshadow_handshake_get_session_key(byref(ctx))
    if not ptr:
        return None
    return bytes(ctypes.string_at(ptr, MEMSHADOW_SESSION_KEY_SIZE))


# ============================================================================
# Session Management Functions
# ============================================================================

def memshadow_session_manager_init(mgr: memshadow_session_manager_t, timeout_ms: int = 60000) -> None:
    """Initialize session manager with default timeout in ms."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_session_manager_init(byref(mgr), timeout_ms)


def memshadow_session_create(
    mgr: memshadow_session_manager_t,
    peer_id: str,
    session_key: bytes,
    hmac_key: bytes
) -> str:
    """
    Create a new active session for a peer.

    Returns:
        session_id hex string
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    c_skey = (c_uint8 * MEMSHADOW_SESSION_KEY_SIZE).from_buffer_copy(session_key)
    c_hkey = (c_uint8 * MEMSHADOW_SESSION_KEY_SIZE).from_buffer_copy(hmac_key)
    out_sid = create_string_buffer(MEMSHADOW_SESSION_ID_SIZE + 1)

    res = _msnet_lib.memshadow_session_create(
        byref(mgr), peer_id.encode("utf-8"), c_skey, c_hkey, out_sid
    )
    if res != 0:
        raise ValueError(f"Failed to create session: error {res}")
    return out_sid.value.decode("utf-8")


def memshadow_session_close(mgr: memshadow_session_manager_t, session_id: str) -> int:
    """Close an active session by session ID."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_session_close(byref(mgr), session_id.encode("utf-8")))


def memshadow_session_find(mgr: memshadow_session_manager_t, session_id: str) -> Optional[POINTER(memshadow_session_t)]:
    """Find session by session ID."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    ptr = _msnet_lib.memshadow_session_find(byref(mgr), session_id.encode("utf-8"))
    return ptr if bool(ptr) else None


def memshadow_session_find_by_peer(mgr: memshadow_session_manager_t, peer_id: str) -> Optional[POINTER(memshadow_session_t)]:
    """Find active session by peer ID."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    ptr = _msnet_lib.memshadow_session_find_by_peer(byref(mgr), peer_id.encode("utf-8"))
    return ptr if bool(ptr) else None


def memshadow_session_tick(mgr: memshadow_session_manager_t) -> None:
    """Tick session manager to update states and expire idle sessions."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_session_tick(byref(mgr))


def memshadow_session_cleanup_expired(mgr: memshadow_session_manager_t) -> None:
    """Remove expired and closed sessions."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_session_cleanup_expired(byref(mgr))


def memshadow_session_record_send(session: POINTER(memshadow_session_t), bytes_count: int) -> None:
    """Record outbound bytes and message count on session."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if session:
        _msnet_lib.memshadow_session_record_send(session, bytes_count)


def memshadow_session_record_receive(session: POINTER(memshadow_session_t), bytes_count: int) -> None:
    """Record inbound bytes and message count on session."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if session:
        _msnet_lib.memshadow_session_record_receive(session, bytes_count)


def memshadow_session_rotate_key(
    session: POINTER(memshadow_session_t),
    new_key: bytes,
    new_hmac: bytes
) -> int:
    """Rotate session and HMAC keys for active session."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if not session:
        return -1
    c_k = (c_uint8 * MEMSHADOW_SESSION_KEY_SIZE).from_buffer_copy(new_key)
    c_h = (c_uint8 * MEMSHADOW_SESSION_KEY_SIZE).from_buffer_copy(new_hmac)
    return int(_msnet_lib.memshadow_session_rotate_key(session, c_k, c_h))


def memshadow_session_get_stats(mgr: memshadow_session_manager_t) -> memshadow_session_stats_t:
    """Get aggregated statistics across all managed sessions."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    stats = memshadow_session_stats_t()
    _msnet_lib.memshadow_session_get_stats(byref(mgr), byref(stats))
    return stats


def memshadow_session_active_count(mgr: memshadow_session_manager_t) -> int:
    """Get number of currently active sessions."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_session_active_count(byref(mgr)))


# ============================================================================
# Peer Management Functions
# ============================================================================

def memshadow_peer_manager_init(mgr: memshadow_peer_manager_t, max_peers: int = MEMSHADOW_PEER_MAX) -> None:
    """Initialize peer manager."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_peer_manager_init(byref(mgr), max_peers)


def memshadow_peer_add(mgr: memshadow_peer_manager_t, peer: memshadow_peer_info_t) -> int:
    """Add or update peer in peer table."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_peer_add(byref(mgr), byref(peer)))


def memshadow_peer_remove(mgr: memshadow_peer_manager_t, node_id: str) -> int:
    """Remove peer by node ID."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_peer_remove(byref(mgr), node_id.encode("utf-8")))


def memshadow_peer_find(mgr: memshadow_peer_manager_t, node_id: str) -> Optional[POINTER(memshadow_peer_info_t)]:
    """Find peer by node ID."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    ptr = _msnet_lib.memshadow_peer_find(byref(mgr), node_id.encode("utf-8"))
    return ptr if bool(ptr) else None


def memshadow_peer_select(mgr: memshadow_peer_manager_t) -> Optional[POINTER(memshadow_peer_info_t)]:
    """Select best healthy peer based on configured selection strategy."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    ptr = _msnet_lib.memshadow_peer_select(byref(mgr))
    return ptr if bool(ptr) else None


def memshadow_peer_connect(mgr: memshadow_peer_manager_t, node_id: str) -> None:
    """Mark peer status as connected."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_peer_connect(byref(mgr), node_id.encode("utf-8"))


def memshadow_peer_disconnect(mgr: memshadow_peer_manager_t, node_id: str) -> None:
    """Mark peer status as disconnected."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_peer_disconnect(byref(mgr), node_id.encode("utf-8"))


def memshadow_peer_ban(mgr: memshadow_peer_manager_t, node_id: str) -> None:
    """Ban peer for configured ban duration."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_peer_ban(byref(mgr), node_id.encode("utf-8"))


def memshadow_peer_tick(mgr: memshadow_peer_manager_t) -> None:
    """Tick peer manager for timeouts and unbans."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_peer_tick(byref(mgr))


def memshadow_peer_record_ping(peer: POINTER(memshadow_peer_info_t), latency_ms: float) -> None:
    """Record successful ping response with latency."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if peer:
        _msnet_lib.memshadow_peer_record_ping(peer, latency_ms)


def memshadow_peer_record_ping_failure(peer: POINTER(memshadow_peer_info_t)) -> None:
    """Record ping timeout or failure."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if peer:
        _msnet_lib.memshadow_peer_record_ping_failure(peer)


def memshadow_peer_is_healthy(health: memshadow_peer_health_t) -> bool:
    """Check if peer health parameters satisfy health thresholds."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return bool(_msnet_lib.memshadow_peer_is_healthy(byref(health)))


def memshadow_peer_health_score(health: memshadow_peer_health_t) -> float:
    """Compute overall health score (0.0 to 1.0) for peer."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return float(_msnet_lib.memshadow_peer_health_score(byref(health)))


def memshadow_peer_connected_count(mgr: memshadow_peer_manager_t) -> int:
    """Get count of connected peers."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_peer_connected_count(byref(mgr)))


# ============================================================================
# Post-Quantum Cryptography (PQC) Functions
# ============================================================================

def memshadow_pqc_init(algorithm: int = PQC_ALGORITHM_HYBRID_X25519_KYBER) -> POINTER(memshadow_pqc_manager_t):
    """Initialize PQC manager with chosen algorithm."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    mgr = POINTER(memshadow_pqc_manager_t)()
    res = _msnet_lib.memshadow_pqc_init(byref(mgr), algorithm)
    if res != PQC_SUCCESS:
        raise ValueError(f"Failed to initialize PQC manager: error {res}")
    return mgr


def memshadow_pqc_generate_keypair(mgr: POINTER(memshadow_pqc_manager_t)) -> memshadow_hybrid_keypair_t:
    """Generate hybrid classical + post-quantum keypair."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    kp = memshadow_hybrid_keypair_t()
    res = _msnet_lib.memshadow_pqc_generate_keypair(mgr, byref(kp))
    if res != PQC_SUCCESS:
        raise ValueError(f"Failed to generate PQC keypair: error {res}")
    return kp


def memshadow_pqc_cleanup(mgr: POINTER(memshadow_pqc_manager_t)) -> None:
    """Clean up PQC manager instance."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if mgr:
        _msnet_lib.memshadow_pqc_cleanup(mgr)


def memshadow_pqc_key_exchange(
    mgr: POINTER(memshadow_pqc_manager_t),
    my_private_key: bytes,
    peer_public_key: bytes
) -> bytes:
    """
    Perform key exchange to derive shared secret.

    Returns:
        32-byte shared secret bytes
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    c_priv = (c_uint8 * len(my_private_key)).from_buffer_copy(my_private_key)
    c_pub = (c_uint8 * len(peer_public_key)).from_buffer_copy(peer_public_key)
    secret_out = (c_uint8 * 32)()
    secret_len = c_size_t(32)

    res = _msnet_lib.memshadow_pqc_key_exchange(
        mgr, c_priv, len(my_private_key), c_pub, len(peer_public_key), secret_out, byref(secret_len)
    )
    if res != PQC_SUCCESS:
        raise ValueError(f"Failed to perform PQC key exchange: error {res}")
    return bytes(secret_out[:secret_len.value])


def memshadow_hybrid_keypair_init(algorithm: int = PQC_ALGORITHM_HYBRID_X25519_KYBER) -> memshadow_hybrid_keypair_t:
    """Initialize empty hybrid keypair structure."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    kp = memshadow_hybrid_keypair_t()
    res = _msnet_lib.memshadow_hybrid_keypair_init(byref(kp), algorithm)
    if res != PQC_SUCCESS:
        raise ValueError(f"Failed to initialize hybrid keypair: error {res}")
    return kp


def memshadow_hybrid_keypair_cleanup(kp: memshadow_hybrid_keypair_t) -> None:
    """Free memory associated with hybrid keypair."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_hybrid_keypair_cleanup(byref(kp))


def memshadow_pqc_error_message(error: int) -> str:
    """Get human-readable PQC error description."""
    if _msnet_lib is None:
        return f"PQC error {error}"
    ptr = _msnet_lib.memshadow_pqc_error_message(error)
    if ptr:
        return ptr.decode("utf-8")
    return f"PQC error {error}"


# ============================================================================
# Gossip Protocol Functions
# ============================================================================

def memshadow_gossip_peer_init(peer_id: str, address: str, port: int) -> memshadow_gossip_peer_t:
    """Initialize a gossip peer structure."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    peer = memshadow_gossip_peer_t()
    res = _msnet_lib.memshadow_gossip_peer_init(
        byref(peer), peer_id.encode("utf-8"), address.encode("utf-8"), port
    )
    if res != 0:
        raise ValueError(f"Failed to initialize gossip peer: error {res}")
    return peer


def memshadow_gossip_peer_cleanup(peer: memshadow_gossip_peer_t) -> None:
    """Clean up allocated memory inside gossip peer."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_gossip_peer_cleanup(byref(peer))


def memshadow_gossip_peer_update_last_seen(peer: memshadow_gossip_peer_t) -> None:
    """Update last seen timestamp and heartbeat counter for gossip peer."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_gossip_peer_update_last_seen(byref(peer))


def memshadow_gossip_manager_init(
    node_id: str,
    fan_out: int = 3,
    gossip_interval_ms: int = 1000
) -> POINTER(memshadow_gossip_manager_t):
    """Initialize gossip manager instance."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    mgr = POINTER(memshadow_gossip_manager_t)()
    res = _msnet_lib.memshadow_gossip_manager_init(
        byref(mgr), node_id.encode("utf-8"), fan_out, gossip_interval_ms
    )
    if res != 0:
        raise ValueError(f"Failed to initialize gossip manager: error {res}")
    return mgr


def memshadow_gossip_manager_add_peer(
    mgr: POINTER(memshadow_gossip_manager_t),
    peer: memshadow_gossip_peer_t
) -> int:
    """Add peer to gossip manager peer list."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_gossip_manager_add_peer(mgr, peer))


def memshadow_gossip_manager_remove_peer(
    mgr: POINTER(memshadow_gossip_manager_t),
    peer_id: str
) -> bool:
    """Remove peer from gossip manager by peer ID."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return bool(_msnet_lib.memshadow_gossip_manager_remove_peer(mgr, peer_id.encode("utf-8")))


def memshadow_gossip_manager_broadcast_message(
    mgr: POINTER(memshadow_gossip_manager_t),
    msg_type: int,
    payload: bytes,
    ttl: int = 3
) -> int:
    """Broadcast a new message via epidemic gossip."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    p_buf = (c_uint8 * len(payload)).from_buffer_copy(payload) if payload else None
    return int(_msnet_lib.memshadow_gossip_manager_broadcast_message(
        mgr, msg_type, p_buf, len(payload), ttl
    ))


def memshadow_gossip_manager_receive_message(
    mgr: POINTER(memshadow_gossip_manager_t),
    message: memshadow_gossip_message_t,
    from_peer: str
) -> int:
    """Process incoming gossip message from peer."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_gossip_manager_receive_message(
        mgr, message, from_peer.encode("utf-8")
    ))


def memshadow_gossip_manager_perform_gossip_round(
    mgr: POINTER(memshadow_gossip_manager_t)
) -> List[Tuple[str, memshadow_gossip_message_t]]:
    """
    Perform a gossip round and return list of (peer_id, message) to transmit.
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    out_msgs = POINTER(memshadow_gossip_outgoing_message_t)()
    out_count = c_size_t(0)

    res = _msnet_lib.memshadow_gossip_manager_perform_gossip_round(
        mgr, byref(out_msgs), byref(out_count)
    )
    if res != 0:
        raise ValueError(f"Failed to perform gossip round: error {res}")

    results = []
    if out_msgs and out_count.value > 0:
        for i in range(out_count.value):
            item = out_msgs[i]
            target_peer = item.peer_id.decode("utf-8") if item.peer_id else ""
            results.append((target_peer, item.message))
    return results


def memshadow_gossip_manager_cleanup(mgr: POINTER(memshadow_gossip_manager_t)) -> None:
    """Clean up gossip manager instance."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if mgr:
        _msnet_lib.memshadow_gossip_manager_cleanup(mgr)


def memshadow_gossip_peer_increase_suspicion(peer: memshadow_gossip_peer_t) -> None:
    """Increase suspicion score for peer."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_gossip_peer_increase_suspicion(byref(peer))


def memshadow_gossip_peer_is_suspected_failed(peer: memshadow_gossip_peer_t, threshold: float = 3.0) -> bool:
    """Check if peer exceeds suspicion failure threshold."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return bool(_msnet_lib.memshadow_gossip_peer_is_suspected_failed(byref(peer), threshold))


def memshadow_gossip_message_init(
    msg_type: int,
    sender_id: str,
    payload: bytes = b"",
    ttl: int = 3
) -> memshadow_gossip_message_t:
    """Initialize a new gossip message structure."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    msg = memshadow_gossip_message_t()
    p_buf = (c_uint8 * len(payload)).from_buffer_copy(payload) if payload else None
    res = _msnet_lib.memshadow_gossip_message_init(
        byref(msg), msg_type, sender_id.encode("utf-8"), p_buf, len(payload), ttl
    )
    if res != 0:
        raise ValueError(f"Failed to initialize gossip message: error {res}")
    return msg


def memshadow_gossip_message_cleanup(msg: memshadow_gossip_message_t) -> None:
    """Clean up memory allocated inside gossip message."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_gossip_message_cleanup(byref(msg))


def memshadow_gossip_message_is_expired(msg: memshadow_gossip_message_t) -> bool:
    """Check if gossip message TTL has reached 0."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return bool(_msnet_lib.memshadow_gossip_message_is_expired(byref(msg)))


def memshadow_gossip_message_decrement_ttl(msg: memshadow_gossip_message_t) -> None:
    """Decrement gossip message TTL and increment hop count."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_gossip_message_decrement_ttl(byref(msg))


def memshadow_gossip_message_id_equals(id1: bytes, id2: bytes) -> bool:
    """Check if two 16-byte message UUIDs are equal."""
    if _msnet_lib is None:
        return id1 == id2
    c_id1 = (c_uint8 * 16).from_buffer_copy(id1)
    c_id2 = (c_uint8 * 16).from_buffer_copy(id2)
    return bool(_msnet_lib.memshadow_gossip_message_id_equals(c_id1, c_id2))


def memshadow_gossip_outgoing_messages_cleanup(messages: POINTER(memshadow_gossip_outgoing_message_t), count: int) -> None:
    """Clean up dynamic array of outgoing gossip messages."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    if messages and count > 0:
        _msnet_lib.memshadow_gossip_outgoing_messages_cleanup(messages, count)


def memshadow_gossip_manager_run_failure_detection(mgr: POINTER(memshadow_gossip_manager_t)) -> int:
    """Run failure detection cycle across gossip peers."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    return int(_msnet_lib.memshadow_gossip_manager_run_failure_detection(mgr))


def memshadow_gossip_manager_tick(mgr: POINTER(memshadow_gossip_manager_t)) -> int:
    """Tick gossip manager for failure detection and maintenance."""
    return memshadow_gossip_manager_run_failure_detection(mgr)


def memshadow_gossip_manager_get_statistics(mgr: POINTER(memshadow_gossip_manager_t)) -> memshadow_gossip_statistics_t:
    """Get gossip protocol statistics."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    stats = memshadow_gossip_statistics_t()
    _msnet_lib.memshadow_gossip_manager_get_statistics(mgr, byref(stats))
    return stats


def memshadow_gossip_manager_cleanup_old_messages(mgr: POINTER(memshadow_gossip_manager_t), max_age_ns: int = 300_000_000_000) -> None:
    """Clean up seen message cache older than max_age_ns."""
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")
    _msnet_lib.memshadow_gossip_manager_cleanup_old_messages(mgr, max_age_ns)


def memshadow_gossip_manager_perform_anti_entropy(
    mgr: POINTER(memshadow_gossip_manager_t),
    remote_message_ids: List[bytes]
) -> List[memshadow_gossip_message_t]:
    """
    Perform anti-entropy synchronization against a remote node's message list.

    Returns:
        List of missing messages that local node has and remote node needs.
    """
    if _msnet_lib is None:
        raise RuntimeError("MSNET native library not available")

    remote_count = len(remote_message_ids)
    c_remote_ids = None
    if remote_count > 0:
        c_remote_ids = ((c_uint8 * 16) * remote_count)()
        for i, mid in enumerate(remote_message_ids):
            for b in range(min(16, len(mid))):
                c_remote_ids[i][b] = mid[b]

    missing_msgs = POINTER(memshadow_gossip_message_t)()
    missing_count = c_size_t(0)

    res = _msnet_lib.memshadow_gossip_manager_perform_anti_entropy(
        mgr, c_remote_ids, remote_count, byref(missing_msgs), byref(missing_count)
    )
    if res != 0:
        raise ValueError(f"Failed to perform anti-entropy: error {res}")

    result = []
    if missing_msgs and missing_count.value > 0:
        for i in range(missing_count.value):
            result.append(missing_msgs[i])
    return result
