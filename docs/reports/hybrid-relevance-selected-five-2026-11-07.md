# Recuperação híbrida e relevância estimada — cinco perguntas

## Execução

O pipeline terminou com sucesso em **785,82 segundos (13 min 6 s)**, em CPU,
sem carregar o OLMo. Foram processados os **58 PDFs e 810 páginas** do corpus
local, gerando **4.378 chunks** e um ranking final de **dez chunks para cada
pergunta**, na ordem **7, 1, 5, 13 e 23**. Nenhum PDF falhou ou teve conversão
parcial. Texto e embeddings foram recalculados, sem hits de cache.

Comando, a partir da raiz do repositório:

```bash
CUDA_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -u tools/run_retrieval.py \
  --config experiments/configs/pipeline.json \
  --no-formula-enrichment --bm25-stopwords --bm25-stemming \
  --output experiments/runs/hybrid-relevance-2026-11-07/run
```

O modo foi `hybrid`: semântico + BM25, sem KG. O BM25 usou `k1=1.2`, `b=0.75`,
remoção das 318 stopwords inglesas do scikit-learn e stemming Porter do NLTK.
Continuidade por seção e penalização de capas/referências ficaram ativas.
O reconhecimento de fórmulas ficou **desativado**, acompanhando a versão atual
de `src/main.py`; a flag substitui o valor `true` ainda presente no JSON de
experimentos. Nenhuma configuração de inferência foi alterada para esta execução.

| Etapa | Tempo |
| --- | ---: |
| PDFs e chunking | 689,29 s |
| Embeddings dos documentos | 80,69 s |
| Construção BM25 | 0,68 s |
| Total, incluindo importações e exportações | 785,82 s |

O pico RSS do processo foi 4.372,21 MiB, aproximadamente 4,27 GiB. Estes números
descrevem a recuperação local; não medem a execução oficial completa na H100,
que também inclui a geração das respostas. O corpus anterior tinha 54 PDFs;
esta execução tem quatro artigos adicionais de IA, portanto não isola o efeito
das mudanças de recuperação em uma comparação com aquele teste.

## Arquivos gerados

- [JSON pronto para o notebook: hybrid.json](../../experiments/runs/hybrid-relevance-2026-11-07/run/llm_inputs/hybrid.json): perguntas, respostas esperadas, prompt e dez chunks completos por pergunta.
- [Rankings e scores](../../experiments/runs/hybrid-relevance-2026-11-07/run/retrieval.jsonl).
- [Revisão por pergunta](../../experiments/runs/hybrid-relevance-2026-11-07/run/review.md).
- [Configuração efetiva](../../experiments/runs/hybrid-relevance-2026-11-07/run/config.json), [tempos](../../experiments/runs/hybrid-relevance-2026-11-07/run/timings.json) e [resumo](../../experiments/runs/hybrid-relevance-2026-11-07/run/summary.json).
- [Julgamentos estimados em JSON](../../experiments/judgments/selected-five-2026-11-07.json) e [planilha CSV](../../experiments/runs/hybrid-relevance-2026-11-07/document-judgments.csv).
- [Métricas calculadas](../../experiments/runs/hybrid-relevance-2026-11-07/metrics.json).

O JSON de entrada pode ser enviado ao notebook existente. As respostas esperadas
são exportadas para comparação; o notebook não as inclui na mensagem da LLM.
Esta execução não gerou respostas novas.

## Estimativa de relevância dos documentos

As **290 notas** foram estimadas pelo assistente a partir das perguntas e
respostas públicas, títulos, trechos introdutórios e busca/leitura de passagens
nos documentos extraídos. O procedimento é uma triagem, sem revisão integral
de cada artigo nem validação independente. As notas são revisáveis:

- **0 — Não relevante:** não identifiquei evidência útil para a pergunta específica.
- **1 — Possivelmente relevante:** contexto próximo, analogia ou contribuição indireta.
- **2 — Relevante:** evidência direta para pelo menos um aspecto necessário da resposta.

Um documento com nota 2 pode contribuir apenas com parte da resposta. As notas
não foram atribuídas automaticamente pela posição no ranking e não participaram
da recuperação. O JSON contém uma nota para cada par pergunta/documento,
justificativas e passagens de apoio às notas positivas, com offsets no Markdown
e hashes dos documentos. Os demais documentos de cada linha da tabela receberam
nota 0; isso expressa a estimativa desta triagem, não uma prova de ausência de
qualquer evidência útil.

| Questão | Relevantes — nota 2 | Possivelmente relevantes — nota 1 | Não relevantes — nota 0 |
| --- | --- | --- | ---: |
| 7 | DONES-001, DONES-013, DONES-029 | DONES-020, DONES-027 | 53 |
| 1 | Nenhum identificado com evidência direta suficiente | DONES-018, DONES-019, DONES-020, DONES-021, DONES-025, DONES-026 | 52 |
| 5 | DONES-008 | DONES-001, DONES-027, DONES-028, DONES-029 | 53 |
| 13 | AI-007 | Nenhum | 57 |
| 23 | AI-018, AI-019, AI-020 | AI-028 | 54 |

Na **7**, DONES-001 informa 500–600 °C e operação estática antes do arranque ou
após manutenção; DONES-013 sustenta uso durante manutenção e DONES-029 declara
o trap off-line. Na **1**, os artigos de fluorescência explicam excitação e
emissão de fótons, mas não encontrei a comparação específica cintilação versus
OTR; por isso adotei nota 1. Na **5**, DONES-008 explica a cadeia de transporte
e cálculo de inventários; os demais oferecem contexto ou cenários diferentes,
sem cobrir todo o cálculo de Be-7 e trítio da referência. Na **13**, AI-007 é
o artigo do teorema. Na **23**, AI-018 fornece a definição, AI-019 o comparador
FLTrust e AI-020 outras formalizações de robustez.

## Métricas

O [avaliador](../../tools/evaluate_retrieval.py) deduplica os documentos pela
primeira ocorrência entre os dez chunks. O nDCG usa ganhos 0, 1 e 3 para notas
0, 1 e 2. O ranking ideal e os denominadores de Recall usam todos os documentos
anotados, inclusive os que não foram recuperados. Os cortes abaixo contam
**documentos únicos**, não chunks.

| Questão | Documentos recuperados, em ordem | nDCG@10 | Recall@10, notas ≥1 | Recall@10, nota 2 |
| --- | --- | ---: | ---: | ---: |
| 7 | DONES-001, DONES-013, DONES-015 | 0,679 | 0,400 | 0,667 |
| 1 | DONES-019, DONES-026, DONES-020 | 0,645 | 0,500 | — |
| 5 | DONES-029, DONES-001, DONES-002 | 0,330 | 0,400 | 0,000 |
| 13 | AI-007 | 1,000 | 1,000 | 1,000 |
| 23 | AI-019, AI-018 | 0,717 | 0,500 | 0,667 |
| Média macro | | **0,674** | **0,560** | **0,583** |

O Recall estrito da questão 1 é indefinido porque não há documento com nota 2
identificado. A média estrita inclui **quatro perguntas**; as outras duas médias
incluem cinco. Os resultados completos também têm cortes 1, 3 e 5, Precision,
MRR e cobertura de documentos nos primeiros k chunks.

Esses números são relativos aos julgamentos estimados e ao corpus local. Não
são acurácia de respostas, métricas oficiais nem uma avaliação da relevância de
cada trecho. Os CSVs de julgamento de chunks produzidos pelo runner continuam
vazios: a anotação realizada aqui é separada e tem unidade **documento**.

## O que os chunks mostram

| Questão | Observação sobre o contexto final |
| --- | --- |
| 7 | `DONES-001.pdf#12` traz o trap de nitrogênio, sua faixa de temperatura e operação estática. Há evidência útil, mas os chunks de DONES-013 selecionados são de requisitos gerais, não da passagem sobre o Dump Tank. |
| 1 | Há menção a OTR e explicação de excitação na fluorescência em `DONES-026.pdf#3`. A lacuna da comparação com cintilação permanece. |
| 5 | O contexto contém números e purificação, mas não menciona FISPACT nem MCNP. DONES-008, que explica a metodologia, ficou fora dos dez chunks. |
| 13 | O artigo correto foi encontrado, mas o contexto escolheu `#28–31`, `#17–18` e `#12–15`. A construção de Y está em `#32–35`; o fechamento por densidade e repetições está em `#35`, ausente. |
| 23 | `AI-018.pdf#24` inclui a definição (α,f), alinhamento e momentos. FLTrust fornece contexto de confiança no servidor. AI-020 não aparece. O primeiro chunk é a capa de AI-019, incluída como vizinho. |

A questão 13 demonstra por que **nDCG e Recall perfeitos por documento não
garantem o contexto correto**. A expansão alcançou chunks anteriores da seção,
mas ainda não a parte necessária da prova. A questão 23 também mostra que a
continuidade pode reinserir uma capa: a penalização ocorreu antes da expansão,
e o vizinho foi colocado em ordem de leitura. Isso é uma observação desta
execução, sem uma ablação que meça o efeito isolado de cada componente.

Os contextos finais têm 6, 6, 3, 4 e 6 chunks marcados como vizinhos,
respectivamente. Nenhuma referência bibliográfica foi classificada nos top 10;
há uma capa, na questão 23. A questão 13 contém 22 marcadores
`formula-not-decoded` e a 23 contém um. Além disso, **759 chunks (17,3%)**
excederam o limite de entrada do MiniLM. Os JSONs preservam o texto integral;
esse truncamento ocorre no cálculo dos embeddings.

## Reutilizar o avaliador

```bash
.venv/bin/python tools/evaluate_retrieval.py \
  --input experiments/runs/hybrid-relevance-2026-11-07/run/llm_inputs/hybrid.json \
  --judgments experiments/judgments/selected-five-2026-11-07.json \
  --k 1 3 5 10 \
  --output experiments/runs/hybrid-relevance-2026-11-07/metrics.json
```

Para avaliar os documentos efetivamente enviados à LLM após o orçamento de
contexto do notebook, troque `--input` pelo JSON de respostas geradas. O script
usa `chunk_ids` e ignora os IDs omitidos e os textos das respostas. Nenhum modelo
é carregado pelo avaliador. Seus oito testes passaram. Definições, formato dos
julgamentos e diagrama estão em [Métricas de recuperação](../implementations/retrieval-metrics.md).
