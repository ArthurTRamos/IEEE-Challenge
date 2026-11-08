#!/usr/bin/env python3
"""Prepare and verify the pinned CodeFormulaV2 assets for offline Docling."""
import argparse
import hashlib
import json
from pathlib import Path

REPO = 'docling-project/CodeFormulaV2'
REVISION = 'ecedbe111d15c2dc60bfd4a823cbe80127b58af4'
WEIGHT_SHA256 = '4b04e77af34c4e682a7ab1617628340d658f3c3dcd12456dd2a7fff805cf79d2'
REQUIRED = ('model.safetensors', 'config.json', 'generation_config.json', 'preprocessor_config.json',
            'processor_config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json')


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'src/docling_models/docling-project--CodeFormulaV2')
    args = parser.parse_args()
    if not all((args.output/name).is_file() for name in REQUIRED):
        if args.verify_only:
            raise SystemExit('Formula assets missing; run tools/prepare_formula_model.py with network access')
        from huggingface_hub import snapshot_download
        snapshot_download(REPO, revision=REVISION, local_dir=args.output,
                          allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt', '*.jinja', 'LICENSE*', 'README.md'])
    if sha256(args.output/'model.safetensors') != WEIGHT_SHA256:
        raise SystemExit('CodeFormulaV2 weight checksum mismatch')
    paths = sorted(p for p in args.output.iterdir() if p.is_file() and p.name != 'artifact.json')
    manifest = {'repo_id': REPO, 'revision': REVISION, 'license': 'cdla-permissive-2.0',
                'files': {p.name: {'bytes': p.stat().st_size, 'sha256': sha256(p)} for p in paths}}
    (args.output/'artifact.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'[build] verified CodeFormulaV2: {sum(p.stat().st_size for p in paths):,} bytes; revision {REVISION}')


if __name__ == '__main__':
    main()
