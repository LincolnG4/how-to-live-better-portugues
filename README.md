**Português** | [English](README.en.md) | [中文](README.zh-CN.md)

# Guia de Vida de Alto Custo-Benefício (leitura online)

Uma página HTML de arquivo único que renderiza o livro de código aberto
《高性价比人生指南》 (*Guia de Vida de Alto Custo-Benefício*), com as 34 seções e
699 dicas, em um site pesquisável. Funciona no celular, sem instalar nada.

**Leitura online:** https://lincolng4.github.io/how-to-live-better-portugues/

## Créditos

- **Livro (autor original):** [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter),
  licença Unlicense (domínio público). As dicas são ordenadas por custo-benefício:
  cada uma diz o que se gasta, o que se ganha e quão sólida é a evidência, citando
  apenas artigos de periódicos e documentos oficiais. Todo o conteúdo pertence ao autor.
- **Página de leitura original:** criada por [cdyforever](https://cdyforever.github.io/how-to-live-better/),
  que renderiza o livro como um arquivo HTML único. Este repositório parte dessa ideia
  e acrescenta a troca de idioma da interface.

Este repositório não é um fork do livro e não altera o conteúdo original.

## Estado da tradução

- A **interface** está traduzida: Português (padrão), English e 中文, escolhidos no
  menu suspenso no canto superior direito. Cada idioma é uma página própria
  (`index.html`, `en.html`, `zh.html`) e o menu leva de uma para outra.
- O **texto do livro** (as dicas, os títulos das seções e o índice) ainda está no
  original em chinês. Traduzi-lo para português e inglês é a próxima etapa.

## Recursos da página

- **Sem recursos externos:** sem CDN, sem fontes externas, sem `fetch`; funciona offline
- Cartão por dica: título, nível de evidência (A/B/C), faixa de custo-benefício, rótulos de custo
- Bloco destacado **"Linguagem simples"** (说人话), que traduz as estatísticas para o dia a dia
- Busca por palavra-chave em todo o site (com destaque), filtro "Evidência A" e filtro "Linguagem simples"
- Índice lateral com pontos coloridos por custo-benefício e rolagem sincronizada
- No celular: busca em linha própria, barra superior que encolhe ao rolar, botão de voltar ao topo
- Tema claro/escuro
- Impressão suportada

## Uso local

Não precisa de build: abra `index.html` com um duplo clique.

## Regerar a página

```bash
# precisa de um clone local do repositório do livro
git clone --depth 1 https://github.com/eternity4719/HowToLiveBetter.git /tmp/upstream

# todas as seções
python build.py all -o index.html --repo /tmp/upstream

# apenas algumas seções
python build.py 1 2 16 --repo /tmp/upstream
```

O diretório do livro também pode ser definido pela variável de ambiente `HLTB_REPO`.

Os textos da interface (nos três idiomas) ficam na tabela `STR` de `build.py`.

A contagem de dicas, a classificação A/B/C e as três faixas de custo-benefício seguem o
mesmo critério de `tools/sync-stats.ps1` e do `index.html` do repositório do livro, então o
resultado pode ser conferido item a item com os selos do original.

## Atualização automática

`.github/workflows/rebuild.yml` baixa o livro e regera a página todos os dias às 06:00
(horário de Pequim), e só faz commit se houver mudanças. Também pode ser disparado
manualmente na aba Actions.

## Licença

O conteúdo do livro é Unlicense (domínio público). O script de build deste repositório
também é publicado sem reserva de direitos.
