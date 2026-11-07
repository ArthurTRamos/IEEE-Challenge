#!/usr/bin/env python3
"""Baixa PDFs de um corpus público definido por um CSV de metadados.

Uso: pip install requests
     python download_corpus.py --manifest ifmif_dones_30_artigos.csv --outdir corpus_ifmif_dones
"""
import argparse, csv, hashlib, os, re, time
from pathlib import Path
import requests

parser = argparse.ArgumentParser(description='Baixe os PDFs da coleção IFMIF-DONES.')
parser.add_argument('--manifest', default='ifmif_dones_30_artigos.csv')
parser.add_argument('--outdir', default='corpus_ifmif_dones')
parser.add_argument('--sleep', type=float, default=1.2, help='Segundos entre downloads (padrão: 1.2)')
parser.add_argument('--timeout', type=int, default=45)
args = parser.parse_args()

outdir = Path(args.outdir)
pdf_dir = outdir / 'pdfs'
pdf_dir.mkdir(parents=True, exist_ok=True)
with open(args.manifest, encoding='utf-8', newline='') as fp:
    records = list(csv.DictReader(fp))

session = requests.Session()
session.headers.update({'User-Agent': 'IFMIF-DONES-research-corpus/1.0 (academic use; contact site administrator for questions)'})
report=[]
for i, rec in enumerate(records, 1):
    did = rec['id']
    filename = f'{did}.pdf'
    target = pdf_dir / filename
    url = rec['pdf_url'].strip()
    result = dict(id=did, title=rec['title'], source_url=url, local_path=str(target), status='', bytes='', sha256='', error='')
    if not url:
        result['status'] = 'missing_url'
        report.append(result)
        continue
    if target.is_file() and target.stat().st_size > 10:
        head=target.open('rb').read(5)
        if head == b'%PDF-':
            result.update(status='existing', bytes=target.stat().st_size, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
            report.append(result)
            print(f'[{i}/{len(records)}] {did} já existe')
            continue
    try:
        with session.get(url, timeout=args.timeout, allow_redirects=True, stream=True) as response:
            response.raise_for_status()
            temp=target.with_suffix('.part')
            hash_obj=hashlib.sha256()
            size=0
            with temp.open('wb') as fd:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        fd.write(chunk)
                        hash_obj.update(chunk)
                        size+=len(chunk)
            with temp.open('rb') as fd:
                sig=fd.read(5)
            if sig != b'%PDF-':
                raise ValueError(f'Conteúdo não é PDF (content-type={response.headers.get("Content-Type", "?")})')
            if size < 500:
                raise ValueError('PDF com menos de 500 bytes')
            os.replace(temp, target)
            result.update(status='ok', bytes=size, sha256=hash_obj.hexdigest())
            print(f'[{i}/{len(records)}] {did} OK ({size/1024:.1f} KB)')
    except Exception as exc:
        try:
            temp.unlink(missing_ok=True)
        except Exception:
            pass
        result.update(status='error', error=str(exc))
        print(f'[{i}/{len(records)}] {did} ERRO: {exc}')
    report.append(result)
    if i < len(records) and args.sleep:
        time.sleep(args.sleep)

fields=list(report[0]) if report else []
with (outdir/'download_log.csv').open('w',encoding='utf-8',newline='') as fp:
    writer=csv.DictWriter(fp,fieldnames=fields)
    writer.writeheader(); writer.writerows(report)
print(f'Concluído: {sum(r["status"] in ("ok","existing") for r in report)}/{len(records)} PDFs. Relatório: {outdir/"download_log.csv"}')
