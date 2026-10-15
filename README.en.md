[Português](README.md) | **English** | [中文](README.zh-CN.md)

# The High Value-for-Money Life Guide (online reader)

A single-file HTML page that renders the open-source book
《高性价比人生指南》 (*The High Value-for-Money Life Guide*), with all 34 sections and
699 tips, as a searchable website. It works on a phone with nothing to install.

**Read online:** https://lincolng4.github.io/how-to-live-better-portugues/

## Credits

- **Book (original author):** [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter),
  released under the Unlicense (public domain). Tips are ranked by value for money:
  each one states what it costs, what it gives back and how strong the evidence is,
  citing only journal papers and official documents. All content belongs to the author.
- **Original reading page:** created by [cdyforever](https://cdyforever.github.io/how-to-live-better/),
  which renders the book as a single HTML file. This repository builds on that idea
  and adds interface language switching.

This repository is not a fork of the book and does not change the original content.

## Translation status

- The **interface** is translated: Português (default), English and 中文, chosen from the
  dropdown in the top right corner. Each language is its own page
  (`index.html`, `en.html`, `zh.html`) and the dropdown links between them.
- The **book text** is being translated section by section. So far only **section 1**
  ("Don't die early", 48 tips) is in Portuguese; the rest is still the original Chinese,
  and the page footer shows how many tips are already translated. The translation is
  machine-generated (AI) and may contain errors: check the original, especially for
  health topics. The English translation has not started yet.

## Page features

- **No external resources:** no CDN, no external fonts, no `fetch`; works offline
- One card per tip: title, evidence grade (A/B/C), value-for-money tier, cost tags
- A highlighted **"Plain talk"** block (说人话) that turns statistics into everyday language
- Site-wide keyword search (with highlighting), "Evidence A" filter and "Plain talk" filter
- Side table of contents with value-for-money color dots and scroll sync
- On mobile: search on its own row, top bar that collapses on scroll, back-to-top button
- Light/dark theme
- Print support

## Local use

No build needed: double-click `index.html`.

## Regenerating the page

```bash
# needs a local clone of the book repository
git clone --depth 1 https://github.com/eternity4719/HowToLiveBetter.git /tmp/upstream

# all sections
python build.py all -o index.html --repo /tmp/upstream

# only some sections
python build.py 1 2 16 --repo /tmp/upstream
```

The book directory can also be set with the `HLTB_REPO` environment variable.

The interface strings (in all three languages) live in the `STR` table in `build.py`.

Tip counts, A/B/C grading and the three value-for-money tiers follow the same rules as
`tools/sync-stats.ps1` and `index.html` in the book repository, so the output can be
checked item by item against the original badges.

## Translating the content

Translations live in `translations/<language>/NN.json` (for example `translations/pt/01.json`),
one file per section. Each item keeps the original Chinese text (`src`) next to its
translation (`tr`), so review is side by side. If the upstream book changes an item, the
original text no longer matches, the old translation is not shown, and the page falls
back to Chinese until the item is translated again.

```bash
# items in section 2 that still have no translation (the original text is pre-filled)
python build.py 2 --todo pt --repo /tmp/upstream

# check the translation against the original: numbers, links, missing fields, changed source
python build.py 1 --check pt --repo /tmp/upstream
```

`--check` only warns and never changes anything. "Extra or missing numbers" warnings are
not always errors (for example, "四成" becomes "40%"), but each one is worth a look.

## Automatic updates

`.github/workflows/rebuild.yml` pulls the book and regenerates the page every day at
06:00 (Beijing time), committing only when something changed. It can also be triggered
manually from the Actions tab.

## License

The book content is Unlicense (public domain). The build script in this repository is
likewise released with no rights reserved.
