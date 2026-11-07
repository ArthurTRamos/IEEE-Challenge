# Corpus piloto – IA e matemática (IEEE CIS DSQA)

**28 artigos candidatos** derivados das buscas propostas em `corpus-search-guide.md`. Inclui perguntas 11–20, 22–25; a questão 21 (ThinkMore/chess) **não foi localizada com confiança** nesta rodada e não foi preenchida com um artigo de outro nome. O artigo exato “Fairness by Brute Force” (questão 18) também não foi confirmado; os trabalhos nessa categoria são relacionados, não equivalentes.

## Conteúdo
- `artigos_ia_28.csv` e `.jsonl`: metadados, links, temas, perguntas e papel planejado.
- `download_corpus_ia.py`: download respeitando intervalo, validação por cabeçalho PDF, SHA-256 e relatório de falhas.

## Execução
```
python download_corpus_ia.py --manifest artigos_ia_28.csv --outdir pdfs_ia
```

O catálogo **não contém PDFs baixados**. URLs de arXiv foram formadas a partir de IDs dos artigos encontrados; PDFs de outras editoras devem ser verificados localmente. Campos `pdf_url` vazios indicam download manual. **Nenhuma classificação de relevância foi validada contra o texto exato das perguntas**: `central`, `related`, `contrast` são apenas estratégias de coleta; `review_status=candidate_not_judged` para todos.

## Estratégia experimental
1. Baixar os artigos e registrar falhas; corrigir URLs manuais.
2. Deduplicar versões do mesmo artigo e fixar hashes.
3. Extrair PDFs com o mesmo pipeline do baseline.
4. Manter as questões e respostas públicas em arquivo separado, sem inseri-las como evidências na indexação.
5. Julgar (pergunta, página/trecho, documento) como suporte direto, parcial, negativo difícil ou não julgado.
6. Testar BM25, denso, RRF, chunking, reranking, métricas de recuperação e resposta. Não assumir que documentos não julgados são negativos.
7. Evitar extrapolar parâmetros obtidos em apenas 15 perguntas para o benchmark inteiro.

Fontes: arXiv, NeurIPS, OpenReview (via versão arXiv), MDPI, Wiley, IMPAN/U. Granada e repositórios universitários. ACL e JMLR não precisaram ser forçados, pois a pertinência temática foi prioritária.
