#!/usr/bin/env python3
"""Export all-MiniLM-L6-v2 to ONNX using legacy torch exporter, then convert to OpenVINO IR."""
import os
import sys
import numpy as np
import torch

def export():
    from transformers import AutoModel, AutoTokenizer

    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    print(f"Loading {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()

    # Dummy input
    encoded = tokenizer("Hello world test sentence", padding="max_length",
                       truncation=True, max_length=128, return_tensors="pt")

    onnx_path = "/fast/home/john/SPECTRA/models/minilm-l6-v2.onnx"
    os.makedirs(os.path.dirname(onnx_path), exist_ok=True)

    print(f"Exporting to ONNX (legacy exporter): {onnx_path}")
    # Use legacy exporter with dynamo=False
    torch.onnx.export(
        model,
        (encoded["input_ids"], encoded["attention_mask"]),
        onnx_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "last_hidden_state": {0: "batch", 1: "sequence"},
        },
        opset_version=11,
        dynamo=False,  # Force legacy exporter
    )
    print(f"ONNX exported: {onnx_path}")

    # Convert to OpenVINO IR
    from openvino.runtime import Core, serialize
    core = Core()
    print("Reading ONNX model...")
    model_ov = core.read_model(onnx_path)
    print(f"Inputs: {[i.any_name for i in model_ov.inputs]}")
    print(f"Outputs: {[o.any_name for o in model_ov.outputs]}")

    ir_prefix = "/fast/home/john/SPECTRA/models/minilm-l6-v2"
    serialize(model_ov, f"{ir_prefix}.xml", f"{ir_prefix}.bin")
    print(f"OpenVINO IR: {ir_prefix}.xml + {ir_prefix}.bin")

    # Test on MYRIAD
    print("Compiling for MYRIAD...")
    try:
        compiled = core.compile_model(model_ov, "MYRIAD")
        print("MYRIAD compilation OK!")

        infer = compiled.create_infer_request()
        inputs = {
            "input_ids": encoded["input_ids"].numpy().astype(np.int64),
            "attention_mask": encoded["attention_mask"].numpy().astype(np.int64),
        }
        infer.infer(inputs)
        result = infer.get_output_tensor(0).data
        print(f"MYRIAD output shape: {result.shape}")
        print(f"MYRIAD output sample: {result[0, 0, :5]}")

        # Compare with PyTorch
        with torch.no_grad():
            pt_output = model(encoded["input_ids"], encoded["attention_mask"])
        print(f"PyTorch output sample: {pt_output.last_hidden_state[0, 0, :5].numpy()}")
        print(f"Max diff: {np.max(np.abs(result - pt_output.last_hidden_state.numpy()))}")
    except Exception as e:
        print(f"MYRIAD test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    export()
