#!/usr/bin/env python3
"""Step 2: Convert ONNX to OpenVINO IR and test on MYRIAD."""
import os
import sys
import numpy as np

def convert_and_test():
    from openvino.runtime import Core, serialize

    core = Core()
    onnx_path = "/fast/home/john/SPECTRA/models/minilm-l6-v2.onnx"
    print(f"Loading ONNX: {onnx_path}", flush=True)
    model = core.read_model(onnx_path)
    print(f"Inputs: {[i.any_name for i in model.inputs]}", flush=True)
    print(f"Outputs: {[o.any_name for o in model.outputs]}", flush=True)

    ir_prefix = "/fast/home/john/SPECTRA/models/minilm-l6-v2"
    serialize(model, f"{ir_prefix}.xml", f"{ir_prefix}.bin")
    print(f"OpenVINO IR: {ir_prefix}.xml + {ir_prefix}.bin", flush=True)

    print("Compiling for MYRIAD...", flush=True)
    try:
        compiled = core.compile_model(model, "MYRIAD")
        print("MYRIAD compilation OK!", flush=True)

        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
        encoded = tokenizer(["Hello world test"], padding="max_length", truncation=True,
                          max_length=128, return_tensors="np")

        infer = compiled.create_infer_request()
        inputs = {}
        for idx in compiled.inputs:
            name = idx.any_name
            if "input_ids" in name:
                inputs[name] = encoded["input_ids"].astype(np.int64)
            elif "attention_mask" in name:
                inputs[name] = encoded["attention_mask"].astype(np.int64)
        print(f"Inputs: {list(inputs.keys())}", flush=True)
        infer.infer(inputs)
        result = infer.get_output_tensor(0).data
        print(f"MYRIAD output shape: {result.shape}", flush=True)
        print(f"MYRIAD output sample: {result[0, 0, :5]}", flush=True)
    except Exception as e:
        print(f"MYRIAD test failed: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    convert_and_test()
