# Ampliação da base pública — 08/11/2026

[Dados e arquivos](../../data/local_eval/README.md) · [Como foi implementado](../implementations/public-evaluation-dataset.md)

**Atualização posterior:** o usuário revisou três negativos, acrescentando
contexto nota 1 para Q6/DONES-034 e Q25/AI-025/AI-027. A base atual tem 97
passagens, 32 notas 1 e 38 notas 2. O [relatório dos testes de pesos](rrf-weights-public25-2026-11-08.md)
registra os efeitos dessa revisão. As contagens abaixo descrevem a curadoria inicial.

A avaliação foi ampliada para as **25 perguntas públicas originais**, preservando
seus enunciados, IDs e respostas. Foram acrescentados seis PDFs aos 58 anteriores:
agora são **64 documentos, 975 páginas e 1.600 pares pergunta–documento anotados**.
Os arquivos anteriores de cinco perguntas e seus rankings foram preservados.

As notas são estimativas do assistente: 38 pares receberam **2 (relevante)**,
29 receberam **1 (possivelmente relevante)** e 1.533 receberam **0 (nenhum apoio
identificado na triagem)**. Os negativos são provisórios. Há **94 passagens**
de apoio/contexto, com offsets e hashes das fontes. As evidências não são chunks
fixos de um modelo; podem ser usadas para analisar diferentes chunkings depois.

Não foram executadas recuperação nova, geração por LLM ou submissão nesta etapa.
As contagens abaixo descrevem a curadoria, não resultados de desempenho.

## Fontes acrescentadas

Os PDFs estão em `data/download_pdfs/public_qa_expansion/`. URLs, tamanho, páginas,
hashes e verificação dos downloads estão no
[manifesto de download](../../data/download_pdfs/public_qa_expansion/download-manifest.json).
O [manifesto editável de fontes](../../tools/public_qa_sources.json) registra o
motivo da seleção. Algumas fontes são de física geral e contexto metodológico,
não artigos específicos do DONES ou do método citado na pergunta.

| ID | Fonte primária | Páginas | Contribuição |
| --- | --- | ---: | --- |
| DONES-031 | Y. Qiu et al., [Status of DONES neutronics, source terms analyses and radiation protections](https://doi.org/10.1088/1741-4326/addeda), Nuclear Fusion 65 (2025) 122013, CC BY 4.0 | 38 | Meia-vida de Be-7, transporte/ativação, fonte no lítio e parâmetro de 2% |
| DONES-032 | G. Kube, C. Behrens e W. Lauth, [Resolution Studies of Inorganic Scintillation Screens…](https://proceedings.jacow.org/IPAC10/papers/mopd088.pdf), IPAC 2010 MOPD088 | 3 | Deposição de energia e produção de pares elétron-lacuna no cintilador |
| DONES-033 | Eva Barbara Holzer, [Beam Instrumentation](https://indico.cern.ch/event/279729/contributions/1626379/), CERN, 2014 | 24 | OTR em interface dielétrica e perturbação por diagnósticos invasivos |
| DONES-034 | J. Knaster et al., [The accomplishment of the Engineering Design Activities of IFMIF/EVEDA…](https://documenta.ciemat.es/server/api/core/bitstreams/7c7b4c47-ac72-44a4-bbc0-044ca4783cd5/content), manuscrito aceito, 2015 | 43 | Dimensões usadas na referência da questão 9, com ressalva IFMIF versus DONES |
| DONES-035 | F.S. Nitti et al., [The lithium systems of the IFMIF-DONES facility](https://documenta.ciemat.es/items/036b674a-afab-464d-b3c6-795b004f02e8), Nuclear Fusion 65 (2025) 122004, CC BY 4.0 | 21 | Vazões do circuito e ICS, composição dos ramos e geração de Be-7 |
| AI-029 | A. Benavoli et al., [Time for a Change: a Tutorial for Comparing Multiple Classifiers Through Bayesian Analysis](https://jmlr.org/papers/v18/16-305.html), JMLR 18(77), 2017, CC BY 4.0 | 36 | Posteriores e equivalência prática; apoio metodológico, sem substituir ThinkMore |

Para os materiais sem licença explícita registrada, o manifesto remete aos
direitos da publicação original. Disponibilidade pública não é tratada como
autorização genérica de redistribuição dos PDFs.

## Cobertura das perguntas

“Textual” significa apoio estimado aos aspectos centrais da pergunta. Não
significa que a LLM responderá corretamente nem que cada detalhe da resposta
pública foi confirmado. O arquivo [coverage.csv](../../data/local_eval/coverage.csv)
inclui também fontes nota 1 e ressalvas por pergunta.

| ID | Tema resumido | Documentos nota 2 | Situação |
| ---: | --- | --- | --- |
| 1 | Cintilação versus OTR | DONES-032, 033 | Textual |
| 2 | Diagnóstico destrutivo/interceptivo | DONES-017, 018, 019, 033 | Textual |
| 3 | Constante de decaimento de Be-7 | DONES-031, 035 | Textual; exige cálculo |
| 4 | Be-7 deixa de dominar no HX | DONES-027 | Depende da figura 8, página PDF 4 |
| 5 | Inventários de Be-7 e trítio | DONES-008, 031, 035 | Parcial; faltam detalhes do cenário numérico |
| 6 | Vazão no trocador primário | DONES-001, 006, 035 | Textual; nominal ~97,5 L/s |
| 7 | Trap de nitrogênio | DONES-001, 013, 029, 035 | Textual; corrigir premissa on-line |
| 8 | Fração de fluxo da ICS | DONES-031, 035 | Textual; atenção à versão antiga |
| 9 | Volume do prédio | DONES-034 | Ressalva: fonte e referência são do IFMIF |
| 10 | Acesso humano/manutenção remota | DONES-013 | Parcial; classificação de dose não basta para regra universal |
| 11 | RQ-Kmeans em OneSearch | AI-001 | Textual |
| 12 | Imutabilidade e baselines ONB-MACF | AI-004, 006 | Parcial; falta auditar configurações de todos os baselines |
| 13 | Por que Y é lush | AI-007 | Textual; construção e limite exigem vários trechos |
| 14 | Métricas limitadas no REVEL | AI-008 | Textual |
| 15 | Janela do WinStat para L=512 | AI-010 | Textual; exige cálculo |
| 16 | Ativação relativa e classificação FCM | — | Fonte primária não localizada; AI-011 é contexto |
| 17 | Covering com pesos conhecidos | AI-011 | Textual |
| 18 | Fairness by Brute Force | — | Artigo exato não localizado |
| 19 | Normalização dos pesos WinStatFlex | AI-010 | Textual; Softmax explícita |
| 20 | Gerador R no ZeroDiff | AI-014 | Textual |
| 21 | Comparação bayesiana de ThinkMore | — | Artigo exato não localizado; tutorial é contexto |
| 22 | Augmentation isolada no SimCLR | AI-016 | Textual |
| 23 | Resiliência (alpha,f) e comparadores | AI-018, 019, 020 | Textual; definição e comparadores em fontes distintas |
| 24 | Active learning em GPAIS aberto | AI-021 | Textual |
| 25 | LTI e Selective Copying no Mamba | AI-022 | Textual |

São **22 perguntas com alguma evidência direta**, das quais **17** têm cobertura
textual central estimada mais completa. Três são parciais, uma exige figura e
uma apresenta ambiguidade de escopo. As outras três permanecem com fonte ausente.
Todos os IDs continuam no conjunto; não foram substituídos para melhorar scores.

## Lacunas e cuidados para os próximos experimentos

- **Q16:** a fonte AI-011 trata de espaços viáveis e declara que classificadores
  foram excluídos do experimento. Buscas por “relative activation values”,
  “qrFCM” e termos de encolhimento/classificação não localizaram a fonte com
  os F1 0,74/0,54/0,69. Não promover esse contexto a evidência direta.
- **Q18:** buscas pelo título “Fairness by Brute Force”, pelo subtítulo e pelo
  protocolo de insatisfação não localizaram o trabalho. AI-012 tem outras
  profissões e outro protocolo; não valida os percentuais e iterações do Grok.
- **Q21:** buscas por ThinkMore, ThinkMoreReeval e a descrição neuro-simbólica
  do xadrez não localizaram o trabalho. AI-029 sustenta a escolha metodológica,
  mas não os valores epsilon/delta nem os resultados de ThinkMore. Resultados
  binários também admitem testes frequentistas; não transformar a resposta
  pública em uma afirmação geral de impossibilidade desses testes.
- **Q5:** o artigo *Nuclear assessment of the IFMIF-DONES lithium target system*
  foi identificado ([página da publicação](https://www.sciencedirect.com/science/article/abs/pii/S0920379620302064)),
  mas seu PDF completo não foi incorporado. É candidato para completar os
  números da referência. Os inventários e taxas do artigo de 2025 representam
  outro cenário e não devem ser combinados sem conferir hipóteses e unidades.
- **Q8:** DONES-001 contém 0,65 L/s (~0,6%), enquanto DONES-035 contém 2,015 L/s
  e ~2%. Essa é uma oportunidade de avaliar discriminação entre versões.
- **Q9:** as dimensões coincidem com a resposta esperada, mas a instalação é
  IFMIF, não uma confirmação do prédio DONES. Avaliar separadamente.
- **Q4:** recuperar o documento correto não resolve a ausência da curva nos
  chunks textuais. A evidência visual foi localizada, sem alterar o extrator.

Para métricas futuras, mantenha os mesmos 64 documentos e a mesma versão dos
julgamentos entre encoders. Relate todas as perguntas e o subconjunto textual
separadamente; o Recall estrito das três perguntas sem nota 2 fica indefinido.
As 25 perguntas são desenvolvimento público e já orientaram a seleção das fontes;
os resultados locais não são estimativa imparcial da acurácia no corpus oculto.

## Validação realizada

O gerador verificou hashes dos 64 PDFs/Markdown, os intervalos e as âncoras das
94 passagens, a preservação das perguntas oficiais e a matriz completa no
carregador de métricas existente. Passaram os 12 testes de integridade da base
e de cálculo das métricas. Nenhum modelo de geração foi carregado.
