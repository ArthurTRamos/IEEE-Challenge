# Corpus piloto IFMIF-DONES: 30 artigos identificados

Curadoria inicial baseada no `corpus-search-guide.md`, com URLs provenientes de páginas de periódicos/repositórios e de proceedings conferidos via pesquisa web em 7 de novembro de 2026.

**Não são julgamentos automáticos de relevância.** `selection` representa o papel sugerido na composição do piloto: `central` (específico à instalação), `ampliacao` (documentação temática) ou `contraste` (IFMIF-EVEDA/LIPAc). `relevance_judgment=unjudged` é deliberado: cada par pergunta/documento precisa ser inspecionado. Mesmo um artigo de outra instalação pode trazer uma comparação válida.

## Arquivos

- `ifmif_dones_30_artigos.csv`: catálogo, origem, temas, grupos de perguntas, PDFs e metadados.
- `ifmif_dones_30_artigos.jsonl`: mesmo catálogo em JSONL.
- `download_corpus.py`: downloader local dos 30 URLs, com relatório e validação de cabeçalho PDF.

## Uso local

Requer Python 3.10+ e `pip install requests`.

```bash
python download_corpus.py --manifest ifmif_dones_30_artigos.csv --outdir corpus_ifmif_dones
```

Uma vez concluído, confira `corpus_ifmif_dones/download_log.csv` e eventuais falhas. A disponibilidade dos servidores pode mudar, e **não foi executado download completo dos 30 PDFs neste ambiente**. Cada caminho foi selecionado de páginas/repositórios identificados por pesquisa; disponibilidade HTTP e integridade precisam ser testadas na execução local.

## Organização experimental recomendada

- `DONES-001` a `DONES-030` são identificadores estáveis.
- Preserve o PDF original, URL, ano e grupo de origem; o texto extraído pode ir para uma pasta derivada.
- Compare primeiro retrieval e geração sem os 3 documentos de contraste (`025`, `026`, `030`) e depois com eles.
- Para julgar documentos/chunks: anote por pergunta `supporting`, `partial`, `hard_negative`, `unjudged`, com trecho e página. Não trate documentos não examinados como negativos.
- Use *leave-one-topic-out* ou holdout de documentos/perguntas para impedir vazamento na otimização.
- Faça deduplicação por SHA-256. Artigos sobre etapas diferentes do projeto podem apresentar números de projeto revisados: registre contexto e data.

## Licenciamento

Esta entrega contém apenas o catálogo e código de download, não uma redistribuição dos artigos. Alguns PDFs de preprints EUROfusion têm avisos específicos de circulação/reprodução. Consulte os termos de cada fonte e limite o uso ao que é permitido. Trabalhos da JACoW geralmente têm licenças Creative Commons com exigência de atribuição, dependendo do ano.
