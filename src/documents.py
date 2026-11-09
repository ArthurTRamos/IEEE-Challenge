"""Offline Docling conversion; chunking and metadata live in evidence.py."""

from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

def create_converter(device=None, num_threads=None, formula_enrichment=False) -> DocumentConverter:
    pipeline_options = PdfPipelineOptions(
        artifacts_path=str(Path(__file__).parent / "docling_models"),
        do_ocr=False,              # the corpus is born-digital text, not scans
        do_table_structure=False,  # TableFormer is a separate, untested ablation.
        do_formula_enrichment=formula_enrichment,
    )
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.object_detection_engine_options import TransformersObjectDetectionEngineOptions
    pipeline_options.layout_options.engine_options = TransformersObjectDetectionEngineOptions(compile_model=False)
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=device or "auto", num_threads=num_threads or 4,
        cuda_use_flash_attention2=False,
    )
    if formula_enrichment:
        from docling.datamodel.pipeline_options import CodeFormulaVlmOptions
        from docling.datamodel.vlm_engine_options import TransformersVlmEngineOptions
        formula_path = Path(__file__).parent / "docling_models/docling-project--CodeFormulaV2"
        if not (formula_path / "model.safetensors").is_file():
            raise FileNotFoundError("Missing offline formula model; run tools/prepare_formula_model.py")
        pipeline_options.code_formula_options = CodeFormulaVlmOptions.from_preset("codeformulav2")
        pipeline_options.code_formula_options.model_spec.max_new_tokens = 1024
        pipeline_options.code_formula_options.engine_options = TransformersVlmEngineOptions(
            torch_dtype="float32" if device == "cpu" else "bfloat16", compile_model=False,
        )
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
