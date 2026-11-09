# Refatoração, validação e dispositivos — 08/11/2026

`src/main.py` foi reduzido à coordenação da API oficial. Configuração,
documentos, indexação, recuperação, contexto e geração têm módulos próprios.
O teste de equivalência confirmou **125 rankings e os cinco JSONs para o
notebook idênticos** entre o código anterior e o novo, sobre os mesmos 64 PDFs,
5.093 chunks e 25 perguntas, em CPU.

O [guia prático de testes e resultados](../testing-guide.md) reúne os comandos.
A [documentação do pipeline](../implementations/rag-pipeline.md) descreve os
módulos, configurações, caches e fluxo atual.

## Alterações implementadas

- `settings.py` define `PipelineConfig`, com validação de variantes, pesos,
  dispositivos, tamanhos e parâmetros; `src/pipeline.json` configura a submissão.
- `documents.py` mantém a conversão Docling offline; `indexing.py` constrói
  apenas os canais habilitados e devolve o encoder à CPU antes da LLM por padrão.
- `retrieval_utils.py` centraliza variantes/pesos e RRF; `retrieval.py` compartilha
  rankings e seleção final com os experimentos.
- `context.py` empacota evidências e fontes; `generation.py` carrega o modelo
  de resposta somente quando solicitado pela interface oficial.
- Foram removidos o tokenizador lexical duplicado, o preprocessor global
  implícito, a configuração de ranking fixa em `main.py` e as dependências dos
  tools em funções privadas do ponto de entrada.
- Os índices e modelos têm caches separados. A configuração completa e os
  parâmetros do grafo participam da identidade do índice.
- O build inclui os novos módulos e o JSON. Valida variantes que exigem KG,
  caminhos de assets empacotados e a exclusão atual dos pesos de fórmulas.

BM25 pode ser desligado pela variante; testes apenas lexicais não carregam o
encoder. Peso zero desativa efetivamente o respectivo canal. Continuidade,
penalizações, fórmulas, stopwords e stemming têm controles explícitos. A API
`answer(question, corpus_dir, model_id)` e os defaults de recuperação da
submissão permanecem híbrido 1/1, RRF 60 e top 10.

O modelo em `src/embed_model` não foi trocado. O novo preset local
`experiments/configs/public-25-minilm.json` seleciona o MiniLM preservado no
cache e as cinco variantes. As configurações locais passam a aceitar
`embedding_device=auto`; o processamento de documentos fica em CPU por padrão,
com opção separada `docling_device`.

## Equivalência e cache

As pastas históricas de experimentos haviam sido removidas. A validação usou
o código salvo antes da refatoração, o corpus congelado em `data/local_eval`
e os caches disponíveis. As cópias do código anterior foram preservadas na
[pasta da validação](../../experiments/runs/refactor-validation-2026-11-08).

A mudança de nome/localização da função do conversor altera a chave de cache
baseada no código-fonte. Antes da reprodução completa, verificou-se a
equivalência da AST da função, exceto seu nome e a indicação do comando em
uma mensagem de erro. Os 64 PDFs, Markdown e entradas antigas do cache foram
conferidos; as entradas foram copiadas para as novas chaves, preservando as antigas.

| Verificação | Resultado |
| --- | --- |
| PDFs e textos na comparação | 64, todos reutilizados do cache |
| Chunks | 5.093, IDs e hashes idênticos |
| Perguntas × variantes | 25 × 5 = 125 rankings idênticos, incluindo scores |
| JSONs para o notebook | Idênticos nas cinco variantes |
| Vetores de documentos | Reutilizados do cache nas duas reproduções |
| Testes antes da refatoração | 115 passaram |
| Testes após a refatoração | 122 passaram |
| Sintaxe do build | `bash -n src/build.sh` passou |
| Importação do pacote plano | Testada com a lista real de arquivos do build, sem assets/modelos |

Os nDCG@10 nas 25 perguntas também permaneceram: denso 0,8313; BM25 0,8064;
híbrido 0,8769; mentions 0,8865; graph 0,8780. São métricas documentais com as
notas estimadas corrigidas, não acurácia da LLM.

O corpus congelado, os rótulos de contexto e as regras de empacotamento foram
mantidos. A geração foi verificada com modelos simulados; não se executou
OLMo nem se mediu qualidade de respostas ou tempo completo na H100. A comparação
de rankings em CPU não promete identidade numérica entre CPU e CUDA.

## GPU: o que foi confirmado

O diagnóstico iniciado antes da continuação confirmou:

| Contexto | Resultado |
| --- | --- |
| Dentro do sandbox | CUDA indisponível; NVML informou bloqueio de acesso |
| Fora do sandbox | RTX 4050 Laptop GPU, 6 GiB, PyTorch 2.8.0+cu128 |
| Operação pequena de tensor | Executada em `cuda:0`, com resultado esperado |

Isso confirma que a GPU funciona no ambiente do usuário, sem ser um benchmark
de throughput. Não foram iniciados diagnósticos adicionais de GPU após a
solicitação de seguir com a refatoração.

Os testes anteriores estavam explicitamente em CPU nos JSONs e reutilizavam
embeddings em cache. Além disso, BM25, KG, RRF e as operações NumPy de similaridade
continuam em CPU. Portanto, pouco uso de GPU nesse cenário é esperado.

Agora `auto` seleciona CUDA quando acessível ao processo, com alternativa CPU.
`cuda` exige acesso e falha com mensagem clara se indisponível; não muda
silenciosamente para CPU. Os logs e `config.json` mostram dispositivo pedido,
efetivo e canais executados. Na submissão, o encoder volta à CPU antes da LLM;
no runner local, pode permanecer na GPU para consultas. Caches quentes evitam
nova codificação dos documentos em qualquer dos casos.

O utilitário opcional `tools/check_device.py` mostra o ambiente de um terminal;
`--test-cuda` acrescenta uma operação pequena. Ele não carrega a LLM.

## Limites e artefatos

Não foram acrescentadas dependências nem reconstruído o ZIP anterior. O custo
oficial de uma hora e a qualidade das respostas continuam exigindo avaliação
completa. Configuração e arquivos Python novos acrescentam apenas código ao
próximo build; não foram introduzidos pesos de modelos adicionais.

Na [pasta da validação](../../experiments/runs/refactor-validation-2026-11-08):

- `equivalence.json`: identidade dos rankings, exportações e métricas;
- `cache-migration.json`: verificação e migração das 64 entradas de texto;
- `legacy-replay/` e `refactored/`: reproduções completas, configurações e logs;
- `refactored-final/`: nova conferência após os ajustes finais; os hashes do
  código registrado e os cinco JSONs foram verificados contra os arquivos atuais;
- `metrics-*.json`: métricas recalculadas do código refatorado;
- `gpu-diagnostic.json`: observações do diagnóstico já concluído;
- `legacy-main.py.txt` e `legacy-runner.py.txt`: código anterior usado na reprodução.

Os relatórios históricos foram preservados. A configuração dos novos testes
e os comandos de avaliação estão no [guia prático](../testing-guide.md).
