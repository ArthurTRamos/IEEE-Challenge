"""Device selection and small diagnostics; never download or load a model."""


def resolve_device(requested="auto"):
    import torch
    if requested not in ("auto", "cpu", "cuda"):
        raise ValueError("Device must be auto, cpu or cuda")
    if requested == "cpu":
        return "cpu"
    available = torch.cuda.is_available()
    if requested == "cuda" and not available:
        raise RuntimeError("CUDA was requested but is unavailable to this process. Run tools/check_device.py in your terminal, or select cpu/auto.")
    return "cuda" if available else "cpu"


def device_report():
    import os
    import torch
    available = torch.cuda.is_available()
    return {"torch": torch.__version__, "cuda_build": torch.version.cuda,
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "cuda_available": available,
            "gpu": torch.cuda.get_device_name(0) if available else None,
            "vram_gib": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2) if available else None}
