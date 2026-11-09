# Comparação de embeddings e ZIP de submissão — 08/11/2026

## Atualização após a avaliação

O usuário informou **40 de acurácia** para a candidata abaixo. O resultado
contraria a expectativa de ganho baseada no pequeno recorte local; o BGE-small
não deve ser tratado como uma melhoria validada nem como opção preferida.
O encoder reduziu truncamento, mas o nDCG por documento em cinco perguntas foi
insuficiente para prever a qualidade das respostas. A regressão de cobertura
da questão 7, já registrada abaixo, continua sendo um sinal concreto.

O arquivo foi renomeado para `hybrid_noKG_BGESmall.zip`; seu hash coincide com
o manifesto gerado. O [registro de submissões](submission-results.md#emb-01--bge-small-resultado-oficial-informado-de-40)
documenta o relato e o próximo controle recomendado. As seções seguintes
preservam os resultados e a justificativa experimental anteriores à submissão.

## Escolha

O pacote final usa **BAAI/bge-small-en-v1.5**, com **33.360.000 parâmetros**,
vetores de **384 dimensões** e entradas de até **512 tokens**. Ele é maior que
o MiniLM de controle, tem o dobro do limite de entrada e apresentou o melhor
equilíbrio entre os dois modelos BGE testados. A diferença de qualidade no
recorte de cinco perguntas é pequena e há uma regressão importante na questão 7.

O **BGE-base** também foi testado no corpus inteiro. Seus 109.482.240 parâmetros
e vetores de 768 dimensões aumentaram muito o custo em CPU sem melhorar a
recuperação neste teste. Ele não foi incluído no pacote.

Fontes dos modelos e instruções:
[BGE-small](https://huggingface.co/BAAI/bge-small-en-v1.5) e
[BGE-base](https://huggingface.co/BAAI/bge-base-en-v1.5).
A revisão do small é `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`; a do base,
`a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`.

## Comparação controlada

Foram mantidos os mesmos **58 PDFs, 810 páginas, 4.378 chunks**, perguntas
**7, 2, 5, 13 e 23**, julgamentos estimados de relevância e parâmetros:

- BM25 com stopwords e stemming, `k1=1.2`, `b=0.75`, `epsilon=0.25`.
- RRF com pesos iguais entre semântico e BM25, profundidade 100 por canal.
- Chunking por seção, penalizações de capas e referências e top 10 sem expansão.
- Prompt e orçamentos de geração preservados; nenhum OLMo foi carregado.

Todos os modelos foram medidos em **CPU, quatro threads e batch oito**. O texto
dos PDFs veio do cache, mas os vetores de documentos foram **recalculados uma vez
para cada encoder** em um cache novo. Os testes ocorreram em sequência para
evitar competição entre encoders. Os limites, prompts e revisões fazem parte
dos artefatos e da identidade do cache.

O teste compara a substituição completa do encoder, incluindo sua instrução e
limite. Não isola o efeito de aumentar parâmetros, o treinamento, o pooling ou
o limite de tokens individualmente.

| Encoder | Limite | Indexação de embeddings, CPU | Total com texto em cache | Pico RSS |
| --- | ---: | ---: | ---: | ---: |
| MiniLM, controle | 256 | **145,94 s** | 187,72 s | 995,85 MiB |
| BGE-base | 512 | **1.011,73 s** | Ver timings do run | 1.652,12 MiB |
| **BGE-small, escolhido** | **512** | **280,58 s** | **315,37 s** | **1.222,93 MiB** |

O small custou aproximadamente **1,92 vez** o tempo de indexação do controle;
o base, **6,93 vezes**. O small foi aproximadamente **3,61 vezes mais rápido**
que o base nesta medição. Os tempos são deste ambiente de CPU, sem repetição
estatística, e não são uma previsão do throughput da H100.

## Truncamento

| Encoder | Chunks truncados | Parcela do corpus | Perguntas selecionadas truncadas |
| --- | ---: | ---: | ---: |
| MiniLM | 759 | 17,3% | 1 de 5 |
| BGE-base | 255 | 5,8% | 0 de 5 |
| BGE-small | 255 | 5,8% | 0 de 5 |

Foram **504 chunks a menos com corte**, redução de aproximadamente 66,4% na
contagem. A pergunta 13 tem 310 tokens no controle e 318 com a instrução BGE;
o limite de 512 permite representar também sua pergunta final. Os 255 chunks
restantes ainda ultrapassam o limite: o modelo novo reduz o problema, sem
substituir a necessidade de investigar segmentação por tokens em textos longos.

O corte se refere à entrada do embedding. Os chunks completos continuam nos
JSONs exportados para a LLM, sujeitos ao orçamento de contexto do notebook.

## Qualidade estimada da recuperação

As métricas abaixo usam os mesmos
[290 julgamentos por documento](../../experiments/judgments/selected-five-2026-11-08.json).
O ganho é `2^nota - 1`. Cada artigo é contado uma vez, pela primeira ocorrência
no ranking de chunks. Os três modelos têm cinco perguntas com denominador
definido para Recall estrito.

| Encoder | nDCG@10, híbrido | Recall@10, notas ≥1 | Recall@10, nota 2 | nDCG@10, somente semântico |
| --- | ---: | ---: | ---: | ---: |
| MiniLM | 0,8220 | 0,6967 | 0,9333 | 0,9070 |
| BGE-base | 0,7463 | 0,7700 | 0,9333 | 0,6922 |
| **BGE-small** | **0,8371** | **0,7633** | **0,9333** | **0,7328** |

O small melhora pouco o nDCG documental do híbrido; o Recall estrito fica igual.
Ambos os BGE pioram o controle somente semântico neste recorte. Esses resultados
não demonstram aumento de acurácia das respostas ou superioridade geral do novo
encoder. A escolha é uma candidata experimental para reduzir truncamento com
custo menor que o base, acompanhada de verificação das passagens.

## Conferência das evidências do híbrido BGE-small

| Questão | Observação |
| --- | --- |
| 7 | `DONES-029#40` preserva a correção off-line. **O trecho de 500–600 °C, `DONES-001#12`, saiu do top 10**; estava presente no controle. É uma regressão de cobertura que o score por documento não revela. |
| 2 | `DONES-017#19` mantém a perda de energia na passagem pela grade; outros trechos documentam o uso de diagnósticos interceptivos. |
| 5 | Inclui passagens de DONES-027 sobre FISPACT, espectros de decaimento e transporte MCNP, ausentes do contexto do controle. Elas não cobrem sozinhas o cálculo de produção de Be-7 e trítio da resposta esperada. |
| 13 | Mantém `AI-007#35`, com pares densos e epsilons arbitrariamente pequenos. A sequência completa da construção `#32–34` ainda está ausente. A entrada semântica agora inclui a pergunta inteira. |
| 23 | Mantém `AI-018#24`, com a definição, e `AI-020#18`, para comparação das noções de robustez, além do contexto de FLTrust. |

Os checks literais do JSON de comparação são diagnósticos, não um novo gabarito
automático por chunk. Em particular, encontrar “FISPACT” e “MCNP” não garante
que a passagem sustente todos os detalhes da questão 5. O próximo passo é
anotar essas passagens e ampliar o conjunto de perguntas, sem ajustar rótulos
para favorecer um modelo.

## Submissão preparada

O arquivo [hybrid_noKG_BGESmall.zip](../../hybrid_noKG_BGESmall.zip), originalmente
gerado como `hybrid_rag_submission.zip`, tem
**393.272.049 bytes (393,3 MB decimais)**. Inclui:

- BGE-small completo, com limite, instrução de consulta, revisão e manifesto.
- Os sete módulos locais, incluindo o novo `embedding.py`.
- Layout Docling em Transformers **e ONNX**, conforme solicitado anteriormente.
- Busca híbrida, penalizações e seleção top 10 sem expansão de vizinhos.

CodeFormulaV2, o artefato KG, MiniLM, BGE-base, PDFs e caches não entram no pacote
final. O pacote anterior de 398.602.705 bytes e os pesos MiniLM foram preservados
em `experiments/runs/embedding-comparison-2026-11-08/previous-minilm-submission.zip`
e `.cache/embedding-models/`, respectivamente. O pacote anterior tem a seleção
com expansão, portanto não é exatamente o controle sem expansão desta tabela.

O build verifica identidade e integridade do modelo, arquivos necessários,
CRC do ZIP e limite decimal de 1 GB. Os pesos small têm 133.462.128 bytes antes
da compressão; o ZIP menor não indica remoção do ONNX. As revisões e tamanhos
por arquivo estão no [registro do pacote](../../experiments/runs/embedding-comparison-2026-11-08/submission.json).

## Tempo e memória na avaliação

Na submissão, documentos são codificados na GPU disponível, em batch oito,
**antes da carga do OLMo**. O encoder retorna à CPU e o cache CUDA é liberado;
as consultas seguintes são codificadas em CPU. Essa mudança evita manter o
encoder na VRAM durante a geração e permite usar a H100 na indexação.

A GPU não estava acessível neste ambiente local. O ciclo CUDA foi testado com
mocks; seu throughput e o tempo total oficial não foram medidos. Os 315 segundos
locais reutilizam Markdown e excluem a geração. O limite de uma hora continua
dependendo do corpus oculto e da execução completa com OLMo. Os logs da submissão
passam a indicar dispositivo e tempo de codificação dos documentos.

## Validações e arquivos

**111 testes passaram** na versão final. Incluem os papéis de prompts, cache
sob `.cache/`, integridade de pesos, retorno do encoder à CPU e seleção de dez
âncoras sem vizinhos. A carga do encoder extraído do ZIP foi feita com rede
desativada, codificando a pergunta 13 inteira e um documento, com vetores finitos
e normalizados de 384 dimensões. Nenhum modelo de respostas foi carregado.

Os hashes de todos os arquivos do encoder dentro do ZIP coincidem com o
manifesto. Os sete módulos coincidem byte a byte com o workspace. A interface
`answer(question, corpus_dir, model_id)` foi preservada.

- [JSON final para o notebook, com identificação do encoder](../../experiments/runs/embedding-comparison-2026-11-08/bge-small-hybrid.json).
- [Comparação completa em JSON](../../experiments/runs/embedding-comparison-2026-11-08/comparison.json).
- [Métricas do híbrido escolhido](../../experiments/runs/embedding-comparison-2026-11-08/bge-small-hybrid-metrics.json).
- [Auditoria das perguntas](../../experiments/runs/embedding-comparison-2026-11-08/bge-small/query-embedding-audit.json).
- [Configuração efetiva do experimento escolhido](../../experiments/runs/embedding-comparison-2026-11-08/bge-small/config.json).
- [Tempos do small](../../experiments/runs/embedding-comparison-2026-11-08/bge-small/timings.json) e [do base](../../experiments/runs/embedding-comparison-2026-11-08/bge-base/timings.json).
- [Resultado da validação offline](../../experiments/runs/embedding-comparison-2026-11-08/submission.json).
- [Implementação e diagrama](../implementations/embedding-models.md).

Para reconstruir a mesma seleção local, com os pesos já preparados:

```bash
source .venv/bin/activate
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  EMBED_MODEL_ID=BAAI/bge-small-en-v1.5 REUSE_MODELS=1 ./src/build.sh
```
