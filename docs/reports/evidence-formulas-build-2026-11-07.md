# Build híbrido com continuidade, fórmulas e penalizações

Implementação detalhada: [Evidências e fórmulas](../implementations/evidence-and-formulas.md).
Dados medidos: [JSON do relatório](evidence-formulas-build-2026-11-07.json).

## Artefato

- [hybrid_rag_submission.zip](../../hybrid_rag_submission.zip): **746.098.072 bytes**, abaixo do limite decimal de 1 GB.
- Padrão: semântico + BM25 com stopwords/stemming, `k1=1.2`, `b=0.75`, sem KG.
- Chunking por seção, continuidade limitada, penalizações de referências/capas
  e CodeFormulaV2 offline habilitados. Nenhum reranker neural adicionado.
- O pacote contém layout Transformers, MiniLM e CodeFormulaV2. KG e layout ONNX
  não estão no ZIP padrão.

## Verificações realizadas

1. **96 testes passaram**, incluindo limites de seção, integridade de blocos
   matemáticos, hierarquia, penalizações, vizinhança, deduplicação, montagem da
   mensagem e integração do runner.
2. Uma conversão offline real da página 10 de AI-007 concluiu com status
   `success`, reconhecendo as duas desigualdades em LaTeX e nenhum marcador
   `formula-not-decoded`. Tempo: aproximadamente **19,84 s em CPU**, incluindo a
   carga nessa conversão. Isso não é validação matemática completa: há uma
   quebra de linha LaTeX residual ao fim de uma das expressões.
3. O runner executou sobre um corpus diagnóstico de **três páginas**: páginas
   10 e 11 de AI-007 e página 4 de AI-018. Concluiu a extração de dois PDFs,
   produziu 19 chunks e exportou as perguntas 13 e 23 em modo hybrid, sem LLM.
   Tempo medido do runner: **23,12 s**, com cache de Markdown em um dos dois
   PDFs. Esse teste comprova integração, não recall, acurácia ou custo do corpus
   completo. Nas páginas recortadas podem faltar títulos de seções presentes no
   PDF completo; as regras de continuidade estão cobertas pelos testes unitários.
4. O build passou por verificação CRC e limite de tamanho. Os seis módulos de
   inferência no ZIP foram comparados byte a byte com os arquivos atuais. O
   SHA-256 dos pesos CodeFormulaV2 dentro do ZIP coincide com o manifesto.

Os resultados locais do teste de integração estão em
[section-formula-smoke-2026-11-07-complete](../../experiments/runs/section-formula-smoke-2026-11-07-complete/review.md).
Os PDFs recortados foram somente entradas temporárias para diagnóstico; a
seleção das páginas foi registrada no JSON do relatório. Não há resultados de
respostas OLMo novos nesta implementação.

## Limitações restantes

A submissão deve ser medida no ambiente H100 com o corpus completo. O modelo
adicional de fórmulas aumenta o processamento inicial e a memória durante a
conversão; ele é liberado antes da carga do modelo de resposta. Não foi
verificado o limite de 60 minutos com OLMo 32B nem um ganho de qualidade sobre o
baseline. Tabelas estruturadas e OCR geral continuam desativados. Reconhecimento
de fórmulas, títulos e capas é falível; os novos fatores e limites são parâmetros
iniciais para avaliação, não valores otimizados.
