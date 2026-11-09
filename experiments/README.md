# Executar experimentos sem editar código

Os arquivos em `configs/` controlam os experimentos locais. Os resultados ficam
em `runs/`, ignorados pelo Git, em diretórios novos para preservar anotações.

O [guia prático de testes e resultados](../docs/testing-guide.md) é o ponto de
partida atual. O preset `configs/public-25-minilm.json` usa MiniLM, as cinco
variantes e `embedding_device=auto`; Docling fica em CPU por padrão.

## Base das 25 perguntas públicas

A [base ampliada](../data/local_eval/README.md) contém as 25 perguntas oficiais,
64 documentos e julgamentos estimados para os 1.600 pares. O
[relatório de cobertura](../docs/reports/public-25-corpus-2026-11-08.md) identifica
as fontes ausentes, parciais e visuais; 22 perguntas têm algum documento nota 2.
A questão 1 passou a ter evidências diretas com as fontes novas de cintilação/OTR.

Use `configs/public-25.json` no próximo experimento e escolha `embed_model` antes
de executar. Essa configuração fixa os IDs dos documentos, inclui stopwords e
stemming e compara `dense`, `bm25` e `hybrid`, sem LLM. O caminho do encoder foi
copiado da configuração atual; isso não escolhe uma nova candidata de submissão.

```bash
.venv/bin/python tools/build_public_qa_judgments.py --check
.venv/bin/python tools/run_retrieval.py --config experiments/configs/public-25.json \
  --output experiments/runs/public-25-SEU-EXPERIMENTO
.venv/bin/python tools/evaluate_retrieval.py \
  --input experiments/runs/public-25-SEU-EXPERIMENTO/llm_inputs/hybrid.json \
  --judgments experiments/judgments/public-25-2026-11-08.json \
  --output experiments/runs/public-25-SEU-EXPERIMENTO/metrics-hybrid.json
```

Os seis PDFs adicionados mudam o corpus encontrado por configurações sem filtro
de documentos. Não compare scores antigos de 58 documentos com scores novos
de 64 como se apenas um parâmetro de recuperação tivesse mudado. Os julgamentos
e execuções históricos continuam preservados.

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
`[7, 2, 5, 13, 23]`. A questão 2 substitui a 1 por ter evidência direta no corpus;
o [relatório de 08/11](../docs/reports/covered-five-2026-11-08.md) registra os novos scores.
`include_reference_answers=true` inclui a resposta esperada
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

## Avaliar a recuperação com julgamentos de relevância

O avaliador aceita tanto o JSON de entrada quanto o JSON de respostas do
notebook e não carrega modelos:

```bash
.venv/bin/python tools/evaluate_retrieval.py \
  --input experiments/runs/covered-five-2026-11-08/run/llm_inputs/hybrid.json \
  --judgments experiments/judgments/selected-five-2026-11-08.json \
  --k 1 3 5 10 \
  --output experiments/runs/covered-five-2026-11-08/metrics.json
```

Os julgamentos iniciais usam notas 0 (não relevante), 1 (possivelmente relevante)
e 2 (relevante), estimadas pelo assistente para os documentos locais. As métricas
são por **documento**, com artigos repetidos deduplicados; não medem diretamente
a utilidade de cada chunk. O resultado inclui nDCG e Recall com dois limiares,
além de cobertura de documentos dentro dos primeiros k chunks.
Veja [definições e formato dos julgamentos](../docs/implementations/retrieval-metrics.md).

## Continuidade, penalizações e fórmulas

O pipeline padrão usa `hybrid`, chunking por seção e penalização de capas e
referências. `continuity=false` seleciona os dez melhores candidatos sem expandir
vizinhos. `formula_enrichment=false` acompanha a inferência atual e as últimas
execuções locais, que não utilizam o reconhecimento de fórmulas.
Os parâmetros e flags de ablação estão em
[Evidências e fórmulas](../docs/implementations/evidence-and-formulas.md).
Para ativar o reconhecimento opcional, os pesos precisam ser preparados com
`tools/prepare_formula_model.py`; eles não entram no build atual. Mudanças no
chunking alteram IDs e textos; use novas pastas de execução e não transfira
julgamentos antigos apenas por ID. A grade BM25 continua disponível para
combinações futuras, com os componentes definidos no pipeline associado.

## Comparar embeddings

O caminho `embed_model` seleciona o encoder local. Os prompts de consulta e o
limite de tokens acompanham o modelo salvo e são usados igualmente pelo runner
e pela submissão. A auditoria inclui truncamento dos documentos e das perguntas.
Preparação, configurações e cuidados com tempo/VRAM estão em
[Modelos de embedding](../docs/implementations/embedding-models.md).
