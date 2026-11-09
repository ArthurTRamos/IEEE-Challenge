# Substituição da questão sem evidência direta — 08/11/2026

A seleção passou de **7, 1, 5, 13 e 23** para **7, 2, 5, 13 e 23**, conforme
confirmado pelo usuário. A questão 1 não tinha documentos com nota 2
(relevantes), embora tivesse documentos com nota 1 (possivelmente relevantes).
A questão 13 permanece: ela tem um artigo diretamente relevante e permite
observar problemas de seleção de chunks mesmo quando o documento é encontrado.

## Nova pergunta e relevância

**Questão 2:** “What does a ‘destructive’ beam diagnostic do to the beam it measures?”

A referência explica que o diagnóstico intercepta ou interage fisicamente com
o feixe, perturbando-o; seu uso ocorre no comissionamento ou em manutenção,
em vez da operação normal. A pergunta mantém o domínio DONES e o tema de
diagnóstico de feixes. A escolha foi motivada pela presença de evidências no
corpus, sem tentar maximizar a nota do ranking.

| Documento | Nota estimada | Motivo |
| --- | ---: | --- |
| DONES-017 | 2 | Descreve um SEM Grid interceptivo e a perda de energia do feixe ao atravessar a grade |
| DONES-018 | 2 | Documenta diagnósticos interceptivos, como wire scanners e Faraday cups, no comissionamento; apoio parcial à referência |
| DONES-019 | 2 | Determina evitar métodos interceptivos na potência nominal e explica seu uso no comissionamento |
| DONES-022 | 1 | Apresenta a combinação de instrumentos interceptivos e não interceptivos |
| DONES-025 | 1 | Contextualiza a escolha de diagnóstico não interceptivo e o risco de dano ao instrumento |
| DONES-026 | 1 | Oferece um diagnóstico não interceptivo de fluorescência como contraste |
| Outros 52 documentos | 0 | Não foi identificada contribuição útil para a pergunta específica na triagem |

São estimativas do assistente, com os mesmos critérios do
[teste anterior](hybrid-relevance-selected-five-2026-11-07.md). Uma nota 2 pode
representar apoio a parte da referência. A destruição do instrumento, citada em
DONES-025, não deve ser confundida com a perturbação do feixe que define o
diagnóstico destrutivo. Ocorrências de “Non-Destructive Examination” em
DONES-012 tratam de soldas; “intercept” em DONES-021 também aparece como
intercepto matemático. Esses casos não receberam nota positiva.

O novo arquivo reúne **290 julgamentos**, sendo **58 novos para a questão 2**
e **232 preservados integralmente** para as outras quatro perguntas. Há
justificativas e passagens de apoio às notas positivas. Os documentos e seus
hashes são os mesmos do corpus anterior; as citações de apoio preservam os
arquivos Markdown da execução de 07/11.

## Execução

```bash
CUDA_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -u tools/run_retrieval.py \
  --config experiments/configs/pipeline.json \
  --output experiments/runs/covered-five-2026-11-08/run
```

O modo continua **hybrid**, com stopwords e stemming ativos, `k1=1.2`, `b=0.75`,
continuidade por seção e penalização de capas/referências. A configuração agora
explicita `formula_enrichment=false`, reproduzindo a opção usada na execução
anterior e no código atual de submissão. O método de recuperação e seus pesos
não foram alterados.

O pipeline terminou em **48,85 segundos**, em CPU, sem carregar OLMo. Foram
mantidos **58 PDFs, 810 páginas e 4.378 chunks**, com dez chunks por pergunta.
Houve **58 hits de cache de texto** e reutilização dos embeddings. Nenhum PDF
falhou ou teve conversão parcial. O pico RSS do processo foi 965,32 MiB. A
diferença de tempo em relação aos 13 minutos anteriores decorre do cache e
não demonstra uma otimização no processamento de PDFs.

Os JSONs exportados das perguntas **7, 5, 13 e 23** são idênticos aos anteriores,
incluindo textos, ordem, IDs dos chunks e scores. Seus julgamentos também são
idênticos. Essa comparação foi verificada por igualdade dos registros completos.

## Scores recalculados

As métricas são por **documento único**, mantendo a ordem da primeira ocorrência
entre os chunks. `k=10` conta documentos. O nDCG usa ganho `2^nota - 1`; o Recall
inclui os documentos relevantes não recuperados no denominador.

| Questão | Documentos recuperados, em ordem | nDCG@10 | Recall@10, notas ≥1 | Recall@10, nota 2 |
| --- | --- | ---: | ---: | ---: |
| 7 | DONES-001, DONES-013, DONES-015 | 0,6786 | 0,4000 | 0,6667 |
| 2 | DONES-019, DONES-017 | 0,6466 | 0,3333 | 0,6667 |
| 5 | DONES-029, DONES-001, DONES-002 | 0,3296 | 0,4000 | 0,0000 |
| 13 | AI-007 | 1,0000 | 1,0000 | 1,0000 |
| 23 | AI-019, AI-018 | 0,7171 | 0,5000 | 0,6667 |
| Média macro, cinco perguntas | | **0,6744** | **0,5267** | **0,6000** |

| Média | Seleção anterior | Nova seleção |
| --- | ---: | ---: |
| nDCG@10 | 0,6740, cinco perguntas | 0,6744, cinco perguntas |
| Recall@10, notas ≥1 | 0,5600, cinco perguntas | 0,5267, cinco perguntas |
| Recall@10, nota 2 | 0,5833, quatro perguntas | 0,6000, cinco perguntas |

Agora o Recall estrito tem denominador definido para todas as cinco perguntas.
A troca praticamente mantém o nDCG médio e reduz o Recall amplo; a média estrita
passa a incluir uma pergunta adicional. **O conjunto de perguntas mudou**, então
essas diferenças não indicam melhora ou piora do algoritmo.

Para a nova pergunta, `DONES-019.pdf#9` explica as restrições aos métodos
interceptivos e o uso no comissionamento; `DONES-017.pdf#18–19` contém a
descrição do SEM Grid e da perda de energia ao atravessar os fios. Esses chunks
estão presentes no contexto exportado. Não houve geração de resposta para
validar como a LLM utiliza as evidências.

Os problemas das outras perguntas permanecem: a 5 não recupera a metodologia
de cálculo e a 13 encontra o artigo, mas deixa de fora a construção central de
Y. Os detalhes continuam no [relatório anterior](hybrid-relevance-selected-five-2026-11-07.md).

## Arquivos e reprodução das métricas

- [JSON pronto para o notebook](../../experiments/runs/covered-five-2026-11-08/run/llm_inputs/hybrid.json).
- [Revisão dos rankings](../../experiments/runs/covered-five-2026-11-08/run/review.md).
- [Julgamentos estimados](../../experiments/judgments/selected-five-2026-11-08.json).
- [Métricas completas](../../experiments/runs/covered-five-2026-11-08/metrics.json).
- [Configuração efetiva](../../experiments/runs/covered-five-2026-11-08/run/config.json) e [tempos](../../experiments/runs/covered-five-2026-11-08/run/timings.json).

```bash
.venv/bin/python tools/evaluate_retrieval.py \
  --input experiments/runs/covered-five-2026-11-08/run/llm_inputs/hybrid.json \
  --judgments experiments/judgments/selected-five-2026-11-08.json \
  --k 1 3 5 10 \
  --output experiments/runs/covered-five-2026-11-08/metrics.json
```

O script também aceita o JSON de respostas devolvido pelo notebook. Definições
dos cortes, interpretação das notas e limitações estão em
[Métricas de recuperação](../implementations/retrieval-metrics.md).
