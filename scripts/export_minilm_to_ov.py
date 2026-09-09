#!/usr/bin/env python3
"""Export all-MiniLM-L6-v2 SentenceTransformer to OpenVINO IR format for Myriad X.

The model has two parts:
1. Transformer encoder (the heavy part — goes on Myriad X)
2. Pooling layer (mean pooling — trivial, done in NumPy)

We export just the transformer encoder to OpenVINO IR, then do pooling in Python.
"""
import sys
import os
import numpy as np

def export_model():
    from sentence_transformers import SentenceTransformer
    from transformers import AutoModel, AutoTokenizer
    import torch

    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    print(f"Loading {model_name}...")

    # Load the transformer model directly
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()

    # Create dummy input for tracing
    dummy_input = tokenizer(
        ["Hello world, this is a test sentence."],
        padding=True,
        truncation=True,
        max_length=128,
        return_tensors="pt"
    )

    # Export to ONNX first
    onnx_path = "/fast/home/john/SPECTRA/models/minilm-l6-v2.onnx"
    os.makedirs(os.path.dirname(onnx_path), exist_ok=True)

    print(f"Exporting to ONNX: {onnx_path}")
    torch.onnx.export(
        model,
        (dummy_input["input_ids"], dummy_input["attention_mask"], dummy_input.get("token_type_ids", torch.zeros_like(dummy_input["input_ids"]))),
        onnx_path,
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "token_type_ids": {0: "batch", 1: "sequence"},
            "last_hidden_state": {0: "batch", 1: "sequence"},
        },
        opset_version=11,
    )
    print(f"ONNX exported: {onnx_path}")

    # Now convert ONNX to OpenVINO IR using the new OpenVINO API
    from openvino.runtime import Core, serialize
    core = Core()
    model_ov = core.read_model(onnx_path)

    # Serialize to IR
    ir_prefix = "/fast/home/john/SPECTRA/models/minilm-l6-v2"
    serialize(model_ov, f"{ir_prefix}.xml", f"{ir_prefix}.bin")
    print(f"OpenVINO IR saved: {ir_prefix}.xml + {ir_prefix}.bin")

    # Verify by loading on MYRIAD
    print("Verifying on MYRIAD...")
    # Compile for MYRIAD
    try:
        compiled = core.compile_model(model_ov, "MYRIAD")
        print("MYRIAD compilation successful!")

        # Run inference
        infer = compiled.create_infer_request()
        input_ids = dummy_input["input_ids"].numpy().astype(np.int64)
        attention_mask = dummy_input["attention_mask"].numpy().astype(np.int64)
        token_type_ids = dummy_input.get("token_type_ids", torch.zeros_like(dummy_input["input_ids"])).numpy().astype(np.int64)

        inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        }
        infer.infer(inputs)
        result = infer.get_output_tensor(0).data
        print(f"MYRIAD output shape: {result.shape}")
        print(f"MYRIAD output sample: {result[0, 0, :5]}")
    except Exception as e:
        print(f"MYRIAD compilation failed: {e}")
        print("Trying CPU compilation...")
        compiled = core.compile_model(model_ov, "CPU")
        infer = compiled.create_infer_request()
        input_ids = dummy_input["input_ids"].numpy().astype(np.int64)
        attention_mask = dummy_input["attention_mask"].numpy().astype(np.int64)
        token_type_ids = dummy_input.get("token_type_ids", torch.zeros_like(dummy_input["input_ids"])).numpy().astype(np.int64)
        inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        }
        infer.infer(inputs)
        result = infer.get_output_tensor(0).data
        print(f"CPU output shape: {result.shape}")

if __name__ == "__main__":
    export_model()
