# IEEE-Challenge

Sistema de perguntas e respostas para o IEEE CIS GPAIS Technical Challenge,
com recuperação BM25, busca semântica e exploração de um KG local da DBpedia.

- [Visão técnica e fluxo do projeto](docs/technical-overview.md)
- [Detalhes das implementações](docs/implementations/README.md)
- [Requisitos da competição](docs/competition-requirements.md)
- [Notebooks da DBpedia](notebooks/dbpedia/README.md)

Com o ambiente `.venv` preparado:

```bash
.venv/bin/python tools/prepare_kg.py
.venv/bin/python -m unittest discover -s tests -v
source .venv/bin/activate
REUSE_MODELS=1 ./src/build.sh
```

O modo padrão de recuperação é `KG_MODE=graph`. Os modos `mentions` e `off`
permitem comparar o efeito da exploração. Consulte os detalhes de
[build e validação](docs/implementations/build-and-validation.md) antes de
interpretar os diagnósticos como resultados da avaliação.
