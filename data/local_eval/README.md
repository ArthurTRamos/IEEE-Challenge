# Base local das 25 perguntas públicas

Conjunto de desenvolvimento para avaliar a recuperação. Preserva as 25 perguntas
e respostas oficiais e associa os 64 PDFs locais a notas **estimadas pelo assistente**.
Os julgamentos precisam de revisão humana e não são um teste independente.

| Arquivo | Uso |
| --- | --- |
| [questions.json](questions.json) | Perguntas e respostas, sem modificar o conteúdo oficial |
| [documents.jsonl](documents.jsonl) | Catálogo, caminhos, URLs e hashes dos PDFs/Markdown |
| [annotation-spec.json](annotation-spec.json) | Anotação editável: positivos, justificativas, lacunas e seletores das evidências |
| [coverage.csv](coverage.csv) / [coverage.json](coverage.json) | Cobertura por pergunta e grupos para comparações |
| [evidence.jsonl](evidence.jsonl) | 97 passagens com offsets, hashes e localizadores de figuras |
| [qrels.tsv](qrels.tsv) | Formato `question_id  0  document_id  grade`, separado por tabs |
| [Julgamentos completos](../../experiments/judgments/public-25-2026-11-08.json) | Matriz de 1.600 notas compatível com o avaliador existente |

As pastas geradas `markdown/`, `page-text/` e `figures/` ficam fora do Git.
Os PDFs permanecem em `data/download_pdfs/`. As respostas esperadas e as notas
não entram na recuperação; o runner só usa as perguntas e os documentos.

A revisão posterior dos negativos acrescentou contexto nota 1 para
Q6/DONES-034 e Q25/AI-025/AI-027. A especificação editável preserva essas notas.
Os [testes de pesos](../../docs/reports/rrf-weights-public25-2026-11-08.md)
usam a versão corrigida dos julgamentos, com AI-027 em lugar de AI-026.

Para conferir fontes e regeneração:

```bash
.venv/bin/python tools/build_public_qa_judgments.py --check
```

Para editar, altere `annotation-spec.json` e execute o mesmo comando sem
`--check`. Mudanças no PDF/Markdown exigem revisar as evidências e atualizar os
fingerprints conscientemente. Não reutilize offsets após trocar o extrator.

Consulte o [relatório de cobertura](../../docs/reports/public-25-corpus-2026-11-08.md)
e o [guia da implementação](../../docs/implementations/public-evaluation-dataset.md).
