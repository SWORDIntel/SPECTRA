# KEYSTONE Vector Engine — Revised Plan (v2.0)

**Revision summary:** VPU coupling removed entirely. The engine is now a hardware-agnostic vector store/search library. All acceleration is optional and layered behind a 7-level runtime dispatch chain with compile-time guards. The scalar path is always compiled and is the correctness baseline for everything else.

---

## Part 1: Revised `keystone_vector_engine.h`

```c
/*
 * keystone_vector_engine.h — KEYSTONE Vector Engine
 *
 * DESIGN PRINCIPLES (v2.0 revision):
 *
 *  1. HARDWARE AGNOSTIC INPUT. This library stores and searches float32
 *     arrays. It has NO knowledge of where vectors came from (VPU, CPU,
 *     GPU, hash_bow, or any future source). Embedding generation is a
 *     separate concern handled at the Python layer.
 *
 *  2. NO VPU CODE. There are no VPU sockets, no framing protocols, no
 *     Myriad X references, and no VPU fields in any struct in this
 *     library. VPU integration (if used at all) lives in
 *     myriad_embedding_server.py, which calls
 *     keystone_vector_engine.upsert_batch() via ctypes like any other
 *     client.
 *
 *  3. GRACEFUL FALLBACK CHAIN. Runtime dispatch order (highest first):
 *
 *        1. CUDA GPU present + init OK?      -> CUDA batch path
 *        2. AVX-512 present?                 -> AVX-512 SIMD path
 *        3. AVX2 present?                    -> AVX2 SIMD path
 *        4. AVX present?                     -> AVX SIMD path
 *                                              (256-bit YMM, float ops
 *                                              only — no integer SIMD,
 *                                              no FMA, per Intel guidance
 *                                              for Sandy Bridge compat)
 *        5. SSE4.2 present?                  -> SSE4.2 SIMD path
 *        6. NEON present (ARM64/ARMv7)?      -> NEON SIMD path
 *        7. None of the above?               -> Scalar C path
 *                                              (portable, ALWAYS compiled,
 *                                              works on any Linux box
 *                                              with a C compiler)
 *
 *     If CUDA init fails at runtime (driver crash, OOM, device lost),
 *     the engine degrades to the best available CPU SIMD level.
 *     If SIMD detection fails or a SIMD path was not compiled in,
 *     the engine degrades to scalar. The engine NEVER crashes due to
 *     missing hardware.
 *
 *  4. DUAL DETECTION. SIMD paths are BOTH compile-time guarded
 *     (#ifdef __AVX512F__ etc., so the build machine only compiles
 *     what it supports) AND runtime detected (CPUID on x86, getauxval
 *     on ARM), so a binary built on an AVX-512 server still runs
 *     correctly on an SSE2-only box via runtime dispatch.
 *
 *  5. CUDA IS SOFT-LOADED. libkeystone_cuda.so is dlopen()'d at
 *     runtime. The core library never links against CUDA at build
 *     time, so it builds and runs on machines with no CUDA toolkit
 *     and no GPU.
 */

#ifndef KEYSTONE_VECTOR_ENGINE_H
#define KEYSTONE_VECTOR_ENGINE_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define KEYSTONE_VERSION_MAJOR 2
#define KEYSTONE_VERSION_MINOR 0

/* ---------------------------------------------------------------
 * Error codes
 * --------------------------------------------------------------- */
typedef enum {
    KEYSTONE_OK              = 0,
    KEYSTONE_ERR_NULL        = -1,   /* NULL argument            */
    KEYSTONE_ERR_PARAM       = -2,   /* bad parameter           */
    KEYSTONE_ERR_DIM         = -3,   /* dimension mismatch      */
    KEYSTONE_ERR_OOM         = -4,   /* allocation failure      */
    KEYSTONE_ERR_CAPACITY    = -5,   /* engine full             */
    KEYSTONE_ERR_IO         = -6,   /* persistence I/O failure */
    KEYSTONE_ERR_INTERNAL    = -7
} keystone_error_t;

/* ---------------------------------------------------------------
 * Backend identifiers — mirrors the fallback chain exactly.
 * --------------------------------------------------------------- */
typedef enum {
    KEYSTONE_BACKEND_SCALAR  = 0,   /* level 7: portable baseline  */
    KEYSTONE_BACKEND_SSE42   = 1,   /* level 5                    */
    KEYSTONE_BACKEND_AVX     = 2,   /* level 4: YMM, float only   */
    KEYSTONE_BACKEND_AVX2    = 3,   /* level 3                    */
    KEYSTONE_BACKEND_AVX512  = 4,   /* level 2                    */
    KEYSTONE_BACKEND_NEON    = 5,   /* level 6 (ARM)              */
    KEYSTONE_BACKEND_CUDA    = 6    /* level 1                    */
} keystone_backend_t;

/* ---------------------------------------------------------------
 * CPU feature flags (runtime detection result)
 * --------------------------------------------------------------- */
typedef enum {
    KEYSTONE_F_SSE42    = 1 << 0,
    KEYSTONE_F_AVX      = 1 << 1,   /* 256-bit YMM available, OS-enabled */
    KEYSTONE_F_AVX2     = 1 << 2,
    KEYSTONE_F_AVX512F  = 1 << 3,
    KEYSTONE_F_NEON     = 1 << 4
} keystone_cpu_features_t;

/* ---------------------------------------------------------------
 * Distance metrics
 * --------------------------------------------------------------- */
typedef enum {
    KEYSTONE_METRIC_L2      = 0,
    KEYSTONE_METRIC_DOT     = 1,    /* inner product        */
    KEYSTONE_METRIC_COSINE  = 2     /* normalized L2 equiv. */
} keystone_metric_t;

/* ---------------------------------------------------------------
 * Engine configuration
 *
 * NOTE: There are deliberately NO VPU fields here. No socket paths,
 * no framing, no Myriad references. Vectors arrive via
 * keystone_upsert_batch() from whatever process computed them.
 * --------------------------------------------------------------- */
typedef struct {
    uint32_t    dim;                /* vector dimension (e.g. 384)   */
    uint32_t    capacity;           /* max number of vectors        */
    keystone_metric_t metric;

    /* LSH coarse-index parameters (retained from v1 plan) */
    uint32_t    lsh_num_tables;     /* e.g. 8                       */
    uint32_t    lsh_hash_bits;      /* e.g. 12 -> 4096 buckets      */
    uint32_t    lsh_probes;          /* multiprobe count, e.g. 4    */
    uint32_t    rerank_k;            /* candidates to exact-rerank  */

    /* Threading */
    int         omp_threads;         /* 0 = let OpenMP decide       */

    /* Backend override: KEYSTONE_BACKEND_SCALAR forces scalar even
     * on AVX-512 hardware (useful for testing / correctness diffs).
     * Pass -1 for automatic dispatch. */
    int         force_backend;
} keystone_config_t;

/* Opaque engine handle */
typedef struct keystone_engine keystone_engine_t;

/* ---------------------------------------------------------------
 * Search result
 * --------------------------------------------------------------- */
typedef struct {
    uint64_t    id;
    float       distance;
} keystone_result_t;

/* ---------------------------------------------------------------
 * Runtime hardware detection
 *
 * Returns feature flags detected at runtime (CPUID on x86/x86-64,
 * getauxval(AT_HWCAP) on ARM). Always succeeds; returns 0 on any
 * machine with no SIMD — which is a fully supported configuration.
 * --------------------------------------------------------------- */
uint32_t keystone_detect_cpu_features(void);

/* Returns human-readable name of the backend the engine selected,
 * e.g. "avx2", "scalar", "cuda". Never returns NULL. */
const char *keystone_backend_name(keystone_backend_t b);

/* ---------------------------------------------------------------
 * Lifecycle
 * --------------------------------------------------------------- */
keystone_error_t keystone_engine_create(const keystone_config_t *cfg,
                                        keystone_engine_t **out);

void             keystone_engine_destroy(keystone_engine_t *e);

/* Which backend is this engine actually using right now? After a
 * CUDA runtime failure this will report the CPU backend it fell
 * back to. */
keystone_backend_t keystone_engine_get_backend(const keystone_engine_t *e);

/* ---------------------------------------------------------------
 * Vector I/O — the ONLY input path. Hardware-agnostic.
 *
 * Vectors are float32 arrays of engine->dim. Where they were
 * computed (VPU / CPU / GPU / hash_bow / anything) is irrelevant.
 * --------------------------------------------------------------- */
keystone_error_t keystone_upsert_batch(keystone_engine_t *e,
                                       const uint64_t *ids,
                                       const float *vectors,   /* row-major, n*dim */
                                       uint32_t n);

/* Batch search. queries is row-major nq*dim. Results are
 * per-query arrays of rerank_k (id, distance) pairs, best-first.
 * OpenMP-parallel across queries when available. */
keystone_error_t keystone_search_batch(keystone_engine_t *e,
                                       const float *queries,  /* nq*dim */
                                       uint32_t nq,
                                       uint32_t k,
                                       keystone_result_t *results /* nq*k */);

/* Single-query convenience wrapper (calls the batch path with nq=1). */
keystone_error_t keystone_search(keystone_engine_t *e,
                                 const float *query,
                                 uint32_t k,
                                 keystone_result_t *results);

/* ---------------------------------------------------------------
 * Persistence
 * --------------------------------------------------------------- */
keystone_error_t keystone_save(const keystone_engine_t *e, const char *path);
keystone_error_t keystone_load(keystone_engine_t **e, const char *path);

/* ---------------------------------------------------------------
 * Introspection
 * --------------------------------------------------------------- */
uint32_t    keystone_engine_dim(const keystone_engine_t *e);
uint64_t    keystone_engine_count(const keystone_engine_t *e);

#ifdef __cplusplus
}
#endif

#endif /* KEYSTONE_VECTOR_ENGINE_H */
```

**What was removed vs. v1:** `vpu_socket_path`, `vpu_framing_*` fields, `keystone_vpu_*` functions, any Myriad X includes, and the "VPU listener" lifecycle hooks. **What was added:** `keystone_backend_t` mirroring the 7-level chain, `keystone_detect_cpu_features()`, `force_backend` for testing, and `keystone_engine_get_backend()` so callers can observe fallback after CUDA loss.

---

## Part 2: Revised Implementation Plan

### 2.1 The Complete Fallback Dispatch Table

| Level | Backend | Compile-time guard | Runtime detection | Kernel file | Compiled when? |
|---|---|---|---|---|---|
| 1 | CUDA | `KEYSTONE_HAVE_CUDA` (CMake/`build.sh` flag only — never a `#ifdef` in core code; CUDA lives in a separate `.so`) | `dlopen("libkeystone_cuda.so")` + `cudaInit` + device query + context creation all succeed | `keystone_cuda.cu` | Only if `nvcc` found AND user didn't pass `--no-cuda` |
| 2 | AVX-512 | `#ifdef __AVX512F__` | CPUID leaf 7 EBX bit 16 **and** CPUID leaf 1 ECX bit 27 (OSXSAVE) **and** `_xgetbv(0) & 0xE6 == 0xE6` | `kernels_avx512.c` (compiled with `-mavx512f -mavx512dq`) | Only if compiler accepts `-mavx512f` |
| 3 | AVX2 | `#ifdef __AVX2__` | CPUID leaf 7 EBX bit 5, plus AVX OS check above | `kernels_avx2.c` (`-mavx2 -mfma`) | Only if compiler accepts `-mavx2` |
| 4 | AVX | `#ifdef __AVX__` | CPUID leaf 1 ECX bit 28 **and** OSXSAVE **and** `_xgetbv(0) & 0x6 == 0x6` | `kernels_avx.c` (`-mavx`, **float ops only**, no integer SIMD, no FMA — per Intel's guidance so the code is safe on Sandy Bridge-era AVX) | Only if compiler accepts `-mavx` |
| 5 | SSE4.2 | `#ifdef __SSE4_2__` | CPUID leaf 1 ECX bit 20 | `kernels_sse42.c` (`-msse4.2`) | Only if compiler accepts `-msse4.2` |
| 6 | NEON | `#ifdef __ARM_NEON` | `getauxval(AT_HWCAP) & HWCAP_NEON` (aarch64: always present, but check anyway) | `kernels_neon.c` (`-mfpu=neon` / nothing on aarch64) | Only on ARM with NEON support |
| 7 | Scalar | none — **no guard, ever** | none — **always available** | `kernels_scalar.c` (no ISA flags, `-O2` only) | **ALWAYS. Unconditionally. On every build.** |

### 2.2 How Dispatch Works — Function Pointer Table

Each backend compiles to the same kernel ABI:

```c
/* kernel_dispatch.h — internal */
typedef struct {
    /* Exact distance between one query and one stored vector */
    float (*dist1)(const float *a, const float *b, uint32_t dim);
    /* Block of 8/16 candidates — SIMD backends process lanes in parallel */
    void  (*dist8)(const float *q, const float * const *cands,
                   uint32_t dim, float out[8]);
} keystone_kernels_t;

extern const keystone_kernels_t keystone_kernels_scalar;  /* always linked */
#ifdef __AVX512F__
extern const keystone_kernels_t keystone_kernels_avx512;
#endif
/* ... one extern per compiled backend ... */
```

At `keystone_engine_create()`:

```c
static keystone_error_t select_kernels(keystone_engine_t *e) {
    uint32_t f = keystone_detect_cpu_features();

    /* Level 1: CUDA — soft-loaded, never required */
    if (e->cfg.force_backend < 0 || e->cfg.force_backend == KEYSTONE_BACKEND_CUDA) {
        if (keystone_cuda_try_init(e)) {          /* dlopen + init */
            e->backend = KEYSTONE_BACKEND_CUDA;
            return KEYSTONE_OK;                   /* kernels live on GPU */
        }
        /* CUDA absent OR init failed (no driver, OOM, device lost).
         * NOT an error. Silently continue down the chain. */
    }

    /* Levels 2–6: CPU SIMD, highest compiled-and-present wins */
    const keystone_kernels_t *k = &keystone_kernels_scalar;  /* level 7 default */
    keystone_backend_t b = KEYSTONE_BACKEND_SCALAR;

#if defined(__AVX512F__)
    if (f & KEYSTONE_F_AVX512F) { k = &keystone_kernels_avx512; b = KEYSTONE_BACKEND_AVX512; }
    else
#endif
#if defined(__AVX2__)
    if (f & KEYSTONE_F_AVX2)     { k = &keystone_kernels_avx2;   b = KEYSTONE_BACKEND_AVX2;   }
    else
#endif
#if defined(__AVX__)
    if (f & KEYSTONE_F_AVX)      { k = &keystone_kernels_avx;    b = KEYSTONE_BACKEND_AVX;    }
    else
#endif
#if defined(__SSE4_2__)
    if (f & KEYSTONE_F_SSE42)    { k = &keystone_kernels_sse42;  b = KEYSTONE_BACKEND_SSE42;  }
    else
#endif
#if defined(__ARM_NEON)
    if (f & KEYSTONE_F_NEON)     { k = &keystone_kernels_neon;   b = KEYSTONE_BACKEND_NEON;   }
    else
#endif
    { /* scalar — the else-branch that can never be compiled out */ }

    e->kernels = k;
    e->backend = b;
    return KEYSTONE_OK;   /* dispatch CANNOT fail: scalar is always linked */
}
```

Key property: because the scalar extern is unconditional and the final `else` needs no guard, **dispatch is structurally incapable of failing**. Every `#if` that evaluates false just falls through to the next level, and the last resort is always present.

### 2.3 CUDA Init Failure → CPU Degradation (runtime, mid-session too)

`keystone_cuda_try_init()` does, in order: `dlopen("libkeystone_cuda.so")` → resolve `keystone_cuda_init` → `cudaSetDevice` → allocate pinned scratch buffers. Any failure at any step → `dlclose`, return false, log one line to stderr, continue to CPU dispatch. **No error propagates to the caller.**

Mid-session degradation: every CUDA-path call in `keystone_search_batch` checks the return status. On `cudaErrorDeviceLost` / `cudaErrorOutOfMemory` / context-destroyed:

```c
if (cuda_err != CUDA_SUCCESS) {
    /* Flip to CPU kernels permanently for this engine, re-run the
     * current batch on CPU, free GPU resources. Search still returns
     * correct results — just slower. */
    keystone_cuda_teardown(e);
    e->kernels = &keystone_kernels_scalar_or_best_cpu(e);
    e->backend = best_cpu_backend(e);
    return keystone_search_batch_cpu(e, queries, nq, k, results);
}
```

The caller never sees an error; the next `keystone_engine_get_backend()` call reports the CPU backend. This is the "engine must NEVER crash due to missing hardware" guarantee.

### 2.4 Missing SIMD → Scalar Degradation

Two distinct scenarios, both handled:

1. **SIMD not compiled in** (built on a Pi, run on an AVX-512 box): the `#ifdef` blocks don't exist; runtime CPUID flags are irrelevant; scalar is selected. Correct, just not optimal.
2. **SIMD compiled in but not present at runtime** (built on AVX-512 server, binary copied to an ancient SSE2-only Xeon): `keystone_detect_cpu_features()` returns only `KEYSTONE_F_SSE42` (or 0); the `#if` chain skips down to the highest flag that is both compiled AND detected. **This is why runtime detection is mandatory even when compile-time guards exist** — the guards alone would let AVX-512 code execute on a machine that faults on EVEX encodings.

`keystone_detect_cpu_features()` implementation notes:
- x86: `__cpuid` / inline asm, leaf 1 (SSE4.2 bit 20, AVX bit 28, OSXSAVE bit 27), leaf 7 (AVX2 bit 5, AVX512F bit 16), plus `_xgetbv` to confirm the OS actually saves YMM/ZMM state (a VM with AVX masked off must not select AVX).
- ARM: `getauxval(AT_HWCAP)` — `HWCAP_NEON` on 32-bit, `HWCAP_ASIMD` on aarch64.
- Any failure path (unknown arch, cpuid fault): return 0 → scalar. Detection itself can't crash the engine.

### 2.5 `build.sh` — Auto-detect, Always Compile Scalar

```bash
#!/usr/bin/env bash
set -euo pipefail
CC=${CC:-cc}
CFLAGS_BASE="-O2 -fPIC -std=c11 -Wall -Wextra"
OBJS="keystone_engine.o kernels_scalar.o lsh.o persist.o dispatch.o"
HAVE_CUDA=0

try_compile_flag() {  # $1 = flag; returns 0 if the compiler accepts it
    printf 'int main(void){return 0;}' > /tmp/ks_test.c
    $CC $CFLAGS_BASE "$1" -c /tmp/ks_test.c -o /tmp/ks_test.o 2>/dev/null
}

# ---- Level 7: SCALAR — ALWAYS COMPILED, NO CONDITIONS ----
$CC $CFLAGS_BASE -c kernels_scalar.c -o kernels_scalar.o

# ---- Levels 2-5: x86 SIMD — compile only what this machine's compiler supports ----
if try_compile_flag -msse4.2; then
    $CC $CFLAGS_BASE -msse4.2  -c kernels_sse42.c  -o kernels_sse42.o  && OBJS+=" kernels_sse42.o"
fi
if try_compile_flag -mavx; then
    # AVX level: float ops only (see header comment) — no -mfma, no integer SIMD
    $CC $CFLAGS_BASE -mavx     -c kernels_avx.c    -o kernels_avx.o    && OBJS+=" kernels_avx.o"
fi
if try_compile_flag -mavx2; then
    $CC $CFLAGS_BASE -mavx2 -mfma -c kernels_avx2.c -o kernels_avx2.o && OBJS+=" kernels_avx2.o"
fi
if try_compile_flag -mavx512f; then
    $CC $CFLAGS_BASE -mavx512f -mavx512dq -c kernels_avx512.c -o kernels_avx512.o \
        && OBJS+=" kernels_avx512.o"
fi

# ---- Level 6: NEON (ARM only) ----
if [ "$(uname -m)" = "aarch64" ] || try_compile_flag -mfpu=neon; then
    $CC $CFLAGS_BASE -c kernels_neon.c -o kernels_neon.o 2>/dev/null && OBJS+=" kernels_neon.o"
fi

# ---- Core (compiled with NO ISA flags — must run everywhere) ----
$CC $CFLAGS_BASE $(pkg-config --cflags omp 2>/dev/null || echo) \
    -c keystone_engine.c -o keystone_engine.o
$CC $CFLAGS_BASE -c lsh.c -o lsh.o
$CC $CFLAGS_BASE -c dispatch.c -o dispatch.o
$CC $CFLAGS_BASE -c persist.c -o persist.o

# ---- Level 1: CUDA — optional shared module, dlopen'd at runtime ----
if command -v nvcc >/dev/null 2>&1 && [ "${KEYSTONE_NO_CUDA:-0}" != "1" ]; then
    nvcc -O3 -shared -Xcompiler -fPIC keystone_cuda.cu -o libkeystone_cuda.so \
        && HAVE_CUDA=1 \
        || echo "keystone: nvcc present but CUDA build failed — building CPU-only (OK)"
fi

$CC $CFLAGS_BASE -shared -o libkeystone.so $OBJS -lm $(pkg-config --libs omp 2>/dev/null || echo)

echo "keystone: built. backends compiled: scalar(always)$(echo $OBJS | grep -o 'avx512\|avx2\|avx\|sse42\|neon' | sort -u | tr '\n' ' ')cuda=${HAVE_CUDA}"
```

Critical build invariants:
- `kernels_scalar.c` is compiled with **zero** ISA flags and **zero** conditions — it builds with any C compiler on any Linux box.
- Core files (`keystone_engine.c`, `lsh.c`, `dispatch.c`) are compiled with no ISA flags, so the dispatch code itself never faults on an old CPU. Only the per-backend kernel translation units carry `-m*` flags.
- CUDA is a **separate `.so`**; the core library never links it. `KEYSTONE_NO_CUDA=1` skips it; nvcc failure is a warning, not an error.

### 2.6 Retained from v1 (unchanged in spirit)

- **LSH coarse index:** `lsh_num_tables` random hyperplane hash tables → candidate bucket union + multiprobe → exact rerank of `rerank_k` candidates using the selected kernel. Rerank always uses the *same* kernel ABI, so LSH logic is backend-independent.
- **AVX intrinsics:** `_mm256_ps` dot/L2 loops in `kernels_avx.c` (float-only), FMA-fused loops in `kernels_avx2.c`, masked 16-wide loops in `kernels_avx512.c`.
- **OpenMP batch:** `#pragma omp parallel for` over queries in `keystone_search_batch` and over rows in `keystone_upsert_batch`; if OpenMP isn't available, a `#ifdef _OPENMP` guard reduces to serial loops (another fallback).
- **CUDA kernel:** batched matrix of candidates → GPU distance kernel → top-k on GPU. Now wrapped in the soft-load + mid-session-degradation shell described in 2.3.

### 2.7 VPU Section (replaces all v1 VPU content)

> **VPU integration is handled at the Python layer.** The `myriad_embedding_server.py` generates vectors and passes them to `keystone_vector_engine.upsert_batch()` via ctypes. No VPU-specific code exists in the C library. The engine does not listen on any socket, does not know the VPU exists, and works identically with VPU, CPU SentenceTransformer, hash_bow, or any future embedding source — they are all just callers of `upsert_batch`.

---

## Part 3: Revised Python Bindings (`keystone_vector_engine.py`)

```python
"""
KEYSTONE Vector Engine — Python ctypes bindings.

Embedding-source agnostic. This module stores and searches float32
vectors. It has NO VPU code, NO sockets, NO framing. Embedding
generation (VPU / CPU / hash_bow / anything) happens in other modules,
which call upsert_batch() here.
"""
import ctypes
import numpy as np
from pathlib import Path

_LIB = ctypes.CDLL(str(Path(__file__).parent / "libkeystone.so"))

# --- enums (mirror the header) ---
SCALAR, SSE42, AVX, AVX2, AVX512, NEON, CUDA = 0, 1, 2, 3, 4, 5, 6
L2, DOT, COSINE = 0, 1, 2

class _Config(ctypes.Structure):
    _fields_ = [
        ("dim", ctypes.c_uint32),
        ("capacity", ctypes.c_uint32),
        ("metric", ctypes.c_int),
        ("lsh_num_tables", ctypes.c_uint32),
        ("lsh_hash_bits", ctypes.c_uint32),
        ("lsh_probes", ctypes.c_uint32),
        ("rerank_k", ctypes.c_uint32),
        ("omp_threads", ctypes.c_int),
        ("force_backend", ctypes.c_int),   # -1 = auto dispatch
    ]

class _Result(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint64), ("distance", ctypes.c_float)]

_LIB.keystone_engine_create.restype = ctypes.c_int
_LIB.keystone_engine_create.argtypes = [ctypes.POINTER(_Config),
                                        ctypes.POINTER(ctypes.c_void_p)]
_LIB.keystone_upsert_batch.restype = ctypes.c_int
_LIB.keystone_upsert_batch.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_uint64),
                                       ctypes.POINTER(ctypes.c_float),
                                       ctypes.c_uint32]
_LIB.keystone_search_batch.restype = ctypes.c_int
_LIB.keystone_search_batch.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_float),
                                       ctypes.c_uint32, ctypes.c_uint32,
                                       ctypes.POINTER(_Result)]
_LIB.keystone_engine_get_backend.restype = ctypes.c_int
_LIB.keystone_engine_get_backend.argtypes = [ctypes.c_void_p]
_LIB.keystone_backend_name.restype = ctypes.c_char_p
_LIB.keystone_backend_name.argtypes = [ctypes.c_int]
_LIB.keystone_engine_destroy.restype = None
_LIB.keystone_engine_destroy.argtypes = [ctypes.c_void_p]


class KeystoneVectorEngine:
    """Hardware-agnostic vector store. Falls back automatically:
    CUDA -> AVX-512 -> AVX2 -> AVX -> SSE4.2 -> NEON -> scalar."""

    def __init__(self, dim=384, capacity=1_000_000, metric=COSINE,
                 lsh_num_tables=8, lsh_hash_bits=12, lsh_probes=4,
                 rerank_k=64, force_backend=-1):
        cfg = _Config(dim=dim, capacity=capacity, metric=metric,
                      lsh_num_tables=lsh_num_tables, lsh_hash_bits=lsh_hash_bits,
                      lsh_probes=lsh_probes, rerank_k=rerank_k,
                      omp_threads=0, force_backend=force_backend)
        self._dim = dim
        self._e = ctypes.c_void_p()
        rc = _LIB.keystone_engine_create(ctypes.byref(cfg), ctypes.byref(self._e))
        if rc != 0:
            raise RuntimeError(f"keystone_engine_create failed: {rc}")

    @property
    def backend(self) -> str:
        """e.g. 'avx2', 'scalar', 'cuda'. Reflects CURRENT backend —
        will change if CUDA died and we fell back to CPU."""
        return _LIB.keystone_backend_name(
            _LIB.keystone_engine_get_backend(self._e)).decode()

    def upsert_batch(self, ids, vectors) -> None:
        """Upsert vectors. `vectors`: (n, dim) float32. Source-agnostic:
        VPU, CPU, GPU, hash_bow — all identical to this call."""
        ids = np.ascontiguousarray(ids, dtype=np.uint64)
        vecs = np.ascontiguousarray(vectors, dtype=np.float32)
        if vecs.ndim != 2 or vecs.shape[1] != self._dim:
            raise ValueError(f"expected (n, {self._dim}) float32")
        rc = _LIB.keystone_upsert_batch(self._e, ids.ctypes.data_as(
            ctypes.POINTER(ctypes.c_uint64)),
            vecs.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            vecs.shape[0])
        if rc != 0:
            raise RuntimeError(f"upsert_batch failed: {rc}")

    def search_batch(self, queries, k=10):
        """queries: (nq, dim) float32 -> list of (k,) id arrays and (k,) dist arrays."""
        qs = np.ascontiguousarray(queries, dtype=np.float32)
        nq = qs.shape[0]
        out = (_Result * (nq * k))()
        rc = _LIB.keystone_search_batch(self._e,
            qs.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            nq, k, out)
        if rc != 0:
            raise RuntimeError(f"search_batch failed: {rc}")
        res = np.ctypeslib.as_array(out).reshape(nq, k)
        return res["id"].copy(), res["distance"].copy()

    def search(self, query, k=10):
        ids, dists = self.search_batch(query[None, :], k)
        return ids[0], dists[0]

    def close(self):
        if self._e:
            _LIB.keystone_engine_destroy(self._e)
            self._e = ctypes.c_void_p()
```

**Removed from v1 bindings:** `vpu_connect()`, `vpu_socket_path` parameter, any framing helpers, any embedding-generation functions. **Embedding source usage is now just:**

```python
# myriad_embedding_server.py (or any other producer) — illustrative
engine = KeystoneVectorEngine(dim=384)
vecs = my_embedding_source.encode(texts)   # VPU, CPU, hash_bow — doesn't matter
engine.upsert_batch(ids, vecs)             # the ONLY integration point
```

---

## Part 4: Graceful Degradation Matrix

| Hardware configuration | Compiled backends | Runtime detection result | Backend selected | If selected backend fails mid-session | Net behavior |
|---|---|---|---|---|---|
| Modern x86 server, RTX GPU, CUDA toolkit | scalar, sse42, avx, avx2, avx512, cuda | all flags + CUDA init OK | **CUDA** | GPU lost/OOM → teardown, re-dispatch to **AVX-512**, current batch re-run on CPU, no error surfaced | Full speed → still fast, zero downtime |
| Modern x86 server, **no GPU** (or no driver / no toolkit) | scalar, sse42, avx, avx2, avx512 | all CPU flags; `dlopen` fails or skipped | **AVX-512** | n/a (CPU SIMD doesn't "fail") | Fast, CPU-only |
| Current dev machine (AVX only) | scalar, sse42, avx | SSE4.2 + AVX flags | **AVX** (float-only YMM path) | n/a | Fast |
| Typical laptop (AVX2, no GPU) | scalar, sse42, avx, avx2 | SSE4.2 + AVX + AVX2 | **AVX2** | n/a | Fast |
| Ancient x86-64 server (SSE2 only) | scalar, sse42, avx, avx2, avx512 (built elsewhere) | **only SSE4.2** flag set (or none) | **SSE4.2** or **scalar** | n/a | Correct, slower — never crashes on EVEX/VEX faults because runtime detection skipped them |
| VM with AVX masked off by hypervisor | any set compiled | cpuid shows no AVX, `_xgetbv` confirms OS doesn't save YMM | **SSE4.2** | n/a | Correct — the OSXSAVE check is what prevents illegal-instruction crashes here |
| Raspberry Pi 4 / any ARM64 | scalar, neon | NEON flag | **NEON** | n/a | Correct, decent speed |
| ARM board without NEON (or 32-bit fallback) | scalar only | no NEON flag | **Scalar** | n/a | Correct, slow — works |
| Raspberry Pi Zero / any random Linux box, only `cc` available | **scalar only** (build.sh compiles nothing else) | irrelevant | **Scalar** | n/a | Builds and runs everywhere — this is the floor, and the floor is solid |
| Binary built on Pi, run on AVX-512 box | scalar only | irrelevant (no SIMD compiled) | **Scalar** | n/a | Correct, suboptimal — acceptable trade-off of cross-deployed binaries |
| `force_backend=SCALAR` on AVX-512 machine (testing) | all | all flags | **Scalar** | n/a | Bit-exact reference for SIMD correctness diffs |

**Invariants the matrix demonstrates:**
1. Every row ends in "correct results" — speed varies, correctness never does.
2. No row can crash from missing hardware: compile-time guards prevent absent code, runtime detection prevents illegal instructions, soft CUDA loading prevents link/init failures, and the scalar floor is unconditionally compiled.
3. The engine's only input contract is `upsert_batch(float32[n][dim])` — the VPU, CPU embedders, and hash_bow are interchangeable producers behind an identical call.

If you want, next step I can write out the actual kernel translation units (`kernels_scalar.c` / `kernels_avx.c` / etc.) with the shared ABI, or the CUDA soft-load shim in full.