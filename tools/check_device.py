#!/usr/bin/env python3
"""Report CUDA visibility; optionally execute a tiny tensor operation."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.runtime import device_report, resolve_device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-cuda", action="store_true")
    args = parser.parse_args()
    report = device_report()
    if args.test_cuda:
        import torch
        device = resolve_device("cuda")
        value = torch.ones((16, 16), device=device)
        result = value @ value
        torch.cuda.synchronize()
        report["tensor_test"] = {"device": str(result.device), "result": float(result[0, 0])}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
