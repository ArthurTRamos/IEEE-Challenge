# Implementações

Esta pasta detalha os componentes implementados. A introdução menos detalhada
está na [visão técnica](../technical-overview.md).

| Documento | Conteúdo |
| --- | --- |
| [Evidências e fórmulas](evidence-and-formulas.md) | Chunking por seção, continuidade, penalização de metadados e LaTeX offline |
| [Pipeline RAG](rag-pipeline.md) | PDF, chunking, fontes, BM25, embeddings, RRF, contexto e geração |
| [Preparação do KG](kg-data-preparation.md) | Exportações dos notebooks, conversão, esquema, auditoria e proveniência |
| [Recuperação pelo grafo](graph-retrieval.md) | Entidades, postings, adjacência, filtros, limites, pontuação e rastreabilidade |
| [Build e validação](build-and-validation.md) | Ambiente, testes, diagnósticos, ZIP e limites de recursos |
| [Recuperação local e revisão manual](local-retrieval-review.md) | PDFs reais, variantes, caches, tempos e exportação de chunks para anotação |
| [Configuração e grades de experimentos](experiment-configuration.md) | JSON editável, stopwords, stemming, k1/b e controles sem BM25 |
| [Geração externa](external-generation.md) | Top 10 autocontido em JSON e notebook com OLMo 3 7B |
| [Métricas de recuperação](retrieval-metrics.md) | Julgamentos estimados por documento, nDCG, Recall, Precision, MRR e cobertura do contexto |

```mermaid
flowchart TD
    N[Notebooks de pesquisa] --> P[Preparação do artefato]
    P --> G[Recuperação pelo grafo]
    R[Pipeline de documentos] --> G
    G --> F[Fusão e geração no pipeline RAG]
    T[Testes e diagnósticos] --> G
    T --> F
    F --> B[Build e submissão]
```

Ao alterar um componente, atualize seu documento, os parâmetros, os exemplos
e os fluxos/diagramas correspondentes. Resultados medidos ficam em `docs/reports/`, com identificação
do cenário e das limitações.
