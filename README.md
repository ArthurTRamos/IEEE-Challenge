# IEEE CIS GPAIS Technical Challenge

Este projeto participa do desafio IEEE CIS GPAIS de perguntas e respostas
técnicas. O sistema recebe uma pergunta e procura informações em documentos
sobre dois temas: a instalação IFMIF-DONES e pesquisas em Inteligência
Artificial. Na avaliação oficial, o sistema também precisa trabalhar sem
internet, dentro do limite de tempo e usando o modelo de linguagem fornecido
pela competição.

## Como a solução funciona

Em termos simples, o sistema prepara os PDFs para busca, encontra trechos que
podem ajudar a responder cada pergunta e os envia ao modelo de linguagem como
referência. A busca combina duas formas de encontrar esses trechos:

- **Busca por significado:** procura passagens com sentido próximo ao da
  pergunta, mesmo quando usam palavras diferentes.
- **Busca por palavras:** procura termos importantes que aparecem tanto na
  pergunta quanto nos documentos.

Os resultados das duas buscas são combinados. O sistema também tenta manter
trechos próximos da mesma seção e reduzir a prioridade de capas e bibliografias.
Há uma opção experimental que usa um grafo local de conceitos da DBpedia para
orientar a busca. As respostas continuam baseadas nos trechos encontrados nos
documentos.

## Preparar o ambiente

O projeto foi organizado para Python 3.12. Na raiz do repositório, crie o
ambiente e instale as dependências do kit da competição:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
  -r starter-kit/IEEE-CIS-DSQA-Starter-Kit/requirements-participant.txt
```

Para rodar os testes locais:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Experimentar a busca com PDFs locais

Coloque os PDFs em uma pasta e indique essa pasta no arquivo
[`experiments/configs/pipeline.json`](experiments/configs/pipeline.json). Em
seguida, execute:

```bash
.venv/bin/python tools/run_retrieval.py --config experiments/configs/pipeline.json
```

O programa salva os trechos recuperados e rankings para inspeção manual. Essa
etapa ajuda a avaliar se a busca encontra evidências úteis; ela não gera as
respostas com o modelo da competição. O local e o formato dos arquivos gerados
são informados ao final da execução. Mais opções estão descritas no
[guia de experimentos](experiments/README.md).

## Criar o arquivo de submissão

O build prepara e empacota o código e os modelos de busca necessários para
funcionar sem internet. Com os modelos já disponíveis localmente, rode:

```bash
REUSE_MODELS=1 ./src/build.sh
```

O arquivo criado é `hybrid_rag_submission.zip`, na raiz do repositório. O script
verifica se o ZIP está íntegro e respeita o limite de tamanho da competição.
Para conhecer os detalhes do pacote e as limitações já verificadas, consulte
[build e validação](docs/implementations/build-and-validation.md).

## Mais informações

- [Visão técnica do projeto](docs/technical-overview.md)
- [Implementações em detalhe](docs/implementations/README.md)
- [Requisitos da competição](docs/competition-requirements.md)
- [Notebooks e dados da DBpedia](notebooks/dbpedia/README.md)
