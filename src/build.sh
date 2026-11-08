#!/bin/bash
# Builds ../hybrid_rag_submission.zip, ready to upload to Codabench.
#
# Bundles MiniLM and both Transformers and ONNX layout models, so
# document processing runs without network access in the evaluation container.
# Libraries must match requirements-participant.txt. No dependencies are shipped.
# REUSE_MODELS=1 reuses existing weights without downloading; INCLUDE_KG=1
# optionally adds the experimental KG. Default inference is hybrid (KG off).
set -euo pipefail
cd "$(dirname "$0")"

include_kg="${INCLUDE_KG:-0}"
reuse_models="${REUSE_MODELS:-0}"
case "$include_kg:$reuse_models" in
    0:0|0:1|1:0|1:1) ;;
    *) echo "INCLUDE_KG and REUSE_MODELS must be 0 or 1" >&2; exit 1 ;;
esac
files=(main.py kg_retrieval.py retrieval_utils.py prompts.py evidence.py lexical.py embed_model)
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

if [[ "$reuse_models" == 0 || ! -f embed_model/modules.json ]]; then
    rm -rf embed_model
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python3 -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2').save('embed_model')
"
fi

# Keep both layout formats, as in the original package. Formula assets stay out.
files+=(docling_models/docling-project--docling-layout-heron docling_models/docling-project--docling-layout-heron-onnx)

submission_zip="../hybrid_rag_submission.zip"
staging_zip="../hybrid_rag_submission.build.zip"
trap 'rm -f "$staging_zip"' EXIT
rm -f "$staging_zip"
zip -q -r "$staging_zip" "${files[@]}" -x '__pycache__/*' '*.pyc' '*/.cache/*'

# Validate the candidate before replacing the previous working submission.
python3 - "$staging_zip" <<'VALIDATE'
import sys
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
    required = {'main.py', 'evidence.py', 'lexical.py', 'prompts.py',
                'docling_models/docling-project--docling-layout-heron/model.safetensors',
                'docling_models/docling-project--docling-layout-heron-onnx/model.onnx'}
    if not required.issubset(bundle.namelist()):
        raise SystemExit('ZIP missing required inference assets')
print(f"[build] validated candidate ({size:,} bytes)")
VALIDATE
mv -f "$staging_zip" "$submission_zip"
echo "-> $submission_zip"
