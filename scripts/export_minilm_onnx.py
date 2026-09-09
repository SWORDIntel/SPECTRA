#!/usr/bin/env python3
"""Step 1: Export all-MiniLM-L6-v2 to ONNX only (no OpenVINO)."""
import os
import sys
import numpy as np
import torch
import torch.nn as nn

class BertWrapper(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask):
        out = self.model(input_ids=input_ids, attention_mask=attention_mask)
        return out.last_hidden_state

def export():
    from transformers import AutoModel, AutoTokenizer

    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    print(f"Loading {model_name}...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()
    wrapper = BertWrapper(model)
    wrapper.eval()

    encoded = tokenizer("Hello world test sentence", padding="max_length",
                       truncation=True, max_length=128, return_tensors="pt")

    onnx_path = "/fast/home/john/SPECTRA/models/minilm-l6-v2.onnx"
    os.makedirs(os.path.dirname(onnx_path), exist_ok=True)

    print(f"Exporting to ONNX (opset 14): {onnx_path}", flush=True)
    torch.onnx.export(
        wrapper,
        (encoded["input_ids"], encoded["attention_mask"]),
        onnx_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "last_hidden_state": {0: "batch", 1: "sequence"},
        },
        opset_version=14,
    )
    print(f"ONNX exported: {onnx_path}", flush=True)

    # Verify with onnxruntime
    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_path)
    inputs = {
        "input_ids": encoded["input_ids"].numpy().astype(np.int64),
        "attention_mask": encoded["attention_mask"].numpy().astype(np.int64),
    }
    output = sess.run(None, inputs)[0]
    print(f"ORT output shape: {output.shape}", flush=True)
    print(f"ORT output sample: {output[0, 0, :5]}", flush=True)

if __name__ == "__main__":
    export()
