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

rm -rf docling_models
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 docling-tools models download layout -o ./docling_models

rm -rf embed_model
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python3 -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2').save('embed_model')
"

submission_zip="../hybrid_rag_submission.zip"
rm -f "$submission_zip"
zip -q -r "$submission_zip" main.py docling_models embed_model -x '__pycache__/*' '*.pyc'

# Use decimal GB so the archive also fits the stricter interpretation of 1 GB.
python3 - "$submission_zip" <<'PY'
import sys
from pathlib import Path

archive = Path(sys.argv[1])
size = archive.stat().st_size
if size > 1_000_000_000:
    raise SystemExit(f"Submission exceeds 1 GB: {size:,} bytes ({archive})")
print(f"-> {archive} ({size:,} bytes)")
PY
