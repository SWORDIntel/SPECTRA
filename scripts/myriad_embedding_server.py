#!/usr/bin/env python3
"""Myriad X VPU embedding server — runs in the Python 3.10 venv with OpenVINO 2022.3.2.

Splits the BERT model: the embedding lookup (Gather op) runs on CPU
because the VPU's FP16 conversion corrupts integer token IDs. Only the
transformer encoder layers run on the VPU.

Pipeline per text:
  1. Tokenize (CPU)
  2. Embedding lookup — word + position + token_type embeddings (CPU)
  3. Transformer encoder layers (VPU)
  4. Mean pooling with attention mask (CPU)
  5. L2 normalize (CPU)

Protocol (newline-delimited JSON over Unix socket):
  Request:  {"texts": ["text1", "text2", ...]}
  Response: {"vectors": [[0.1, 0.2, ...], ...], "dim": 384}
  Error:    {"error": "message"}

Usage:
  LD_LIBRARY_PATH=/opt/intel/openvino_2022.3.2/runtime/lib/intel64:... \
  PYTHONPATH=/opt/intel/openvino_2022.3.2/python/python3.10 \
  /fast/home/john/SPECTRA/.myriad-venv/bin/python scripts/myriad_embedding_server.py \
    --socket /tmp/myriad_embed.sock \
    --encoder-model /fast/home/john/SPECTRA/models/minilm-encoder-only.xml \
    --device MYRIAD
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
import numpy as np

def main():
    parser = argparse.ArgumentParser(description="Myriad X VPU embedding server")
    parser.add_argument("--socket", default="/tmp/myriad_embed.sock",
                       help="Unix socket path")
    parser.add_argument("--encoder-model",
                       default="/fast/home/john/SPECTRA/models/minilm-encoder-only.xml",
                       help="OpenVINO IR for encoder-only model (static shapes)")
    parser.add_argument("--device", default="MYRIAD",
                       help="OpenVINO device (MYRIAD, MYRIAD.1.1.1-ma2480, CPU)")
    parser.add_argument("--max-seq-length", type=int, default=128,
                       help="Max sequence length (must match model)")
    parser.add_argument("--timeout", type=float, default=300,
                       help="Socket timeout for clients")
    args = parser.parse_args()

    # Load PyTorch + transformers for CPU-side embedding lookup
    import torch
    from transformers import AutoModel, AutoTokenizer

    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    print(f"Loading tokenizer + embeddings from {model_name}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    pt_model = AutoModel.from_pretrained(model_name)
    pt_model.eval()

    # Load OpenVINO for VPU-side transformer encoder
    from openvino.runtime import Core
    core = Core()

    # Enable model caching — first compile takes ~10 min for MYRIAD, but
    # the compiled graph is persisted to cache_dir and reloaded in seconds
    # on subsequent starts.
    cache_dir = os.environ.get("SPECTRA_VPU_CACHE_DIR", "/fast/home/john/SPECTRA/data/vpu_cache")
    os.makedirs(cache_dir, exist_ok=True)
    core.set_property({"CACHE_DIR": cache_dir})
    print(f"OpenVINO cache dir: {cache_dir}", flush=True)

    print(f"Loading encoder model: {args.encoder_model}", flush=True)
    ov_model = core.read_model(args.encoder_model)

    print(f"Compiling for {args.device} (first time ~10 min, cached ~5s)...", flush=True)
    t0 = time.time()
    compiled = core.compile_model(ov_model, args.device)
    print(f"Compiled in {time.time()-t0:.1f}s", flush=True)

    # Create multiple infer requests for parallel VPU execution.
    # The Myriad X can pipeline multiple requests on the hardware.
    NUM_INFER_REQS = int(os.environ.get("SPECTRA_VPU_PARALLEL", "4"))
    infer_requests = [compiled.create_infer_request() for _ in range(NUM_INFER_REQS)]
    print(f"VPU encoder ready ({NUM_INFER_REQS} parallel infer requests)", flush=True)

    import concurrent.futures

    # Each infer request has its own lock so threads don't collide on the
    # same request object, but the VPU hardware pipelines them internally.
    req_locks = [threading.Lock() for _ in range(NUM_INFER_REQS)]
    req_rr = [0]  # round-robin index

    def _cpu_preprocess(text):
        """Tokenize + CPU embedding lookup → (hidden_states, attention_mask)."""
        if not text:
            return None
        encoded = tokenizer(
            [text],
            padding="max_length",
            truncation=True,
            max_length=args.max_seq_length,
            return_tensors="pt",
        )
        with torch.no_grad():
            emb = pt_model.embeddings(
                input_ids=encoded["input_ids"],
                token_type_ids=torch.zeros_like(encoded["input_ids"]),
            )
            ext_mask = pt_model.get_extended_attention_mask(
                encoded["attention_mask"], encoded["input_ids"].shape
            )
        return (
            emb.numpy().astype(np.float32),
            ext_mask.numpy().astype(np.float32),
            encoded["attention_mask"][0].numpy().astype(np.float32),
        )

    def _vpu_infer(preprocessed):
        """Run VPU encoder on a single preprocessed sample."""
        emb_np, ext_mask_np, attn_mask = preprocessed
        inputs = {
            "hidden_states": emb_np,
            "attention_mask": ext_mask_np,
        }
        # Round-robin across infer requests so the VPU can pipeline
        idx = req_rr[0]
        req_rr[0] = (idx + 1) % NUM_INFER_REQS
        with req_locks[idx]:
            infer_requests[idx].infer(inputs)
            hidden_states = infer_requests[idx].get_output_tensor(0).data
        return hidden_states, attn_mask

    def _postprocess(vpu_result):
        """Mean pooling + collect."""
        hidden_states, mask = vpu_result
        masked_hidden = hidden_states[0] * mask[:, np.newaxis]  # (seq, dim)
        sum_hidden = masked_hidden.sum(axis=0)  # (dim,)
        sum_mask = mask.sum()
        if sum_mask > 0:
            return sum_hidden / sum_mask
        return sum_hidden

    def embed_texts(texts):
        """Tokenize, CPU embed, VPU encode, mean-pool, L2-normalize.

        Full parallel pipeline: CPU preprocessing and VPU inference run
        concurrently in thread pools.  Multiple infer requests allow the
        VPU hardware to pipeline inference while CPU works on the next
        sample.
        """
        n = len(texts)
        all_vectors = [None] * n

        # Pipeline: CPU preprocess in one pool, VPU infer + postprocess in
        # another.  As soon as CPU finishes a sample, a VPU worker picks
        # it up.  With NUM_INFER_REQS parallel requests the VPU can keep
        # multiple inferences in flight.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as cpu_pool, \
             concurrent.futures.ThreadPoolExecutor(max_workers=NUM_INFER_REQS) as vpu_pool:

            # Stage 1: CPU preprocess all texts
            preproc_futures = {
                cpu_pool.submit(_cpu_preprocess, text): i
                for i, text in enumerate(texts)
            }

            # Stage 2: As CPU results complete, submit VPU inference
            vpu_futures = {}
            for future in concurrent.futures.as_completed(preproc_futures):
                idx = preproc_futures[future]
                preprocessed = future.result()
                if preprocessed is None:
                    all_vectors[idx] = np.zeros(384, dtype=np.float32)
                    continue
                vpu_futures[vpu_pool.submit(_vpu_infer, preprocessed)] = idx

            # Stage 3: Collect VPU results and postprocess
            for future in concurrent.futures.as_completed(vpu_futures):
                idx = vpu_futures[future]
                all_vectors[idx] = _postprocess(future.result())

        vectors = np.array(all_vectors, dtype=np.float32)

        # L2 normalize
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        vectors = vectors / norms

        return vectors

    # Set up Unix socket server
    sock_path = args.socket
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(8)
    server.settimeout(None)
    print(f"Listening on {sock_path}", flush=True)

    def handle_client(conn):
        conn.settimeout(args.timeout)
        buf = b""
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        request = json.loads(line)
                        texts = request.get("texts", [])
                        if not texts:
                            response = {"vectors": [], "dim": 384}
                        else:
                            vectors = embed_texts(texts)
                            response = {
                                "vectors": vectors.tolist(),
                                "dim": vectors.shape[1],
                            }
                        conn.sendall((json.dumps(response) + "\n").encode())
                    except Exception as e:
                        error_msg = {"error": str(e)}
                        conn.sendall((json.dumps(error_msg) + "\n").encode())
        except socket.timeout:
            pass
        except Exception as e:
            print(f"Client error: {e}", flush=True)
        finally:
            conn.close()

    while True:
        try:
            conn, _ = server.accept()
            thread = threading.Thread(target=handle_client, args=(conn,), daemon=True)
            thread.start()
        except KeyboardInterrupt:
            print("Shutting down...", flush=True)
            break
        except Exception as e:
            print(f"Accept error: {e}", flush=True)

    server.close()
    if os.path.exists(sock_path):
        os.unlink(sock_path)

if __name__ == "__main__":
    main()
