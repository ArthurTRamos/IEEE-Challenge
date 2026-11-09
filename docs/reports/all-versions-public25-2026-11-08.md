# Denso, BM25, híbrido, mentions e graph com MiniLM — 08/11/2026

**Atualização posterior:** as tabelas deste relatório preservam os julgamentos
anteriores à revisão dos negativos. A versão corrigida e os novos testes de
pesos estão no [relatório seguinte](rrf-weights-public25-2026-11-08.md).

Execução analisada: [`all_versions_test_25quests`](../../experiments/runs/all_versions_test_25quests).

**`mentions` lidera a ordenação por documento, e o denso recupera mais documentos
nota 2. Isso ainda não escolhe o melhor contexto para a LLM.** A revisão de
casos concretos mostra que recuperar o artigo correto pode omitir justamente
a temperatura ou o argumento necessário. `graph` não apresenta vantagem
consistente sobre as opções mais simples nesta execução.

Os resultados abaixo usam os julgamentos estimados já existentes. Nenhuma nota,
ranking, configuração, prompt ou modelo foi alterado durante a análise.

## Comparabilidade e validação

- Mesmos 64 PDFs, 975 páginas, 5.093 chunks e 25 perguntas nas cinco variantes.
- MiniLM no caminho `.cache/embedding-models/minilm-baseline-256`: limite 256
  tokens, dimensão 384, execução em CPU, quatro threads e batch oito.
- Stopwords e stemming ativos; BM25 `k1=1.2`, `b=0.75`, `epsilon=0.25`.
- RRF `k=60`, profundidade 100 por canal; semântico e BM25 com peso 1.
- `mentions` acrescenta o canal KG de menções ao híbrido, com peso 0,5.
  `graph` acrescenta o canal de exploração do grafo, com peso 0,5. Não são
  comparações de KG isolado com recuperação semântica isolada.
- Chunking por seção, tamanho nominal 800 caracteres e overlap 150;
  penalizações de capas/referências ativas. **Continuidade por vizinhos e
  reconhecimento de fórmulas desativados.**
- Conferidos hashes dos PDFs, identidade dos Markdown em relação à base
  anotada, hashes dos cinco JSONs de entrada e do arquivo de julgamentos.
  O recálculo das métricas reproduziu os resultados por pergunta já salvos.

`summary.json` continua com `quality_metrics=null` porque o runner de recuperação
não incorpora os resultados do avaliador externo. Isso não indica falha: as
métricas foram calculadas e estão nos cinco arquivos `metrics-*.json`.

## Métricas documentais

nDCG usa documentos únicos ordenados pela primeira ocorrência nos chunks.
Recall estrito considera somente documentos nota 2. Os resultados são locais,
com relevância estimada pelo assistente, e não acurácia de respostas.

| Variante | nDCG@10 — 25 perguntas | nDCG@10 — 22 com evidência direta | nDCG@10 — 17 textuais | Recall estrito@10 — 22 perguntas |
| --- | ---: | ---: | ---: | ---: |
| Denso | 0,8184 | 0,7937 | 0,8362 | **0,9318** |
| BM25 | 0,8105 | 0,8090 | 0,8605 | 0,9053 |
| Híbrido | 0,8640 | 0,8455 | 0,8799 | 0,9205 |
| Mentions | **0,8825** | **0,8665** | **0,9090** | 0,9129 |
| Graph | 0,8664 | 0,8482 | 0,8836 | 0,9129 |

As questões 16, 18 e 21 não têm documento nota 2. Nas três, o nDCG pode premiar
documentos de contexto mesmo sem a fonte necessária para responder. Por isso,
o recorte de 22 perguntas é mais informativo para esta comparação. O recorte
de 17 exclui também os casos parciais, a pergunta visual e a ambiguidade IFMIF/DONES.

| Variante | Nota 2 na primeira posição — 22 perguntas | Recall estrito dentro dos primeiros 5 chunks |
| --- | ---: | ---: |
| Denso | 15/22 | 0,8485 |
| BM25 | 17/22 | 0,8068 |
| Híbrido | 19/22 | 0,8750 |
| Mentions | **20/22** | **0,8864** |
| Graph | 19/22 | 0,8712 |

`mentions` melhora nDCG@10 em quatro perguntas contra o híbrido (1, 6, 7 e 25),
piora em duas (3 e 5) e empata nas outras 19. `graph` melhora três (6, 7 e 9),
piora duas (3 e 5) e empata em 20. Empates documentais podem esconder mudanças
substanciais nos chunks: a questão 13 é um exemplo.

Nas cinco variantes, a média de documentos diferentes nos dez chunks varia
de 2,76 a 3,64. Portanto, @10 documentos frequentemente abrange todo o ranking
documental disponível e não significa que dez artigos foram recuperados.

## Diferença entre domínios

Recorte com algum documento nota 2: dez perguntas DONES e doze de IA.

| Variante | nDCG@10 DONES | Recall estrito DONES | nDCG@10 IA | Recall estrito IA |
| --- | ---: | ---: | ---: | ---: |
| Denso | 0,7346 | **0,9000** | 0,8429 | 0,9583 |
| BM25 | 0,6674 | 0,8417 | 0,9270 | 0,9583 |
| Híbrido | 0,7476 | 0,8750 | 0,9270 | 0,9583 |
| Mentions | **0,7569** | 0,8583 | **0,9578** | 0,9583 |
| Graph | 0,7537 | 0,8583 | 0,9270 | 0,9583 |

BM25 favorece a ordenação dos artigos de IA nesta amostra, mas é mais fraco no
DONES. Várias perguntas de IA citam o título do artigo ou o nome do método;
isso é uma explicação plausível para a utilidade lexical, não um efeito isolado
por este experimento. Não adotar pesos por domínio com base somente nesses
poucos exemplos.

## Auditoria dos chunks

As verificações abaixo usam leitura dos trechos e busca de passagens literais
específicas. Não constituem uma avaliação automática geral de suficiência:
outras passagens podem expressar evidência equivalente.

### Questão 13: documento perfeito, prova ausente

Todas as variantes obtêm nDCG documental 1. Os dez chunks de todas elas vêm de
AI-007. Porém, os trechos da construção e da conclusão estão em `AI-007#32–35`:

| Variante | Recupera #32, #33 ou #34? | Recupera #35, com densidade/repetição/epsilons pequenos? |
| --- | --- | --- |
| Denso | Não | Não |
| BM25 | Não | Sim, posição 3 |
| Híbrido | Não | Sim, posição 6 |
| Mentions | Não | Não |
| Graph | Não | Não |

BM25 e híbrido incluem o parágrafo que encadeia pares densos, repetição infinita
e epsilons arbitrariamente pequenos. Mesmo esses dois não recuperam toda a
construção das testemunhas. Mentions e graph removem `#35` do top 10 apesar de
manter o mesmo score documental. O denso ainda coloca a capa `#0` em segundo.

A consulta 13 tem 310 tokens e é truncada no encoder de 256. Isso é uma
limitação documentada a investigar, sem presumir que explique sozinha a falha.
O texto completo da pergunta permanece no JSON exportado para a LLM.

### Questão 7: premissa e temperatura estão em trechos diferentes

A correção da premissa está explícita em `DONES-035#66`: trap de N off-line,
com o circuito parado. A faixa de 500–600 °C está em `DONES-001#12`.

| Variante | Posição de DONES-035#66 | Posição de DONES-001#12 |
| --- | ---: | ---: |
| Denso | 1 | Ausente |
| BM25 | 2 | 5 |
| Híbrido | 1 | 8 |
| Mentions | 2 | 5 |
| Graph | 2 | 7 |

O Recall documental do denso é 1 nesta pergunta porque ele recupera os quatro
artigos nota 2; isso não garante a faixa de temperatura no contexto. O BM25
coloca em primeiro um trap de IFMIF a 600 °C de outra configuração (`DONES-034#68`),
o que também exige discriminar versões e instalações.

### Questão 3: queda de Recall não implica perda da resposta

Todas as variantes colocam `DONES-035#79` em primeiro. Ele informa meia-vida de
53,2 dias, suficiente para arredondar a 53 e calcular a constante de decaimento.
Mentions e graph perdem a segunda fonte nota 2 e caem para Recall 0,5, mas
preservam esse fato central. Portanto, maximizar Recall documental também pode
premiar redundância desnecessária para responder.

### Questões 6 e 25: revisar negativos provisórios

Na questão 6, `DONES-034#66` aparece em primeiro no híbrido, mentions e graph.
Ele contém uma tabela do HX com **49,7 kg/s**, embora o documento esteja com
nota 0 para essa pergunta. A fonte é IFMIF, e não uma confirmação do projeto
DONES; isso sugere rever como **contexto nota 1**, sem promover automaticamente
o documento a evidência direta. O denso começa com `DONES-035#47`, que contém
a tabela do projeto DONES.

Os chunks inspecionados fornecem massa por tempo, mas isso não basta para obter
vazão volumétrica sem densidade ou o nominal de 97,5 L/s. Recuperar uma tabela
relacionada não deve ser marcado automaticamente como resposta completa.

Na questão 25, `AI-025#169` e `AI-027#19` estão com nota 0, mas explicam o
contraste entre recorrência/filtro fixo e seleção dependente da entrada. São
candidatos a contexto nota 1; não substituem o experimento no artigo original
de Mamba. Isso pode penalizar de forma excessiva rankings que começam com essas
fontes secundárias. As propostas ficaram separadas dos julgamentos atuais.

### Questões 15 e 19: conteúdo certo em posições distintas

Todas as variantes recuperam a regra de janela do WinStat na questão 15.
Na questão 19, `AI-010#39` explicita `Softmax(w)` e soma um. A posição é 9 no
denso, 3 no BM25 e 5 nas três fusões. O nDCG documental é 1 nas cinco opções
e não capta a diferença de posição da evidência.

## Custo e truncamento

A execução completa registrou **51,86 s**, pico RSS de **1.260,62 MiB** e
nenhuma alocação de CUDA. Contudo, houve cache dos 64 textos e dos embeddings:
os 0,10 s de embeddings são leitura de cache, não construção do índice vetorial.
Esse tempo não estima execução fria na H100 nem inclui geração pela LLM.

Matcher e carregamento do KG custaram 0,86 s; índices de menções e grafo,
0,46 s e 0,57 s. A expansão não é o gargalo de tempo nesta execução local.

Foram truncados **921/5.093 chunks (18,08%)** e uma consulta, a questão 13.
Os chunks completos continuam no JSON para geração; o corte afeta a
representação usada na recuperação. Como parágrafos indivisíveis podem exceder
o tamanho nominal, 800 caracteres não garante entrada abaixo de 256 tokens.

## Próximo teste recomendado

1. Revisar os negativos provisórios identificados, criar uma nova versão dos
   julgamentos e recalcular **todas** as variantes com ela. Não substituir os
   resultados atuais silenciosamente.
2. Usar a recuperação de evidências concretas como critério de seleção. Manter
   híbrido e mentions como finalistas e denso como controle; não escolher
   mentions só pelo maior nDCG nem denso só pelo maior Recall documental.
3. Com os mesmos embeddings e chunks, testar peso BM25 `0,25`, `0,5` e `1`,
   mantendo semântico `1` e KG desativado. Depois comparar o melhor híbrido
   com menções de peso `0,25` e `0,5`. A comparação atual não isola o efeito
   de outros pesos: todos os canais principais usam peso 1.
4. Em rodada separada, investigar preservação da pergunta em consultas longas
   e continuidade limitada dentro da seção para casos como Q13. Conferir
   cobertura dos argumentos e ocupação do top 10 antes de ativar expansão geral.
5. Só então enviar os melhores contextos ao notebook de geração e comparar
   respostas. Nenhuma dessas métricas locais estabelece acurácia oficial.

## Artefatos da análise

Em [`analysis_codex_2026-11-08`](../../experiments/runs/all_versions_test_25quests/analysis_codex_2026-11-08):

- `cohort-metrics.json`: agregações para 25, 22, 17 e por domínio;
- `per-question.csv`: 125 linhas para comparar perguntas/variantes;
- `targeted-passage-checks.json`: localizadores dos trechos específicos conferidos;
- `annotation-review-candidates.json`: três propostas de revisão, ainda não
  aplicadas aos julgamentos.

Os rankings e as métricas originais foram preservados. Nenhum encoder, Docling
ou modelo de geração foi carregado durante esta análise.
