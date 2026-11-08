# Visão técnica do projeto

O sistema responde perguntas sobre IFMIF-DONES e artigos de IA usando evidências
extraídas de PDFs. A interface de submissão é
`answer(question, corpus_dir, model_id) -> str`, em [main.py](../src/main.py).

## Fluxo completo

```mermaid
flowchart LR
    P[PDFs do corpus] --> D[Docling, fórmulas em LaTeX e chunks por seção]
    D --> B[Índice BM25]
    D --> E[Embeddings MiniLM]
    D --> I[Índice de menções de entidades]
    K[KG local da DBpedia] --> I
    Q[Pergunta] --> B
    Q --> E
    Q --> G[Entidades e vizinhos de um salto]
    K --> G
    I --> G
    B --> R[Fusão RRF dos chunks]
    E --> R
    G -. KG opcional .-> R
    R --> M[Penalização de capas e referências]
    M --> V[Continuidade na mesma seção]
    V --> C[Contexto com fontes e limite de tokens]
    C --> L[OLMo fornecido pela avaliação]
    Q --> L
    L --> A[Resposta]
```

O padrão de submissão é **hybrid** (semântico + BM25, `KG_MODE=off`). O KG
é opcional. O reconhecimento de fórmulas usa CodeFormulaV2 local; os chunks
respeitam títulos e a seleção expande vizinhos da mesma seção, com limites.
Capas e referências têm pontuação reduzida, sem serem excluídas.

## Implementações principais

| Parte | O que faz | Detalhes |
| --- | --- | --- |
| Evidências e fórmulas | Seções, vizinhos, penalizações e extração LaTeX offline | [Detalhes](implementations/evidence-and-formulas.md) |
| Documentos e geração | Extrai Markdown, cria chunks, preserva referências e monta o prompt | [Pipeline RAG](implementations/rag-pipeline.md) |
| Busca híbrida | Combina BM25 e semântico por RRF; KG opcional | [Pipeline RAG](implementations/rag-pipeline.md#recuperação-e-fusão) |
| Preparação da DBpedia | Converte os resultados dos notebooks para arquivos locais validados | [Preparação do KG](implementations/kg-data-preparation.md) |
| Exploração do grafo | Segue associações de um salto para recuperar chunks de entidades vizinhas | [Recuperação pelo grafo](implementations/graph-retrieval.md) |
| Testes e submissão | Valida componentes, executa diagnósticos e constrói o ZIP | [Build e validação](implementations/build-and-validation.md) |
| Avaliação local | Salva rankings e chunks dos PDFs para revisão humana, sem OLMo | [Revisão manual](implementations/local-retrieval-review.md) |
| Experimentos configuráveis | Executa combinações de BM25 e canais a partir de JSON | [Configuração de experimentos](implementations/experiment-configuration.md) |
| Geração externa | Exporta as perguntas e seus dez chunks finais para um notebook com OLMo 3 7B | [Geração externa](implementations/external-generation.md) |
| Métricas de recuperação | Compara documentos recuperados com notas estimadas de relevância, usando nDCG e Recall | [Métricas](implementations/retrieval-metrics.md) |

## Como o grafo influencia a busca

O KG primeiro reconhece nomes equivalentes, como “Be7” e “Beryllium-7”. Agora
também consulta vizinhos da entidade e procura os chunks que mencionam esses
vizinhos. Os candidatos entram no terceiro ranking do RRF. Só são considerados
vizinhos encontrados no corpus, com limites de quantidade, grau e frequência.

O grafo orienta a recuperação; as passagens enviadas ao modelo continuam vindo
dos PDFs. Um `wikiPageWikiLink` é tratado como associação editorial, sem atribuir
causalidade ou equivalência à conexão.

| `KG_MODE` | Comportamento |
| --- | --- |
| `off` | BM25 + semântico |
| `mentions` | Acrescenta menções das entidades da pergunta |
| `graph` | Acrescenta menções e expansão limitada por vizinhos; experimental |

## Organização

- `src/`: código de inferência e build; `src/kg/` contém artefatos gerados.
- `notebooks/dbpedia/`: coleta offline e protótipos de pesquisa.
- `data/`: exportações originais recebidas do notebook.
- `tools/`: preparação e diagnóstico local.
- `tests/`: testes de índices, ranking, integração e integridade.
- `docs/implementations/`: descrição detalhada do código implementado.
- `docs/reports/`: resultados de diagnósticos; `docs/plans/`: planos de pesquisa.

## Restrições e estado da avaliação

O ambiente oficial usa uma H100, não possui internet e limita a execução total
a 60 minutos e o ZIP a 1 GB. O KG roda em CPU, sem outro modelo de linguagem ou
dependência adicional em inferência. Consulte os
[requisitos locais da competição](competition-requirements.md).

Há testes funcionais, diagnóstico com chunks sintéticos e um runner sobre PDFs
reais que compara semântico, BM25 e as variantes do KG. O runner exporta Markdown
e CSV com julgamentos inicialmente vazios. Ainda não há métricas de relevância
sem a anotação manual, nem medição de acurácia das respostas ou da execução
completa na H100.
