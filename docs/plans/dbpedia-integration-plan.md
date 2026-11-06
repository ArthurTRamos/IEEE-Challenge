# Plano de integração da DBpedia à recuperação híbrida

**Estado atual:** as exportações em `data/` foram auditadas e convertidas.
A recuperação por menções e a expansão limitada de um salto estão implementadas
com testes. Consulte a [visão técnica](../technical-overview.md) e a
[implementação do grafo](../implementations/graph-retrieval.md). A avaliação
completa no corpus, a busca geral de pontes e o contexto direto do KG continuam
pendentes. O restante deste documento registra o plano e a análise inicial;
as observações sobre arquivos ausentes se referem àquela etapa.

## Proposta

Usar o subgrafo da DBpedia construído antes da submissão para reconhecer
entidades, expandir termos e recuperar evidências do corpus. A primeira versão
deve acrescentar um terceiro ranking de **chunks do corpus** à fusão RRF atual.
Contexto textual vindo diretamente da DBpedia será um experimento posterior.

Essa ordem permite avaliar se o grafo ajuda a encontrar as passagens necessárias,
antes de acrescentar uma segunda fonte de afirmações ao prompt.

Este documento registra análise estática dos notebooks e de suas saídas salvas.
As extrações e as consultas não foram executadas nesta análise. Os arquivos
`domain_kg.ttl`, `kg_rag_chunks.jsonl` e os bancos gerados não estão presentes no
checkout analisado, portanto sua qualidade ainda precisa ser auditada.

## O que os notebooks já oferecem

### `notebooks/dbpedia/01_extract_domain_kg.ipynb`

- Parte de 41 categorias e de entidades de física, IA e matemática; expande
  subcategorias por `skos:broader`, em profundidade 1.
- Busca membros das categorias, labels e comentários em inglês, propriedades,
  redirecionamentos e links entre entidades selecionadas.
- Implementa cache SQLite de consultas, tentativas e divisão adaptativa de lotes.
- Usa PageRank para ordenar entidades e podar o grafo quando o Turtle ultrapassa
  o orçamento configurado de 95 MiB.
- Exporta RDF/Turtle e cartões JSONL com URI, label, aliases, definição,
  categorias, propriedades e conceitos relacionados.
- Nas saídas salvas: 8.344 entidades candidatas, 60.021 links internos,
  79.235 triplas e Turtle de 2,93 MiB. A etapa de metadados levou 58min23s e a
  de links 1h13min11s. Só essas etapas já excedem o limite de avaliação.

### `notebooks/dbpedia/02_retrieval_prototypes.ipynb`

- `HybridKGRetriever` importa os cartões e o Turtle para DuckDB, gera embeddings
  com `BAAI/bge-small-en-v1.5` e consulta entidades por similaridade e aliases.
- A pontuação combina similaridade com bônus fixos de 0,35/0,40; apesar do
  comentário sobre fusão, esse código não implementa RRF.
- Recupera propriedades, vizinhos e entidades intermediárias compartilhadas
  por duas ou mais entidades; monta contexto conforme o tipo de pergunta.
- A saída salva informa indexação de 8.342 nós, mas os exemplos exibem
  definições vazias e não exibem atributos. Também aparecem candidatos como
  `Proton emission` e `Photon Multiplicity Detector` na pergunta sobre OTR e
  cintilação. Isso indica necessidade de avaliar cobertura e precisão.
- `UnifiedCompetitionRAG` propõe aliases derivados de siglas do corpus e tabelas
  conjuntas para documentos e KG. Nessa classe não há implementação da ingestão
  dos documentos/KG nem do fluxo completo de recuperação e montagem de contexto.

## Ajustes necessários antes da integração

| Ponto observado | Tratamento proposto |
| --- | --- |
| DuckDB, RDFLib e SPARQLWrapper não constam no arquivo oficial de dependências | Manter RDFLib/SPARQLWrapper apenas no extrator de desenvolvimento; usar `sqlite3`, JSON e NumPy em inferência. Não depender de DuckDB na submissão. |
| BGE no notebook e MiniLM no pipeline atual | Reutilizar o MiniLM local para documentos, entidades e perguntas. Recriar os embeddings do KG offline; dimensões iguais não tornam espaços vetoriais compatíveis. |
| Ausência de definições e propriedades nos exemplos | Medir preenchimento por entidade, domínio e propriedade. Inspecionar consultas e respostas antes de atribuir a ausência à DBpedia. Avaliar outras propriedades textuais disponíveis somente após verificar a fonte. |
| Aliases exportados no JSONL não são usados pelo primeiro retriever | Importar redirecionamentos e manter o mapa manual como complemento auditável. |
| Mapa manual inclui associações temáticas, como `mamba` → sistema LTI | Distinguir sinônimos de associações; aplicar confiança menor às associações e registrar sua origem. |
| Busca por tokens ignora aliases compostos; substring pode ser ambígua | Reconhecer frases com limites de palavras, preferir a expressão mais longa e resolver ambiguidades com a pergunta e os documentos recuperados. |
| `Be7`, `Be-7` e `7Be`; siglas como `OTR` | Adotar normalizações específicas e testadas, sem unir automaticamente todos os termos alfanuméricos. Validar siglas extraídas por regex antes de registrá-las. |
| `wikiPageWikiLink` e categorias representam associações | Preservar predicado e direção originais; buscas de conectividade podem explorar ambos os sentidos, sem apresentar os caminhos como causalidade ou equivalência. |
| Cortes após conversão de conjuntos em listas e SQL sem ordenação | Ordenar antes de truncar; limitar vizinhos por relevância e grau, com desempate estável. |
| `LIMIT` em consultas e respostas parciais salvas como cache normal | Registrar consulta completa/parcial, limites atingidos, erros e entidades omitidas; dividir/paginar consultas quando necessário. |
| Tipos e idiomas dos literais são descartados; propriedades viram strings | Preservar valor, URI do predicado, datatype, idioma e unidade quando informada. Não inferir unidades ausentes. |
| Orçamento de 95 MiB mede somente o Turtle | Medir cartões, índices, embeddings e ZIP final; evitar duplicar artefatos na submissão. |
| `question_type` é passado nos exemplos, mas não integra `answer()` | Começar sem depender de rótulos; avaliar classificação por regras depois, com comportamento padrão quando houver incerteza. |

Os filtros de categorias também precisam de revisão: excluir globalmente
conferências, periódicos ou instituições pode remover contexto útil ao domínio
de publicações em IA. A seleção manual está muito alinhada aos exemplos públicos;
o ganho deve ser avaliado também em perguntas com termos e entidades distintos.

## Etapa 1 — Extrator reproduzível e auditoria do artefato

1. Extrair o código de coleta para `tools/build_dbpedia_kg.py`, com configuração
   explícita de sementes, propriedades, limites e caminhos. Preservar o cache
   por padrão; a célula que apaga o SQLite deve virar uma opção explícita.
2. Exportar nós e arestas estruturados com URIs, proveniência, data de coleta,
   licença/atribuição da fonte e manifesto das consultas incompletas.
3. Gerar relatório de cobertura: sementes resolvidas, nós com definição,
   aliases, propriedades, unidades, graus e componentes do grafo. Inspecionar
   manualmente uma amostra de ambos os domínios.
4. Ordenar e deduplicar as saídas. Falhar com mensagem clara se o orçamento não
   puder ser atingido, em vez de encerrar o laço de poda sem exportação válida.
5. Exportar o artefato de inferência em `kg/`, usando JSON/SQLite para nós,
   aliases, propriedades e adjacências, mais `embeddings.npy` e `manifest.json`.
   O manifesto deve registrar o hash do modelo/tokenizer MiniLM, dimensão,
   normalização, ordem das URIs e versão do formato.

**Entrega:** artefato carregável sem rede e relatório de qualidade. Não gerar
embeddings a partir de registros dominados por campos vazios ou listas genéricas
de categorias sem antes avaliar a representação textual.

## Etapa 2 — KG para recuperar chunks do corpus

### Inicialização durante a avaliação

1. Em `_build_index()`, manter registros de chunks com `chunk_id`, nome/caminho
   relativo do documento, seção quando disponível e texto. Os rankings devem
   usar o mesmo identificador em todos os canais.
2. Carregar o KG uma vez em `_load()`, validar o manifesto e reutilizar o
   embedder atual em CPU. Nenhum modelo adicional será carregado.
3. Identificar menções de entidades nos chunks com labels/aliases e construir
   postings `entity_uri -> chunk_ids`, com frequência/confiança da menção.
   Usar reconhecimento por frases/tokens para evitar uma busca de todas as
   entidades contra cada chunk. Medir o custo dessa etapa.
4. Registrar siglas identificadas no corpus apenas quando sua expansão puder
   ser ligada com confiança a uma entidade. Preservar documento de origem e
   ambiguidades; não substituir globalmente um alias por uma única entidade.

### Por pergunta

1. Produzir os rankings BM25 e semântico atuais; codificar a pergunta uma vez.
2. Ligar entidades usando aliases/frases e similaridade com os nós do KG.
   Usar os primeiros chunks recuperados para desambiguar siglas e contexto.
   Aplicar limiar de confiança: o retriever pode retornar zero entidades.
3. Recuperar chunks associados às entidades e, em uma variante experimental,
   a poucos vizinhos de um salto. Expandir apenas relações permitidas, penalizar
   hubs e limitar o número de entidades, arestas e candidatos.
4. Ordenar esses chunks por confiança das entidades, menções e distância no
   grafo, com desempate determinístico. Entidades sem correspondência no
   corpus não produzem evidência documental.
5. Fundir os três rankings de **chunk_ids**:

   `score(c) = 1/(60+r_BM25(c)) + 1/(60+r_denso(c)) + w_KG/(60+r_KG(c))`

   Um canal só contribui se o chunk estiver em seu ranking. O peso `w_KG`
   precisa de avaliação; usar um valor conservador configurável inicialmente.
   Não fundir diretamente posições de entidades e posições de chunks.
6. Montar contexto documental com referências às fontes. Se o KG estiver
   desativado ou não houver entidades confiáveis, usar os dois rankings atuais.

**Entrega:** `kg_retrieval.py`, integração opcional em `main.py` e testes. A
assinatura pública `answer(question, corpus_dir, model_id)` permanece compatível.

## Etapa 3 — Contexto direto do KG e pontes

Após medir a etapa anterior, testar um bloco curto da DBpedia para definições
e propriedades com proveniência explícita. Reservar inicialmente até 1.000
tokens do orçamento total atual de 10.000; descontar também títulos, referências
e separadores. Esses valores são parâmetros experimentais.

Priorizar documentos para resultados de artigos, instalações e condições
experimentais. Toda propriedade numérica deve manter fonte e unidade; diferenças
entre valores do KG e do documento não devem ser conciliadas silenciosamente.

Só então avaliar pontes de dois saltos para perguntas que envolvam múltiplas
entidades. Priorizar pontes específicas e confirmadas nos documentos; categorias
amplas e links editoriais não justificam uma explicação causal. O tipo de
pergunta pode ser inferido da própria pergunta, sem acesso ao rótulo da amostra.

## Etapa 4 — Testes e avaliação

- Testes unitários: aliases compostos, limites de palavras, siglas ambíguas,
  variantes de isótopos, correspondência URI/embedding, postings e duplicatas.
- Grafos sintéticos: direção e tipo de relação, hubs, ciclos, limites de saltos
  e ausência de caminhos. Verificar a classificação de chunks, além dos nós.
- Regressão: sem KG ou sem entidades confiáveis, retornar a ordem do baseline;
  com KG, validar a fórmula RRF e o limite de tokens do contexto completo.
- Integração offline: carregar o artefato empacotado sem rede, sem downloads e
  com falha explícita em caso de manifesto/modelo incompatível.
- Comparar variantes: baseline; apenas expansão por aliases; ranking KG por
  menções diretas; expansão de um salto; contexto KG; pontes de dois saltos.
  Essa comparação separa o ganho de sinônimos do ganho da estrutura do grafo.
- Usar as 25 perguntas públicas com cautela: já orientaram sementes e aliases.
  Separar ajuste e avaliação e incluir perguntas adicionais independentes.
  Recall/MRR/nDCG exigem anotar evidências relevantes; respostas de referência
  isoladas não fornecem automaticamente esses rótulos.
- Medir correção das respostas, suporte nas evidências, recuperação, tempo de
  inicialização/pergunta, memória RAM/GPU e tamanho do ZIP. Registrar também
  taxa de ativação do KG e exemplos em que ele piora a resposta.

## Recursos e empacotamento

A coleta SPARQL e o pré-cálculo dos embeddings do KG acontecem antes da
submissão. Durante os 60 minutos continuam contando a leitura do artefato,
o processamento dos PDFs, os postings de entidades, o carregamento dos modelos
e todas as respostas. Os tempos salvos dos notebooks não estimam esses custos.

Como referência de armazenamento, 8.342 vetores de 384 dimensões em float32
ocupam 12.813.312 bytes, cerca de 12,2 MiB, sem metadados. Isso é uma conta de
capacidade, não uma medição do artefato final. O ZIP do build anterior tinha
398.604.487 bytes; confirmar seu tamanho no ambiente de empacotamento e medir
novamente após acrescentar o KG.

Atualizar `src/build.sh` para incluir o módulo e somente os artefatos de
inferência. Manter notebooks, cache SPARQL, bancos intermediários e Turtle
de auditoria fora do ZIP. Preservar a checagem final de 1.000.000.000 bytes.

Adotar limites configuráveis de nós, candidatos e vizinhos, sem chamadas extras
ao OLMo. Definir metas de latência e memória a partir de um perfil inicial e
verificá-las em execução completa na H100; não assumir ganho ou conformidade
com 60 minutos com base apenas no tamanho pequeno do subgrafo.

## Primeira implementação recomendada

Começar pelo exportador validado e por aliases/menções diretas, com o KG
controlado por configuração e preservação das fontes dos chunks. Acrescentar
a expansão de um salto somente após comparar essa versão com o baseline.
O experimento deve demonstrar ganho de recuperação e respostas sustentadas,
além de caber no tempo e no ZIP, antes de ativar contexto KG e pontes.
