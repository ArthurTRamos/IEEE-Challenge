#!/usr/bin/env python3
"""Baixa PDFs indicados em um manifesto CSV; falhas ficam no relatorio."""
import argparse,csv,hashlib,json,pathlib,time,urllib.request

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--manifest',default='artigos_ia_28.csv')
 p.add_argument('--outdir',default='pdfs_ia')
 p.add_argument('--delay',type=float,default=3.0,help='Segundos entre requisicoes')
 a=p.parse_args(); out=pathlib.Path(a.outdir);out.mkdir(parents=True,exist_ok=True)
 with open(a.manifest,encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
 log=[]
 for r in rows:
  url=r['pdf_url']; target=out/(r['id']+'.pdf')
  rec={'id':r['id'],'title':r['title'],'url':url,'path':str(target)}
  if not url:rec['status']='manual_url_required';log.append(rec);continue
  if target.exists() and target.read_bytes()[:5]==b'%PDF-':
   data=target.read_bytes();rec.update(status='exists',sha256=hashlib.sha256(data).hexdigest(),bytes=len(data));log.append(rec);continue
  try:
   request=urllib.request.Request(url,headers={'User-Agent':'KnowledgeCorpusPilot/1.0 (academic research; respectful rate limits)','Accept':'application/pdf'})
   with urllib.request.urlopen(request,timeout=45) as response:
    data=response.read(35*1024*1024+1)
   if not data.startswith(b'%PDF-'):raise ValueError('Resposta nao e PDF')
   if len(data)>35*1024*1024:raise ValueError('PDF maior que 35 MB')
   target.write_bytes(data)
   rec.update(status='downloaded',sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
  except Exception as e:rec.update(status='failed',error=str(e))
  log.append(rec);print(rec['id'],rec['status']);time.sleep(max(a.delay,0))
 (out/'download_report.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Relatorio:',out/'download_report.json')
if __name__=='__main__':main()
