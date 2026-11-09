#!/bin/bash
# Builds ../hybrid_rag_submission.zip, ready to upload to Codabench.
#
# Bundles the selected embedding and both Transformers and ONNX layout models, so
# document processing runs without network access in the evaluation container.
# Libraries must match requirements-participant.txt. No dependencies are shipped.
# REUSE_MODELS=1 reuses existing weights without downloading; INCLUDE_KG=1
# optionally adds the experimental KG. Default inference is hybrid (KG off).
# EMBED_MODEL_ID defaults to BAAI/bge-small-en-v1.5, with 512-token inputs.
set -euo pipefail
cd "$(dirname "$0")"

include_kg="${INCLUDE_KG:-0}"
reuse_models="${REUSE_MODELS:-0}"
embedding_model_id="${EMBED_MODEL_ID:-BAAI/bge-small-en-v1.5}"
case "$include_kg:$reuse_models" in
    0:0|0:1|1:0|1:1) ;;
    *) echo "INCLUDE_KG and REUSE_MODELS must be 0 or 1" >&2; exit 1 ;;
esac
files=(main.py settings.py pipeline.json runtime.py documents.py indexing.py retrieval.py context.py generation.py
       kg_retrieval.py retrieval_utils.py prompts.py evidence.py lexical.py embedding.py embed_model)
python3 - "$include_kg" <<'CONFIG'
import json
import sys
from pathlib import Path
from settings import PipelineConfig
values = json.loads(Path('pipeline.json').read_text())
config = PipelineConfig(**values)
if (config.uses('kg_mentions') or config.uses('kg_graph')) and sys.argv[1] != '1':
    raise SystemExit('pipeline.json requests KG: build with INCLUDE_KG=1')
if config.formula_enrichment:
    raise SystemExit('The current build excludes formula weights: set formula_enrichment=false')
if values.get('embed_model', 'embed_model') != 'embed_model' or values.get('kg', 'kg') != 'kg':
    raise SystemExit('The submission build uses relative embed_model/ and kg/ paths in pipeline.json')
if config.stopwords_file is not None:
    raise SystemExit('The current build does not bundle a custom stopwords_file; use the default list or add that asset explicitly')
CONFIG
if [[ "$include_kg" == 1 ]]; then
    if [[ ! -f kg/manifest.json ]]; then
        echo "Prepare the KG first: python tools/prepare_kg.py (from the repository root)" >&2
        exit 1
    fi
    python3 - <<'PY'
from kg_retrieval import load_artifact
import hashlib
from pathlib import Path
manifest, _, _ = load_artifact('kg')
for name, expected in manifest.get('inputs', {}).items():
    original = Path('../data') / name
    if original.is_file() and hashlib.sha256(original.read_bytes()).hexdigest() != expected:
        raise SystemExit('KG inputs changed; run python tools/prepare_kg.py from the repository root')
aliases = Path('../tools/kg_aliases.json')
if aliases.is_file() and hashlib.sha256(aliases.read_bytes()).hexdigest() != manifest.get('curated_aliases_sha256'):
    raise SystemExit('KG aliases changed; run python tools/prepare_kg.py from the repository root')
print(f"[build] validated KG: {manifest['counts']}")
PY
    files+=(kg/manifest.json kg/nodes.jsonl kg/edges.jsonl kg/audit.json)
fi

if [[ "$reuse_models" == 0 || ! -f docling_models/docling-project--docling-layout-heron/model.safetensors || ! -f docling_models/docling-project--docling-layout-heron-onnx/model.onnx ]]; then
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 docling-tools models download layout -o ./docling_models
fi

if [[ "$reuse_models" == 0 ]] || ! python3 ../tools/prepare_embedding_model.py \
    --model-id "$embedding_model_id" --output embed_model --verify-only; then
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python3 ../tools/prepare_embedding_model.py \
        --model-id "$embedding_model_id" --output embed_model --replace
fi

# Keep both layout formats, as in the original package. Formula assets stay out.
files+=(docling_models/docling-project--docling-layout-heron docling_models/docling-project--docling-layout-heron-onnx)

submission_zip="../hybrid_rag_submission.zip"
staging_zip="../hybrid_rag_submission.build.zip"
trap 'rm -f "$staging_zip"' EXIT
rm -f "$staging_zip"
zip -q -r "$staging_zip" "${files[@]}" -x '__pycache__/*' '*.pyc' '*/.cache/*'

# Validate the candidate before replacing the previous working submission.
python3 - "$staging_zip" "$embedding_model_id" <<'VALIDATE'
import sys
import json
from pathlib import Path
from zipfile import ZipFile
archive = Path(sys.argv[1])
size = archive.stat().st_size
if size > 1_000_000_000:
    raise SystemExit(f"Submission exceeds 1 GB: {size:,} bytes ({archive})")
with ZipFile(archive) as bundle:
    bad = bundle.testzip()
    if bad:
        raise SystemExit(f"ZIP checksum failed: {bad}")
    required = {'main.py', 'settings.py', 'pipeline.json', 'runtime.py', 'documents.py',
                'indexing.py', 'retrieval.py', 'context.py', 'generation.py',
                'kg_retrieval.py', 'retrieval_utils.py', 'evidence.py', 'lexical.py', 'prompts.py', 'embedding.py',
                'embed_model/embedding-manifest.json', 'embed_model/modules.json',
                'embed_model/model.safetensors',
                'docling_models/docling-project--docling-layout-heron/model.safetensors',
                'docling_models/docling-project--docling-layout-heron-onnx/model.onnx'}
    if not required.issubset(bundle.namelist()):
        raise SystemExit('ZIP missing required inference assets')
    manifest = json.loads(bundle.read('embed_model/embedding-manifest.json'))
    if manifest['model_id'] != sys.argv[2]:
        raise SystemExit('ZIP contains an unexpected embedding model')
    if not all('embed_model/' + name in bundle.namelist() for name in manifest['files']):
        raise SystemExit('ZIP missing an embedding asset declared in the manifest')
print(f"[build] validated candidate ({size:,} bytes)")
VALIDATE
mv -f "$staging_zip" "$submission_zip"
echo "-> $submission_zip"
