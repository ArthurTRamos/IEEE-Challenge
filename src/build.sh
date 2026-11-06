#!/bin/bash
# Builds ../hybrid_rag_submission.zip, ready to upload to Codabench.
#
# Docling and sentence-transformers (the libraries) are already in the
# challenge's evaluation environment, but two model weight files they need —
# Docling's "layout" model, and the "all-MiniLM-L6-v2" embedding model — are
# not pre-downloaded there, and that environment has no internet access to
# fetch them on its own. This script downloads both once, here, where there
# IS internet, and bundles them into the submission zip so the evaluation
# container never needs to reach out for either.
#
# Needs `docling-tools` (from the `docling` package) and `sentence-transformers`
# on PATH/importable, matching the versions pinned in the challenge's
# docker/requirements-participant.txt, plus `zip`. If you don't have them
# installed locally: pip install docling sentence-transformers (matching
# those pinned versions).
set -euo pipefail
cd "$(dirname "$0")"

include_kg="${INCLUDE_KG:-1}"
reuse_models="${REUSE_MODELS:-0}"
case "$include_kg:$reuse_models" in
    0:0|0:1|1:0|1:1) ;;
    *) echo "INCLUDE_KG and REUSE_MODELS must be 0 or 1" >&2; exit 1 ;;
esac
files=(main.py kg_retrieval.py docling_models embed_model)
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

if [[ "$reuse_models" == 0 || ! -d docling_models ]]; then
    rm -rf docling_models
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 docling-tools models download layout -o ./docling_models
fi

if [[ "$reuse_models" == 0 || ! -f embed_model/modules.json ]]; then
    rm -rf embed_model
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python3 -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2').save('embed_model')
"
fi

submission_zip="../hybrid_rag_submission.zip"
rm -f "$submission_zip"
zip -q -r "$submission_zip" "${files[@]}" -x '__pycache__/*' '*.pyc' '*/.cache/*'

# Use decimal GB so the archive also fits the stricter interpretation of 1 GB.
python3 - "$submission_zip" <<'PY'
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
print(f"-> {archive} ({size:,} bytes)")
PY
