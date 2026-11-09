# Candidata de submissão e próximos passos — 08/11/2026

**Recomendação para hoje: híbrido sem expansão automática de vizinhos**, mantendo
chunking por seção, penalizações, MiniLM, BM25 com stopwords/stemming e o prompt
atual. A candidata usa os dez melhores chunks após fusão e penalizações. KG e
reconhecimento de fórmulas continuam desativados.

Essa recomendação decorre de uma ablação local realizada durante a análise.
Ela ainda exige aplicar essa seleção ao código de submissão e reconstruir o
ZIP: o arquivo atualmente disponível contém a expansão de vizinhos. Nenhuma
alteração foi aplicada ao código de inferência nesta análise.

## Evidência disponível

O [registro de submissões](submission-results.md) contém scores informados de
57 para semântico, 47 para o híbrido inicial, 57 com menções/aliases do KG e 53
com expansão do grafo. Esses históricos não isolam todas as diferenças entre
versões; não demonstram superioridade do BM25 ou do KG.

Nos [resultados locais atuais](covered-five-2026-11-08.md), a continuidade
preenche parte do top 10 com vizinhos, exclui a conclusão da prova da questão 13
e reinsere uma capa na questão 23. Para conferir o efeito dessa etapa, foram
executadas duas variantes adicionais, com os mesmos PDFs, perguntas, modelo,
chunking, pré-processamento lexical e penalizações:

```bash
CUDA_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -u tools/run_retrieval.py \
  --config experiments/configs/pipeline.json \
  --no-continuity --variants dense hybrid \
  --output experiments/runs/submission-assessment-2026-11-08/no-continuity
```

A execução levou **53,91 s com cache**, em CPU, sem OLMo. Foram usados os mesmos
58 PDFs, 4.378 chunks e perguntas 7, 2, 5, 13 e 23. Os hashes de modelo e
perguntas, extração, pesos do híbrido e configurações foram conferidos. Para o
híbrido, a diferença é a expansão; `dense` fornece um controle adicional sem BM25.

Os [julgamentos de 08/11](../../experiments/judgments/selected-five-2026-11-08.json)
foram mantidos. Não houve nova seleção de perguntas ou mudança de notas para
favorecer as variantes.

| Variante | nDCG@10 | Recall@10, notas ≥1 | Recall@10, nota 2 |
| --- | ---: | ---: | ---: |
| Híbrido atual, com expansão | 0,6744 | 0,5267 | 0,6000 |
| Híbrido sem expansão | **0,8220** | **0,6967** | **0,9333** |
| Semântico sem expansão | 0,9070 | 0,8200 | 1,0000 |

São médias por **documento**, sobre cinco perguntas e notas estimadas, não
acurácia de respostas. As notas altas do semântico ilustram a limitação da
unidade de avaliação: é possível recuperar o artigo correto com trechos que
não respondem à pergunta.

## Por que escolher o híbrido sem expansão

| Questão | Evidência observada no híbrido sem expansão |
| --- | --- |
| 7 | Recupera `DONES-029#40`, que declara o trap off-line, e `DONES-001#12`, com 500–600 °C. Na seleção semântica, essas duas passagens estão ausentes. |
| 2 | Mantém `DONES-017#18`, que explica a interação com a grade e a perda de energia do feixe, e `DONES-019#9`, sobre restrições e comissionamento. |
| 5 | Inclui DONES-008, mas seu chunk `#46` é uma conclusão geral. A maior cobertura de documentos ainda não fornece o cálculo completo de inventários. |
| 13 | Recupera `AI-007#35` em sexto, com pares densos repetidos e epsilons arbitrariamente pequenos. Esse trecho desaparecia com a expansão. A sequência anterior `#32–34` continua ausente. |
| 23 | Mantém a definição em `AI-018#24` e recupera a comparação de formalizações em `AI-020#18`. O controle semântico não inclui a definição `#24`. |

O melhor score documental do semântico não basta para escolhê-lo para hoje.
O híbrido sem expansão tem evidências textuais mais úteis em perguntas decisivas
e permite testar uma alteração pequena em relação ao híbrido atual. Isso não
garante ganho com o OLMo 32B: a geração oficial ainda precisa ser medida.

## Diagnóstico adicional: truncamento da pergunta

O tokenizador local do MiniLM registra limite de **256 tokens**. A pergunta 13
tem **310 tokens**, incluindo tokens especiais. Sua frase final — “Why can we
conclude that $Y$ is lush?” — fica depois do corte. O canal BM25 recebe a pergunta
completa, mas a representação semântica perde essa parte da solicitação.

Também há **759 de 4.378 chunks (17,3%)** truncados na entrada do encoder. As flags
salvas pelo runner foram conferidas contra o limite de 256. O texto integral
continua disponível no JSON de geração. Esses fatos justificam investigar o
truncamento, sem afirmar que ele sozinho explica os erros.

O [diagnóstico de tokens](../../experiments/runs/submission-assessment-2026-11-08/query-token-audit.json)
foi feito com o tokenizador local e os registros existentes, sem carregar o modelo
de respostas.

## Ordem recomendada para as melhorias

1. **Medir cobertura das passagens necessárias.** Anotar trechos de referência
   por documento e posição/seção, além dos rótulos por documento. Acompanhar se
   entram nos candidatos, sobrevivem à fusão e chegam ao contexto. Ampliar a base
   de perguntas e reservar casos que não sejam usados para ajustar parâmetros.
2. **Redesenhar a expansão.** Preservar candidatos relevantes antes de ocupar o
   orçamento com vizinhos; testar um orçamento separado para expansão, aplicar
   as restrições de capas/referências aos vizinhos e unir sobreposições. Não impor
   um limite rígido pequeno por documento: uma prova pode exigir vários trechos
   do mesmo artigo. A expansão deve demonstrar ganho sobre a versão sem vizinhos.
3. **Corrigir o tratamento de perguntas e chunks longos.** Garantir que a
   solicitação final não seja descartada pelo encoder. Comparar segmentação por
   tokens e alternativas compatíveis com entradas maiores; reconstruir os
   embeddings quando mudar o texto ou limite efetivo, com caches distintos.
4. **Fazer ablações controladas de canais e pesos.** Comparar semântico, híbrido
   e pesos menores de BM25 usando as mesmas evidências anotadas. Evitar uma grade
   extensa otimizada nas mesmas cinco perguntas. O histórico de 57 versus 47
   torna essa comparação útil, mas não resolve qual componente causou a diferença.
5. **Testar reranking e outro embedding em experimentos separados.** Um reranker
   pequeno é justificável quando a evidência existe nos candidatos, mas perde a
   seleção final. Medir primeiro em 30–50 candidatos por pergunta. Comparar outro
   encoder depois de estabelecer métricas de passagem; liberar os modelos
   auxiliares antes do OLMo e medir memória, tempo e tamanho real do pacote.

O KG e o reconhecimento global de fórmulas ficam em prioridade menor por agora.
Não há ganho consistente observado com o KG; a execução anterior com fórmulas
ultrapassou o tempo, embora não existam logs suficientes aqui para atribuir toda
a demora a uma única etapa. Extração seletiva de fórmulas pode ser estudada
depois, com instrumentação própria. O prompt atual deve ser mantido neste teste
para que a comparação observe a mudança de seleção.

## Candidata e limites operacionais

A candidata de hoje deve preservar MiniLM, BM25 `k1=1.2`, `b=0.75`, stopwords e
stemming ativos, fusão RRF com pesos iguais, chunking por seção, penalizações,
prompt e orçamentos de contexto/saída. Deve selecionar **top 10 após a fusão e
penalizações, sem chamar a expansão de vizinhos**. Apenas retirar a chamada de
expansão sem limitar os candidatos a dez mudaria também o orçamento de chunks.

O ZIP atual tem **398.602.705 bytes**; seus seis módulos de inferência coincidem
com o código atual. Ele contém os dois formatos de layout e não contém
CodeFormulaV2. A flag `--no-continuity` aplicada ao runner não altera esse ZIP;
é necessário implementar a seleção correspondente em `src/main.py` e reconstruir
o pacote para enviar a candidata recomendada.

As [regras oficiais, conferidas em 08/11](https://cis.taskforce.ieee.org/gpais/tc-domain-qa-llms/join-the-challenge/)
mantêm uma submissão por dia, pacote de até 1 GB, execução offline e limite de
uma hora para todo o processamento na H100. Os 54 segundos com cache não estimam
o custo oficial. A referência local sem cache foi aproximadamente 13 minutos
apenas para extração e recuperação, sem geração OLMo.

Guardar hash e configuração do ZIP enviado, score, tempo total e logs. A
[avaliação pública](https://cis.taskforce.ieee.org/gpais/tc-domain-qa-llms/evaluation/)
usa metade do benchmark e acurácia balanceada por domínio; cinco perguntas
locais não bastam para prever esse resultado.

## Artefatos da análise

- [JSON do híbrido sem expansão para o notebook](../../experiments/runs/submission-assessment-2026-11-08/no-continuity/llm_inputs/hybrid.json).
- [JSON do controle semântico](../../experiments/runs/submission-assessment-2026-11-08/no-continuity/llm_inputs/dense.json).
- [Métricas do híbrido](../../experiments/runs/submission-assessment-2026-11-08/hybrid-no-continuity-metrics.json).
- [Métricas do semântico](../../experiments/runs/submission-assessment-2026-11-08/dense-no-continuity-metrics.json).
- [Revisão dos rankings](../../experiments/runs/submission-assessment-2026-11-08/no-continuity/review.md).
