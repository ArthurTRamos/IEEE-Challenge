# Documentação

Comece pela [visão técnica do projeto](technical-overview.md), que apresenta os
componentes e seu fluxo. Para fórmulas, formatos de dados, parâmetros e testes,
use o [índice de implementações](implementations/README.md).
Para executar, comparar e interpretar testes, veja o [guia prático](testing-guide.md).

- [Requisitos da competição](competition-requirements.md)
- [Plano de pesquisa e integração da DBpedia](plans/dbpedia-integration-plan.md)
- [Plano de experimentos até 30/11](plans/experimentation-roadmap.md)
- [Expressões de busca e seleção de distratores](plans/corpus-search-guide.md)
- [Base ampliada: 25 perguntas, 64 documentos e evidências anotadas](reports/public-25-corpus-2026-11-08.md)
- [Comparação das cinco variantes com MiniLM nas 25 perguntas](reports/all-versions-public25-2026-11-08.md)
- [Revisão dos julgamentos e testes dos pesos BM25/menções](reports/rrf-weights-public25-2026-11-08.md)
- [Variação da constante k do RRF nos dois finalistas](reports/rrf-k-public25-2026-11-08.md)
- [Refatoração, equivalência dos rankings e uso da GPU](reports/refactoring-2026-11-08.md)
- [Resultados informados das submissões](reports/submission-results.md)
- [Relatório de reconhecimento de entidades](reports/kg-linking-report.json)
- [Diagnóstico de exploração do grafo](reports/kg-graph-report.json)
- [Piloto local: PDFs reais e chunks para revisão manual](reports/local-retrieval-pilot-2026-11-07.md)
- [Grade de stopwords, stemming e k1/b do BM25](reports/bm25-grid-2026-11-07.md)
- [Rankings híbridos e relevância estimada das cinco perguntas](reports/hybrid-relevance-selected-five-2026-11-07.md)
- [Nova seleção: questão 2 substitui a 1 e scores recalculados](reports/covered-five-2026-11-08.md)
- [Análise da candidata de 08/11: híbrido sem expansão e próximos passos](reports/submission-assessment-2026-11-08.md)
- [Comparação MiniLM/BGE, custo, truncamento e ZIP de 08/11](reports/embedding-comparison-2026-11-08.md)

Os relatórios distinguem medições locais e dados sintéticos de avaliações de
qualidade sobre o corpus. A documentação de implementações descreve o código
atual; o plano registra decisões e etapas de pesquisa.
