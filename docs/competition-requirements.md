# IEEE CIS GPAIS — Requisitos da Competição

## Fontes oficiais

- Visão geral: https://cis.taskforce.ieee.org/gpais/tc-domain-qa-llms/
- Participação e requisitos de código: https://cis.taskforce.ieee.org/gpais/tc-domain-qa-llms/join-the-challenge/
- Avaliação: https://cis.taskforce.ieee.org/gpais/tc-domain-qa-llms/evaluation/
- Kit inicial: https://github.com/jucls/IEEE-CIS-DSQA-Starter-Kit

## Restrições de execução

| Requisito | Restrição |
|---|---|
| GPU | Uma NVIDIA H100 |
| Tempo total de execução | Máximo de 60 minutos |
| Internet durante a avaliação | Indisponível |
| Arquivo de submissão | Máximo de 1 GB |
| Dependências | Ambiente de avaliação pré-configurado |
| Modelo de linguagem | OLMo 3.1 32B Instruct |
| Frequência de submissão | Uma por equipe por dia |

O limite de execução inclui todo o pré-processamento, carregamento de modelos e índices e inferência.

## Domínios de avaliação

1. Instalação de aceleradores de partículas IFMIF-DONES.
2. Publicações científicas especializadas em Inteligência Artificial.

O benchmark oculto contém 100 pares de perguntas e respostas, distribuídos entre cinco categorias:

- Factual
- Comparativa
- Procedimental
- Causal
- Preditiva

## Acesso aos dados

- O benchmark oculto de avaliação não é disponibilizado antecipadamente.
- Uma amostra pública de 25 pares de perguntas e respostas está disponível.
- O corpus de documentos utilizado na avaliação é acessível por meio da interface fornecida.
- Dados externos disponíveis publicamente podem ser utilizados quando devidamente citados.
- Recursos externos necessários durante a avaliação devem ser incluídos no arquivo de submissão.

## Submissão

A submissão deve conter o código de inferência e os arquivos auxiliares necessários, respeitando o limite de tamanho do arquivo.

A submissão final também exige uma descrição da metodologia com quatro páginas, seguindo o formato IEEE.

## Verificações antes da implementação

Antes de modificar o pipeline de submissão, inspecionar:

- O ponto de entrada de execução do kit inicial oficial.
- O arquivo `requirements-participant.txt`.
- Os formatos esperados de entrada e saída.
- Os métodos de acesso ao corpus.
- Os procedimentos de carregamento dos modelos e de inferência.
- As restrições de tempo de execução e dependências.

Não presumir que uma biblioteca disponível no ambiente local também esteja instalada no ambiente de avaliação.

## Objetivos de desempenho específicos do projeto

Os itens abaixo são objetivos de engenharia, não regras oficiais da competição:

- Minimizar o tempo gasto no pré-processamento de PDFs.
- Preservar tabelas, equações, seções e a identidade dos documentos.
- Evitar extrações desnecessárias de grafos utilizando modelos de linguagem.
- Oferecer suporte a recursos de grafos construídos offline.
- Comparar o GraphRAG com um baseline de recuperação híbrida.
- Monitorar acurácia, recall, tempo de execução e consumo de memória.