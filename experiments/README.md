# Executar experimentos sem editar código

Os arquivos em `configs/` controlam os experimentos locais. Os resultados ficam
em `runs/`, ignorados pelo Git, em diretórios novos para preservar anotações.

## Grade solicitada de BM25

```bash
.venv/bin/python tools/run_experiments.py --config experiments/configs/bm25-grid.json
```

Esse comando prepara os dados uma vez, reutiliza os caches disponíveis e executa:

- Normalização, stopwords, stemming e stopwords + stemming.
- `k1 = [0.5, 0.75, 1.0, 1.5]` e `b = [0.5, 0.75, 1.0]`.
- BM25 isolado e combinado com semântico e as duas variantes de KG.
- Controles sem BM25: semântico, semântico + menções e semântico + grafo.

São 48 configurações lexicais e 195 configurações de recuperação, incluindo os
três controles calculados uma vez. Para conferir o plano antes de executar:

```bash
.venv/bin/python tools/run_experiments.py --config experiments/configs/bm25-grid.json --plan-only
```

## Onde alterar os parâmetros

| Arquivo | O que editar |
| --- | --- |
| [configs/bm25-grid.json](configs/bm25-grid.json) | Listas de `k1`/`b`, cenários de pré-processamento, controles e variantes |
| [configs/pipeline.json](configs/pipeline.json) | Corpus, perguntas, modelo, dispositivo, chunking, pesos, top-k e RRF |
| [configs/graph.json](configs/graph.json) | Limites, direção e peso da expansão do grafo |

Para uma única configuração do pipeline:

```bash
.venv/bin/python tools/run_retrieval.py --config experiments/configs/pipeline.json
# Flags explícitas prevalecem sobre o JSON:
.venv/bin/python tools/run_retrieval.py --config experiments/configs/pipeline.json \
  --bm25-k1 0.75 --bm25-b 1 --bm25-stopwords --bm25-stemming
```

Os caminhos escritos nos JSONs são relativos à raiz do repositório, ou absolutos.
`question_ids` seleciona os IDs das perguntas na ordem desejada; atualmente,
`[7, 1, 5, 13, 23]`. `include_reference_answers=true` inclui a resposta esperada
nos JSONs exportados, sem usá-la como entrada da LLM. A configuração atual do
pipeline também habilita stopwords e stemming para BM25, com `k1=1.2` e `b=0.75`.
Os nomes e valores são validados; erros de digitação não são ignorados. A grade
cria automaticamente uma subpasta com timestamp/identificador em `output_root`.
`--output` permite um caminho explícito, que deve estar vazio ou não existir.

Abra `review.md` na saída. O julgamento dos chunks fica em `judgments.csv` e é
compartilhado por todas as configurações. Sem julgamentos, não há seleção
automática de uma vencedora. Consulte o
[guia detalhado](../docs/implementations/experiment-configuration.md).

## Gerar respostas em um notebook externo

Cada execução também salva `llm_inputs/`: um JSON por variante, ou por
configuração/variante na grade. Cada arquivo contém as perguntas e até dez chunks
com texto completo, em ordem, além do prompt de sistema. `index.json` lista os arquivos.

Copie o JSON escolhido para o ambiente externo e ajuste `INPUT_JSON` em
[olmo3_7b_answers.ipynb](../notebooks/generation/olmo3_7b_answers.ipynb).
O notebook gera respostas com `allenai/Olmo-3-7B-Instruct` e salva
`<nome>_answers.json` após cada pergunta.
Para gerar esses arquivos a partir de rankings já salvos:

```bash
.venv/bin/python tools/export_llm_inputs.py --run experiments/runs/SEU_RUN
```

Detalhes do formato e da geração estão no
[guia de geração externa](../docs/implementations/external-generation.md).
