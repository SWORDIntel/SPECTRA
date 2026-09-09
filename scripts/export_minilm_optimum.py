#!/usr/bin/env python3
"""Export all-MiniLM-L6-v2 to ONNX using optimum, then convert to OpenVINO IR."""
import os
import sys
import numpy as np

def export_with_optimum():
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer

    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    output_dir = "/fast/home/john/SPECTRA/models/minilm-onnx"
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading {model_name} with optimum...")
    model = ORTModelForFeatureExtraction.from_pretrained(model_name, export=True)
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    print(f"Saving ONNX to {output_dir}...")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    onnx_path = os.path.join(output_dir, "model.onnx")
    print(f"ONNX model: {onnx_path}")

    # Convert to OpenVINO IR
    from openvino.runtime import Core, serialize
    core = Core()
    model_ov = core.read_model(onnx_path)

    ir_prefix = "/fast/home/john/SPECTRA/models/minilm-l6-v2"
    serialize(model_ov, f"{ir_prefix}.xml", f"{ir_prefix}.bin")
    print(f"OpenVINO IR: {ir_prefix}.xml + {ir_prefix}.bin")

    # Test on MYRIAD
    print("Testing on MYRIAD...")
    try:
        compiled = core.compile_model(model_ov, "MYRIAD")
        print("MYRIAD compilation OK!")

        infer = compiled.create_infer_request()
        inputs = tokenizer(["Hello world test"], padding=True, truncation=True,
                          max_length=128, return_tensors="np")
        ov_inputs = {
            "input_ids": inputs["input_ids"].astype(np.int64),
            "attention_mask": inputs["attention_mask"].astype(np.int64),
        }
        if "token_type_ids" in inputs:
            ov_inputs["token_type_ids"] = inputs["token_type_ids"].astype(np.int64)

        infer.infer(ov_inputs)
        result = infer.get_output_tensor(0).data
        print(f"MYRIAD output shape: {result.shape}")
        print(f"MYRIAD output sample: {result[0, 0, :5]}")
    except Exception as e:
        print(f"MYRIAD test failed: {e}")

if __name__ == "__main__":
    export_with_optimum()
