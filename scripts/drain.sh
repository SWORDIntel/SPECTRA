#!/bin/bash
# KEYSTONE .so has relative RPATH (fortran/) — must run from its directory
cd /fast/home/john/SPECTRA/KEYSTONE
export KEYSTONE_LIB_PATH="/fast/home/john/SPECTRA/KEYSTONE/libkeystone.so"
export PYTHONPATH="/fast/home/john/SPECTRA-PII:${PYTHONPATH}"
exec python3 -m tgarchive index drain \
  --db /fast/home/john/SPECTRA/data/spectra.db \
  --batch-size 50 \
  --max-batches 100 \
  --flush-every-batches 10 \
  --flush-interval-seconds 120
