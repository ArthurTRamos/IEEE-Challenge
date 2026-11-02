# Desafio IEEE de Perguntas e Respostas em Domínios Específicos — Instruções para o Codex

## Objetivo do projeto

Desenvolver um sistema de perguntas e respostas (Question Answering — QA) especializado para o IEEE CIS GPAIS Technical Challenge.

O projeto investiga recuperação híbrida e RAG aprimorado com Grafos de Conhecimento (GraphRAG), combinando BM25, recuperação densa e recuperação de evidências baseada em grafos.

## Restrições obrigatórias da competição

- Ambiente de execução: uma GPU NVIDIA H100.
- Tempo máximo total de execução: 60 minutos, incluindo pré-processamento, carregamento de modelos e índices e resposta a todas as perguntas da avaliação.
- Tamanho máximo do arquivo de submissão: 1 GB, incluindo código de inferência e arquivos auxiliares.
- Não há acesso à internet durante a avaliação.
- Utilizar apenas dependências disponíveis no ambiente oficial de avaliação.
- O modelo de linguagem fornecido é o OLMo 3.1 32B Instruct.
- O corpus oculto da avaliação é acessível somente pela interface disponibilizada.
- O sistema deve lidar com os domínios IFMIF-DONES e publicações científicas especializadas em IA.
- As perguntas podem ser factuais, comparativas, procedimentais, causais ou preditivas.

## Requisitos oficiais

Leia `docs/competition-requirements.md` antes de realizar alterações arquiteturais ou introduzir novas dependências.

O kit inicial oficial, a interface de avaliação e as especificações de dependências têm prioridade sobre quaisquer suposições deste documento.

## Regras de desenvolvimento

1. Preservar a compatibilidade com a interface oficial de submissão.
2. Não presumir conectividade com a internet durante a avaliação.
3. Não instalar dependências sem verificar a compatibilidade com o ambiente de avaliação.
4. Evitar consumo desnecessário de memória da GPU e chamadas custosas a modelos de linguagem.
5. Priorizar componentes modulares para processamento de documentos, recuperação de informações, construção de grafos e geração de respostas.
6. Preservar identificadores dos documentos, metadados das seções e referências às evidências originais.
7. Manter o baseline existente funcional durante os experimentos.
8. Medir acurácia, qualidade da recuperação, tempo de execução e consumo de memória.
9. Não inventar resultados de benchmarks nem presumir que uma otimização melhora o desempenho sem realizar testes.
10. Ao propor alterações, explicar seus impactos sobre os limites de 60 minutos de execução e 1 GB de submissão.

## Direção da pesquisa

A equipe está investigando:

- Subgrafos da DBpedia construídos offline.
- Enriquecimento de grafos online ou específico por pergunta, utilizando documentos científicos.
- Recuperação híbrida combinando BM25, recuperação densa e Grafos de Conhecimento.
- Extração de informações de PDFs científicos utilizando Docling ou pipelines adaptativos alternativos.
- Reordenação de evidências (reranking) e raciocínio orientado pelo tipo de pergunta.

Essas abordagens são possibilidades experimentais, não decisões arquiteturais obrigatórias.

## Procedimento de trabalho

Antes de implementar uma alteração significativa:

1. Inspecionar o código existente.
2. Consultar os requisitos relevantes da competição.
3. Propor a menor implementação que permita testar a hipótese.
4. Identificar possíveis problemas de compatibilidade ou consumo de recursos.
5. Implementar e testar.
6. Relatar os resultados obtidos e as limitações restantes.