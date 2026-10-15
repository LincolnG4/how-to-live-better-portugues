# -*- coding: utf-8 -*-
"""把《高性价比人生指南》指定的节，渲染成一个自包含的单文件 HTML 阅读页。

用法：
    python build.py                      # 默认第 1、2、16 节
    python build.py 1 2 16 3             # 指定任意节号（按给定顺序渲染）
    python build.py all                  # 全部节（用于线上站点）
    python build.py all -o index.html    # 指定输出文件名
    python build.py all --repo /path/to/HowToLiveBetter

源目录也可用环境变量 HLTB_REPO 覆盖（供 GitHub Actions 使用，优先级低于 --repo）。
产物默认与脚本同目录，单个 .html，无任何外部依赖，双击即可打开、可离线读。

数字与标签的口径完全照抄仓库 tools/sync-stats.ps1 与 index.html 的 COST_W / e.ratio：
仓库改了那两行，这里也要同步改，否则性价比档会和官方检索页对不上。
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import textwrap
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent


def parse_args():
    ap = argparse.ArgumentParser(description="生成《高性价比人生指南》单文件阅读页")
    ap.add_argument("sections", nargs="*", help="节号；或 all 表示全部节")
    ap.add_argument("-o", "--out", default=None, help="输出文件名（默认按节号自动命名）")
    ap.add_argument("--repo", default=None, help="上游仓库目录（默认 D:\\Agent\\HowToLiveBetter）")
    ap.add_argument("--check", metavar="LANG", default=None,
                    help="对照原文检查所给节的 LANG 译文（数字、链接、字段、原文是否已变），只提示不改动，不生成页面")
    ap.add_argument("--todo", metavar="LANG", default=None,
                    help="只打印某一节（须只给一个节号）里还没有 LANG 译文的条目骨架（JSON），不生成页面")
    return ap.parse_args()


ARGS = parse_args()
REPO = Path(ARGS.repo or os.environ.get("HLTB_REPO") or r"D:\Agent\HowToLiveBetter")

UPSTREAM = "https://github.com/eternity4719/HowToLiveBetter"

# 正文译文：translations/<lang>/NN.json，见 load_translations。zh 是原文，没有译文目录。
TRANSLATIONS_DIR = HERE / "translations"
SOURCE_LANG = "zh"
TRANSLATABLE = ("说人话", "成本", "收益", "备注")  # 条目里要翻译的字段（另加标题）；来源是文献，不翻
# 目录里条目标题的最大字符数：中文一个字信息量大，拉丁文字的标题天然长得多
TOC_TITLE_MAX_CJK = 34
TOC_TITLE_MAX_LATIN = 60


def avail_sections():
    """扫描 book/ 目录，得到实际存在的节号。"""
    return sorted(int(p.name[:2]) for p in REPO.glob("book/[0-9][0-9]-*.md"))


ALL = avail_sections()
if not ALL:
    raise SystemExit("在 %s 下找不到 book/NN-*.md，请用 --repo 指定正确的仓库目录" % REPO)

if ARGS.sections:
    if any(a.lower() == "all" for a in ARGS.sections):
        SECTIONS = ALL
    else:
        SECTIONS = [int(a) for a in ARGS.sections]
else:
    SECTIONS = [n for n in (1, 2, 16) if n in ALL]

SCOPE = ("全书 %d 节" % len(ALL)) if SECTIONS == ALL else ("第 %s 节" % "、".join(str(n) for n in SECTIONS))
# 界面文案里的范围：key 决定句式（i18n 表里的 scope.all / scope.some），arg 填进 {0}
SCOPE_KEY, SCOPE_ARG = ("all", len(ALL)) if SECTIONS == ALL else ("some", ", ".join(str(n) for n in SECTIONS))

# 界面语言。顺序即下拉顺序，第一个是默认语言；zh 是原文，缺翻译时回退到它。
LANGS = {
    "pt": {"name": "Português", "tag": "pt-BR"},
    "en": {"name": "English", "tag": "en"},
    "zh": {"name": "中文", "tag": "zh-CN"},
}
DEFAULT_LANG = next(iter(LANGS))

# 成本权重与档位规则，抄自 index.html 的 COST_W 与 e.ratio 两行
COST_W = {
    "钱": {"0": 0, "少": 1, "多": 2},
    "时间": {"少": 0, "中": 1, "多": 2},
    "毅力": {"否": 0, "些": 1, "是": 2},
}
RATIO_ORDER = {"极高": 0, "高": 1, "一般": 2}

# 界面文案：key -> (zh, pt, en)，{0} {1}… 是占位。只翻译界面，书的正文保持原文。
# 每种语言渲染成独立的一页（见 main）；下拉框是在这几页之间跳转。
STR = {
    "title": ("高性价比人生指南", "Guia de Vida de Alto Custo-Benefício", "The High Value-for-Money Life Guide"),
    "scope.all": ("全书 {0} 节", "Livro completo, {0} seções", "Full book, {0} sections"),
    "scope.some": ("第 {0} 节", "Seções {0}", "Sections {0}"),
    "doc.desc.all": (
        "《高性价比人生指南》全书 {0} 节，共 {1} 条建议，每条标注成本、收益、证据等级（A/B/C）与原始文献链接。单文件、零依赖、可离线阅读。",
        "Guia de Vida de Alto Custo-Benefício: livro completo, {0} seções e {1} dicas, cada uma com custo, benefício, nível de evidência (A/B/C) e link para a fonte original. Arquivo único, sem dependências, funciona offline.",
        "The High Value-for-Money Life Guide: full book, {0} sections and {1} tips, each with cost, benefit, evidence grade (A/B/C) and a link to the original source. Single file, zero dependencies, works offline."),
    "doc.desc.some": (
        "《高性价比人生指南》第 {0} 节，共 {1} 条建议，每条标注成本、收益、证据等级（A/B/C）与原始文献链接。单文件、零依赖、可离线阅读。",
        "Guia de Vida de Alto Custo-Benefício: seções {0}, {1} dicas, cada uma com custo, benefício, nível de evidência (A/B/C) e link para a fonte original. Arquivo único, sem dependências, funciona offline.",
        "The High Value-for-Money Life Guide: sections {0}, {1} tips, each with cost, benefit, evidence grade (A/B/C) and a link to the original source. Single file, zero dependencies, works offline."),
    "filter.all": ("全部", "Todas", "All"),
    "filter.a": ("只看 A 级", "Evidência A", "Evidence A only"),
    "filter.plain": ("只看说人话", "Linguagem simples", "Plain talk only"),
    "search.ph": ("搜索标题、说人话、收益…", "Buscar nas dicas…", "Search tips…"),
    "count": ("{0} / {1} 条", "{0} / {1}", "{0} / {1}"),
    "n.items": ("{0} 条", "{0} dicas", "{0} tips"),
    "theme": ("明/暗", "Tema", "Theme"),
    "jump.aria": ("跳转到某一节", "Ir para uma seção", "Jump to a section"),
    "lang.aria": ("语言", "Idioma", "Language"),
    "empty": ("没有匹配的条目", "Nenhuma dica encontrada", "No matching tips"),
    "empty.hint": ("换个词试试，或者切回「全部」。", "Tente outra palavra ou volte para Todas.", "Try another word, or switch back to All."),
    "top": ("回到顶部", "Voltar ao topo", "Back to top"),
    "grade": ("{0} 级", "Evidência {0}", "Evidence {0}"),
    # 证据等级说明：取自上游 README「证据分级」一节
    "grade.help": ("这个等级是什么意思？", "O que significa este nível?", "What does this grade mean?"),
    "grade.help.title": ("证据等级", "Nível de evidência", "Evidence grade"),
    "grade.help.A": (
        "有具体数字可查，出处是荟萃分析、跟踪很多人很多年的大型队列，或者随机分组的试验，能说出降了多少。",
        "Há números concretos e verificáveis, vindos de meta-análises, de grandes estudos que acompanham muitas pessoas por anos ou de ensaios randomizados. Dá para dizer quanto o risco cai.",
        "Concrete, checkable numbers from meta-analyses, large cohorts followed for years, or randomized trials. It can say how much the risk drops."),
    "grade.help.B": (
        "有研究支持，但说不出确切数字；或者只有小样本、单独一项研究撑着。",
        "Há estudos que apoiam, mas sem um número preciso; ou só um estudo pequeno ou isolado.",
        "Backed by research, but without a precise number; or resting on a single or small study."),
    "grade.help.C": (
        "作者自己的经验，或者大家公认的做法，没有直接的研究文献。",
        "Experiência do autor ou prática amplamente aceita, sem estudos diretos.",
        "The author's experience or widely accepted practice, with no direct studies."),
    "grade.help.note": (
        "A 级不等于一定是因果：收益栏写着「随机分成两组」的是试验，写着「只记录、不分组」的只是观察。",
        "Evidência A não garante causa e efeito. O campo Benefício diz se as pessoas foram sorteadas em grupos (um ensaio) ou só acompanhadas (um estudo observacional).",
        "Grade A does not guarantee cause and effect. The Benefit field says whether people were randomly split into groups (a trial) or only followed (an observational study)."),
    "close": ("关闭", "Fechar", "Close"),
    "toc": ("目录", "Índice", "Contents"),
    "next": ("下一节", "Próxima seção", "Next section"),
    "ratio.极高": ("性价比 极高", "Custo-benefício altíssimo", "Value for money: excellent"),
    "ratio.高": ("性价比 高", "Custo-benefício alto", "Value for money: high"),
    "ratio.一般": ("性价比 一般", "Custo-benefício regular", "Value for money: average"),
    "field.成本": ("成本", "Custo", "Cost"),
    "field.收益": ("收益", "Benefício", "Benefit"),
    "field.备注": ("备注", "Observação", "Note"),
    "src": ("来源", "Fontes", "Sources"),
    "src.n": ("来源（{0} 条文献）", "Fontes ({0} referências)", "Sources ({0} references)"),
    "footer.1": (
        "数据来源：{0}（Unlicense，公有领域）。",
        "Fonte dos dados: {0} (Unlicense, domínio público).",
        "Data source: {0} (Unlicense, public domain)."),
    "footer.1.rev": (
        "数据来源：{0}（Unlicense，公有领域），数据截至 {1}（{2}）。",
        "Fonte dos dados: {0} (Unlicense, domínio público), dados até {1} ({2}).",
        "Data source: {0} (Unlicense, public domain), data as of {1} ({2})."),
    "footer.2": (
        "「说人话」「收益」等栏目为原文摘录，未作改写；本页共 {0} 条，A 级 {1} 条、B 级 {2} 条、C 级 {3} 条，含 {4} 条文献外链。",
        "Esta página tem {0} dicas: {1} com evidência A, {2} com B e {3} com C, e {4} links externos para as fontes.",
        "This page has {0} tips: {1} with evidence A, {2} with B and {3} with C, plus {4} external links to sources."),
    # 译文进度（zh 是原文，不显示这两句）
    "footer.tr.none": (
        "",
        "O texto das dicas ainda está no original em chinês: só a interface foi traduzida.",
        "The text of the tips is still the original Chinese: only the interface is translated."),
    "footer.tr.some": (
        "",
        "{0} de {1} dicas já estão traduzidas para o português. A tradução é automática e pode conter erros, então confira o original em chinês; as demais dicas continuam em chinês.",
        "{0} of {1} tips are translated into English. The translation is machine-generated and may contain errors, so check the Chinese original; the remaining tips are still in Chinese."),
    "footer.tr.all": (
        "",
        "Todas as {0} dicas já estão traduzidas para o português. A tradução é automática e pode conter erros, então confira o original em chinês.",
        "All {0} tips are translated into English. The translation is machine-generated and may contain errors, so check the Chinese original."),
    "footer.3": (
        "单文件自包含，不引用任何外部资源（正文中的文献链接除外），可离线阅读。由 build.py 生成。",
        "Arquivo único e autossuficiente: não carrega nenhum recurso externo (exceto os links de fontes no texto) e funciona offline. Gerado por build.py.",
        "Single self-contained file: loads no external resources (except the source links in the text) and works offline. Generated by build.py."),
}
for _s in ("all", "some"):
    STR["doc.title." + _s] = tuple(t + " · " + sc for t, sc in zip(STR["title"], STR["scope." + _s]))

# 成本标签：zh 键 -> ((pt 标签, en 标签), {zh 值: (pt 值, en 值)})。展开成 tag.<键>.<值> 进 STR。
TAGS = {
    "口径": (("Medido em", "Measured in"), {
        "时间": ("tempo", "time"), "死亡率": ("mortalidade", "mortality"),
        "自由": ("liberdade", "freedom"), "金钱": ("dinheiro", "money")}),
    "钱": (("Dinheiro", "Money"), {
        "0": ("nenhum", "none"), "少": ("pouco", "little"), "多": ("muito", "a lot")}),
    "时间": (("Tempo", "Time"), {
        "少": ("pouco", "little"), "中": ("médio", "medium"), "多": ("muito", "a lot")}),
    "毅力": (("Força de vontade", "Willpower"), {
        "否": ("não exige", "not needed"), "些": ("alguma", "some"), "是": ("exige", "required")}),
    "收益": (("Benefício", "Benefit"), {
        "大": ("grande", "large"), "中": ("médio", "medium"), "小": ("pequeno", "small")}),
}
for _k, ((_pt, _en), _vals) in TAGS.items():
    for _v, (_vpt, _ven) in _vals.items():
        STR["tag.%s.%s" % (_k, _v)] = ("%s %s" % (_k, _v), "%s: %s" % (_pt, _vpt), "%s: %s" % (_en, _ven))

_STR_ORDER = ("zh", "pt", "en")
I18N = {lang: {k: v[n] for k, v in STR.items()} for n, lang in enumerate(_STR_ORDER)}


def _fill(s, args):
    return re.sub(r"\{(\d+)\}", lambda m: str(args[int(m.group(1))]), s)


def tr(lang, key, *args):
    """取某语言的界面文案，{0} {1}… 用 args 填。"""
    return _fill(I18N[lang][key], args)


def toc_title(title):
    """目录里的短标题。含中日韩字（原文，或还没译的回退）按字数截；拉丁文字按词截，不把词切断。"""
    if re.search(r"[\u4e00-\u9fff]", title):
        return title if len(title) <= TOC_TITLE_MAX_CJK else title[:TOC_TITLE_MAX_CJK - 1] + "…"
    return textwrap.shorten(title, TOC_TITLE_MAX_LATIN, placeholder="…")


def src_key(src):
    """原文字段 -> 查译文的 key。原文有任何改动，key 就变了，旧译文自然对不上、回退到中文。"""
    return json.dumps(src, sort_keys=True, ensure_ascii=False)


def entry_src(e):
    return {"title": e["title"], **{k: e["fields"][k] for k in TRANSLATABLE if k in e["fields"]}}


def section_src(title, intro):
    return {"title": title, "intro": " ".join(intro)}


def load_translations(lang):
    """translations/<lang>/*.json -> {src_key: 译文字段}。

    文件格式：{"section": {"src": {title, intro}, "tr": {...}},
              "entries": [{"src": {title, 说人话, 成本, ...}, "tr": {...}}, ...]}
    src 是当时翻译所依据的中文原文，既用来匹配、也方便并排审校；tr 缺的字段回退到中文。
    """
    out = {}
    for p in sorted((TRANSLATIONS_DIR / lang).glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        for item in ([data["section"]] if "section" in data else []) + data.get("entries", []):
            out[src_key(item["src"])] = item["tr"]
    return out


def localize(e, trans):
    """返回 (换上译文的条目, 是否有译文)。没有译文或字段缺失就保留中文。"""
    t = trans.get(src_key(entry_src(e)))
    if not t:
        return e, False
    fields = {**e["fields"], **{k: t[k] for k in TRANSLATABLE if t.get(k)}}
    return {**e, "title": t.get("title") or e["title"], "fields": fields}, True


def find_file(n):
    hits = sorted(REPO.glob("book/%02d-*.md" % n))
    if not hits:
        raise SystemExit("找不到第 %d 节" % n)
    return hits[0]


def parse(path):
    lines = path.read_text(encoding="utf-8").split("\n")
    title, intro, entries, cur = "", [], [], None
    for ln in lines:
        m = re.match(r"^#\s+(.*)$", ln)
        if m and not title:
            title = m.group(1).strip()
            continue
        m = re.match(r"^###\s+(\d+)\.\s*(.*)$", ln)
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2).strip(),
                   "tags_raw": None, "fields": {}, "last": None}
            entries.append(cur)
            continue
        if cur is None:
            if ln.strip() and not ln.startswith("["):
                intro.append(ln.strip())
            continue
        mt = re.match(r"^<!--\s*成本标签:\s*(.*?)\s*-->", ln)
        if mt:
            cur["tags_raw"] = mt.group(1)
            continue
        mf = re.match(r"^-\s*(成本|说人话|收益|证据等级|来源|备注)：(.*)$", ln)
        if mf:
            cur["last"] = mf.group(1)
            cur["fields"][mf.group(1)] = mf.group(2).strip()
            continue
        if not ln.strip():
            cur["last"] = None
            continue
        if cur["last"]:
            cur["fields"][cur["last"]] += ln.strip()
    return title, intro, entries


def parse_tags(raw):
    if not raw:
        return {}
    return dict(re.findall(r"(钱|时间|毅力|收益|口径)=(\S+)", raw))


def ratio_of(t):
    try:
        cs = sum(COST_W[k][t[k]] for k in ("钱", "时间", "毅力"))
    except KeyError:
        return None
    lv = t.get("收益")
    if lv == "大":
        return "极高" if cs == 0 else ("高" if cs <= 2 else "一般")
    if lv == "中" and cs == 0:
        return "高"
    return "一般"


def inline(s):
    """把一小段 markdown 行内语法转成 HTML。先整体转义，再用占位符放链接。"""
    stash = []

    def mk(url, text=None):
        shown = text or url
        if len(shown) > 62:
            shown = shown[:59] + "…"
        stash.append('<a href="%s" target="_blank" rel="noopener">%s</a>' % (url, shown))
        return "\u0001%d\u0001" % (len(stash) - 1)

    s = html.escape(s, quote=False)
    s = re.sub(r"&lt;(https?://[^\s]+?)&gt;", lambda m: mk(m.group(1)), s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", lambda m: mk(m.group(2), m.group(1)), s)
    s = re.sub(r"(?<![\w\"=])(https?://[^\s，。；）)]+)", lambda m: mk(m.group(1)), s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = s.replace("\\*", "*").replace("\\_", "_")
    s = re.sub("\u0001(\\d+)\u0001", lambda m: stash[int(m.group(1))], s)
    return s


def link_count(s):
    return len(re.findall(r"https?://", s or ""))


def source_rev():
    """取上游当前提交的短 hash 与日期。

    故意用上游 git 状态而不是构建时间：同样的源状态下重跑结果完全一致，
    产物可做字节级比对，方便确认「没改坏东西」。
    """
    try:
        p = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--date=short",
                            "--format=%h|%cd"],
                           capture_output=True, text=True, encoding="utf-8", timeout=15)
        if p.returncode == 0 and "|" in (p.stdout or ""):
            h, d = p.stdout.strip().split("|", 1)
            return h.strip(), d.strip()
    except Exception:
        pass
    return "", ""


CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#fcfcfc;--bg-alt:#f7f7f7;--bg-elv:#ffffff;
  --divider:#ececec;
  --t1:#1f2125;--t2:#45484e;--t3:#86898f;
  --brand-1:#0f7050;--brand-2:#0a5a40;--brand-soft:rgba(15,112,80,.09);
  --yellow-1:#86662d;
  --mark:rgba(214,180,90,.3);
  --shadow-sm:0 1px 2px rgba(20,22,26,.08);--shadow-lg:0 6px 20px rgba(20,22,26,.12);
  --info:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='black' stroke-width='1.6' stroke-linecap='round'%3E%3Ccircle cx='8' cy='8' r='6.5'/%3E%3Cpath d='M8 7.2v4M8 4.6v.1'/%3E%3C/svg%3E");
  --font:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  /* 字号阶梯：正文 15，往下 13.5 / 12.5 / 11，往上 16（说人话）/ 18（条目标题）/ 28（节标题） */
  --fs-2xs:11px;--fs-xs:12.5px;--fs-sm:13.5px;--fs-base:15px;--fs-lead:16px;--fs-md:18px;--fs-lg:28px;
  --fw-regular:400;--fw-medium:500;--fw-strong:600;
  --lh-tight:1.35;--lh-body:1.75;
  /* 版心：正文一栏约 75 个拉丁字符宽，左侧留一条页边挂节号和条目号 */
  --measure:640px;--hang:48px;--gutter:40px;
  --bar:56px;--side:296px;
  --lbl:84px; /* 字段标签列宽：葡/英标签比中文两个字长，中文时收窄 */
}
html[lang^=zh]{--lbl:52px}
[data-theme=dark]{
  --bg:#18191b;--bg-alt:#151618;--bg-elv:#1c1d20;
  --divider:#2a2b2f;
  --t1:#ededea;--t2:#bbbdc1;--t3:#7a7c82;
  --brand-1:#5fcf9f;--brand-2:#8adfba;--brand-soft:rgba(95,207,159,.12);
  --yellow-1:#d5b87d;
  --mark:rgba(213,184,125,.26);
  --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-lg:0 6px 20px rgba(0,0,0,.45);
}
html{scroll-behavior:smooth;scroll-padding-top:calc(var(--bar) + 14px)}
body{margin:0;background:var(--bg);color:var(--t1);font:var(--fs-base)/var(--lh-body) var(--font);
  -webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
a{color:var(--brand-1);text-decoration:none}
a:hover{color:var(--brand-2);text-decoration:underline;text-underline-offset:2px}
mark{background:var(--mark);color:inherit;border-radius:2px;padding:0 1px}
strong{font-weight:var(--fw-strong);color:var(--t1)}
:focus-visible{outline:2px solid var(--brand-1);outline-offset:2px}

/* min-height 用常量、不用 --bar：--bar 是 JS 实测回写的值，
   若拿它当 min-height，顶栏收起后会因为 min-height 还停在旧高度而缩不下去。 */
.bar{position:sticky;top:0;z-index:30;display:flex;flex-wrap:wrap;align-items:center;gap:12px;
  padding:0 20px;min-height:56px;border-bottom:1px solid var(--divider);
  background:color-mix(in srgb,var(--bg) 86%,transparent);
  -webkit-backdrop-filter:saturate(1.4) blur(12px);backdrop-filter:saturate(1.4) blur(12px)}
.bar h1{font-size:var(--fs-base);font-weight:var(--fw-strong);letter-spacing:-.01em;margin:0;white-space:nowrap;min-width:0}
.bar h1 small{font-weight:var(--fw-regular);font-size:var(--fs-xs);color:var(--t3);margin-left:10px;letter-spacing:0}
/* 三格刻度：顶栏标志和条目里的性价比用同一个符号，格子逐级升高 */
.logo,.ratio{display:inline-flex;gap:2px}
.logo{align-items:flex-end;height:14px;margin-right:10px;vertical-align:-1px}
.ratio{align-items:baseline}
.logo i,.ratio i{width:4px;border-radius:1px;background:var(--brand-1)}
.logo i:nth-child(1),.ratio i:nth-of-type(1){height:6px}
.logo i:nth-child(2),.ratio i:nth-of-type(2){height:10px}
.logo i:nth-child(3),.ratio i:nth-of-type(3){height:14px}
.spacer{flex:1}
.seg{display:flex;gap:2px;padding:2px;border-radius:9px;background:var(--bg-alt);box-shadow:inset 0 0 0 1px var(--divider)}
.seg button{height:28px;padding:0 12px;border:0;border-radius:7px;background:none;color:var(--t2);
  font:var(--fw-medium) var(--fs-xs)/1 var(--font);cursor:pointer;white-space:nowrap}
.seg button:hover{color:var(--t1)}
.seg button[aria-pressed=true]{background:var(--bg-elv);color:var(--t1);box-shadow:var(--shadow-sm),0 0 0 1px var(--divider)}
.search{position:relative;flex:1 1 150px;max-width:300px}
.search input{width:100%;height:34px;padding:0 30px 0 32px;border-radius:9px;border:1px solid var(--divider);
  background:var(--bg-alt);color:var(--t1);font:inherit;font-size:var(--fs-sm)}
.search input:focus{outline:0;border-color:var(--brand-1);background:var(--bg-elv);box-shadow:0 0 0 3px var(--brand-soft)}
.search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);width:15px;height:15px;
  fill:none;stroke:var(--t3);stroke-width:2;pointer-events:none}
.search kbd{position:absolute;right:8px;top:50%;transform:translateY(-50%);font:500 10px/1 var(--font);
  color:var(--t3);border:1px solid var(--divider);border-radius:4px;padding:2px 4px;background:var(--bg-elv)}
.count{font-size:var(--fs-xs);color:var(--t3);white-space:nowrap;font-variant-numeric:tabular-nums}
.icon{display:grid;place-items:center;width:32px;height:32px;padding:0;border:0;border-radius:8px;
  background:none;color:var(--t2);cursor:pointer}
.icon svg{width:17px;height:17px}
.icon circle{fill:none;stroke:currentColor;stroke-width:1.8}
.icon path{fill:currentColor}
.icon:hover,.lang:hover{background:var(--bg-alt);color:var(--t1)}
.jump{display:none;height:32px;max-width:min(38vw,220px);padding:0 6px;border-radius:8px;border:1px solid var(--divider);
  background:var(--bg-elv);color:var(--t2);font:var(--fw-medium) var(--fs-xs)/1 var(--font)}
.lang{field-sizing:content;height:32px;padding:0 4px;border:0;border-radius:8px;background:none;
  color:var(--t2);font:var(--fw-medium) var(--fs-xs)/1 var(--font);cursor:pointer}

.shell{display:flex;align-items:flex-start}
.toc{position:sticky;top:var(--bar);flex:none;width:var(--side);height:calc(100vh - var(--bar));
  overflow-y:auto;padding:28px 14px 80px 16px;border-right:1px solid var(--divider);
  scrollbar-width:thin;scrollbar-color:var(--divider) transparent}
.toc .grp{border-bottom:1px solid var(--divider)}
.toc .grp:last-of-type{border-bottom:0}
/* 折叠的节头：左边标题是跳转链接，右边条数和箭头点了才展开 */
.toc .gt{display:flex;align-items:flex-start;gap:8px;padding:9px 8px;list-style:none;cursor:pointer;border-radius:6px}
.toc .gt::-webkit-details-marker{display:none}
.toc .gt:hover{background:var(--bg-alt)}
.toc .gt a{flex:1;min-width:0;display:block;padding:0;font-size:var(--fs-sm);font-weight:var(--fw-medium);color:var(--t1)}
.toc .gt a:hover{background:none;color:var(--brand-1)}
.toc .grp.current>.gt a{font-weight:var(--fw-strong);color:var(--brand-1)}
.toc .gt small{flex:none;padding-top:2px;font-size:var(--fs-2xs);color:var(--t3);white-space:nowrap;font-variant-numeric:tabular-nums}
.toc .gt::after{content:"";flex:none;width:5px;height:5px;margin:7px 2px 0;
  border:solid var(--t3);border-width:0 1.5px 1.5px 0;transform:rotate(-45deg);transition:transform .15s}
.toc .grp[open]>.gt::after{transform:translateY(-2px) rotate(45deg)}
.toc .links{padding:2px 0 12px}
/* 侧栏开关：宽屏收起；窄屏（≤1080，见下方媒体查询）是抽屉 */
html.toc-off .toc{display:none}
.scrim{display:none}
#toc-btn svg{fill:none;stroke:currentColor;stroke-width:1.8}
#toc-btn path{fill:none}

.next{display:block;margin:8px 0 0 var(--hang);padding:24px 0 0;border-top:1px solid var(--divider);
  font-size:var(--fs-md);font-weight:var(--fw-strong);line-height:var(--lh-tight);color:var(--t1)}
.next small{display:block;margin-bottom:4px;font-size:var(--fs-xs);font-weight:var(--fw-regular);color:var(--t3)}
.next::after{content:"";display:inline-block;width:7px;height:7px;margin-left:10px;vertical-align:2px;
  border:solid currentColor;border-width:1.8px 1.8px 0 0;transform:rotate(45deg);transition:transform .15s}
.next:hover{color:var(--brand-1);text-decoration:none}
.next:hover::after{transform:translateX(3px) rotate(45deg)}
.toc a{display:flex;gap:6px;align-items:baseline;padding:4px 8px;border-radius:6px;font-size:var(--fs-xs);
  line-height:var(--lh-tight);color:var(--t2)}
.toc a:hover{background:var(--bg-alt);color:var(--t1);text-decoration:none}
.toc a.active{background:var(--brand-soft);color:var(--brand-1)}
.toc a i{font-style:normal;color:var(--t3);font-variant-numeric:tabular-nums;flex:none;min-width:16px;text-align:right}
.dot{width:6px;height:6px;border-radius:50%;flex:none;margin-top:6px}
/* 目录圆点和条目里的三格刻度同一套含义：越实越值 */
.d0{background:var(--brand-1)}.d1{background:var(--brand-1);opacity:.45}.d2{background:var(--t3);opacity:.6}

main{flex:1;min-width:0;max-width:calc(var(--hang) + var(--measure) + 2 * var(--gutter));margin:0 auto;
  padding:48px var(--gutter) 140px}
section{margin-bottom:96px}
/* 节头和条目都是两栏：左栏页边放编号，右栏正文，所有文字对齐同一条左边线 */
.sec-h{display:grid;grid-template-columns:var(--hang) minmax(0,1fr);align-items:baseline;margin-bottom:20px}
.sn{grid-row:1;font:var(--fw-strong) var(--fs-lg)/var(--lh-tight) var(--font);color:var(--brand-1);
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.sec-h h2{grid-row:1;grid-column:2;margin:0;font-size:var(--fs-lg);font-weight:var(--fw-strong);
  line-height:var(--lh-tight);letter-spacing:-.02em;text-wrap:balance}
.sec-h .meta{grid-column:2;margin-top:4px;font-size:var(--fs-xs);color:var(--t3);font-variant-numeric:tabular-nums}
.intro{margin:0 0 20px var(--hang);color:var(--t2);text-wrap:pretty}
.topics{list-style:none;margin:0 0 40px var(--hang);padding:0;font-size:var(--fs-sm);line-height:1.7;
  color:var(--t2);border-top:1px solid var(--divider)}
.topics li{padding:10px 0}
.topics li+li{border-top:1px solid var(--divider)}
.topics strong{display:block;margin-bottom:2px}

.card{display:grid;grid-template-columns:var(--hang) minmax(0,1fr);padding:32px 0;border-top:1px solid var(--divider)}
.card>*{grid-column:2}
.card>.num{grid-column:1;grid-row:1;align-self:baseline;font:var(--fw-medium) var(--fs-sm)/1 var(--font);
  color:var(--t3);font-variant-numeric:tabular-nums}
.card h3{grid-row:1;align-self:baseline;margin:0;font-size:var(--fs-md);font-weight:var(--fw-strong);
  line-height:var(--lh-tight);letter-spacing:-.01em;text-wrap:balance}
.sig{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;margin:10px 0 14px}
/* 证据等级：A 实心、B 描边、C 虚线，不靠颜色也分得清 */
.grade{font:var(--fw-strong) var(--fs-2xs)/1 var(--font);padding:4px 8px;border-radius:4px;border:1px solid transparent;background:none}
.gA{background:var(--t1);color:var(--bg)}
.gB{border-color:var(--t2);color:var(--t1)}
.gC{border-style:dashed;border-color:var(--t3);color:var(--t2)}
/* 徽章是按钮：带一个 ⓘ，点开 #g-help 说明卡；图标用 mask 画，765 条不必各带一份 SVG */
button.grade{display:inline-flex;align-items:center;gap:5px;padding-right:6px;cursor:pointer}
button.grade::after{content:"";width:12px;height:12px;background:currentColor;opacity:.75;
  -webkit-mask:var(--info) center/contain no-repeat;mask:var(--info) center/contain no-repeat}
button.grade:hover::after{opacity:1}
button.gB:hover,button.gC:hover{border-color:var(--t1);color:var(--t1)}
.help{width:min(420px,calc(100vw - 32px));padding:22px 24px 20px;border:1px solid var(--divider);border-radius:12px;
  background:var(--bg-elv);color:var(--t1);box-shadow:var(--shadow-lg)}
.help::backdrop{background:rgba(10,12,14,.28)}
.help h4{margin:0 0 14px;font-size:var(--fs-base);font-weight:var(--fw-strong)}
.help .close{position:absolute;top:12px;right:12px;font-size:20px;line-height:1}
.help dl{margin:0}
.help dl div{display:grid;grid-template-columns:40px minmax(0,1fr);gap:10px;align-items:baseline;padding:8px 0}
.help dl div+div{border-top:1px solid var(--divider)}
.help dt .grade{display:inline-block;min-width:22px;text-align:center}
.help dd{margin:0;font-size:var(--fs-sm);line-height:1.6;color:var(--t2)}
.help p{margin:14px 0 0;padding-top:12px;border-top:1px solid var(--divider);font-size:var(--fs-xs);line-height:1.6;color:var(--t3)}
.ratio{line-height:1;font-size:var(--fs-xs);font-weight:var(--fw-medium);color:var(--t2)}
.ratio i:nth-of-type(3){margin-right:7px}
.r1 i:nth-of-type(3),.r2 i:nth-of-type(n+2){background:var(--t3);opacity:.3}
.plain{margin:0;font-size:var(--fs-lead);line-height:var(--lh-body);color:var(--t1);text-wrap:pretty}
.facts{display:flex;flex-wrap:wrap;gap:4px 20px;margin:14px 0 0;font-size:var(--fs-xs)}
.facts div{display:flex;gap:6px}
.facts dt{color:var(--t3)}
.facts dd{margin:0;color:var(--t1)}
.fields{margin-top:16px}
.f{display:grid;grid-template-columns:var(--lbl) minmax(0,1fr);gap:12px;padding:4px 0;
  font-size:var(--fs-sm);line-height:1.7;color:var(--t2)}
.f b{font-weight:var(--fw-medium);color:var(--t3);font-size:var(--fs-xs);padding-top:1px}
.f.note b{color:var(--yellow-1)}
.f>div{min-width:0;overflow-wrap:anywhere}
.src{margin-top:12px}
.src summary{cursor:pointer;font-size:var(--fs-xs);color:var(--t3);list-style:none;user-select:none}
.src summary::-webkit-details-marker{display:none}
.src summary{display:inline-flex;align-items:center;gap:8px}
.src summary::before{content:"";width:5px;height:5px;border:solid currentColor;border-width:0 1.5px 1.5px 0;
  transform:rotate(-45deg);transition:transform .15s}
.src[open] summary::before{transform:translateY(-2px) rotate(45deg)}
.src summary:hover{color:var(--brand-1)}
.src .sbody{font-size:var(--fs-xs);line-height:1.8;color:var(--t2);padding:8px 0 2px;word-break:break-word;overflow-wrap:anywhere}

body.plain-only .facts,body.plain-only .fields,body.plain-only .src{display:none}
.hidden{display:none!important}

.empty{margin-left:var(--hang);padding:72px 0 96px;text-align:center;color:var(--t3);font-size:var(--fs-sm)}
.empty p{margin:0}
.empty p:first-child{margin-bottom:6px;color:var(--t1);font-size:var(--fs-md);font-weight:var(--fw-strong)}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  *,*::before,*::after{transition:none!important}
}
footer{margin-left:var(--hang);color:var(--t3);font-size:var(--fs-xs);border-top:1px solid var(--divider);
  padding-top:20px;line-height:1.9}
footer a{color:var(--t2)}

#top{position:fixed;right:20px;bottom:20px;z-index:40;width:40px;height:40px;border-radius:10px;
  border:1px solid var(--divider);background:var(--bg-elv);color:var(--t2);cursor:pointer;
  font:400 16px/1 var(--font);box-shadow:var(--shadow-lg);
  opacity:0;pointer-events:none;transition:opacity .2s,color .18s}
#top.show{opacity:1;pointer-events:auto}
#top:hover{color:var(--brand-1);border-color:var(--brand-1)}

/* 葡/英标题和按钮更长：1200 以下收掉副标题，顶栏才能留在一行 */
@media (max-width:1200px){
  .bar h1 small{display:none}
}
@media (max-width:1080px){
  .toc{display:none}
  .jump{display:block}
  .search{max-width:none}
  html.toc-on .toc{display:block;position:fixed;top:var(--bar);bottom:0;left:0;z-index:35;height:auto;
    width:min(320px,86vw);background:var(--bg);box-shadow:var(--shadow-lg)}
  html.toc-on .scrim{display:block;position:fixed;inset:var(--bar) 0 0 0;z-index:34;background:rgba(10,12,14,.28)}
  :root{--gutter:28px}
}
@media (max-width:820px){
  .bar{padding:8px 12px;gap:8px;min-height:0}
  /* 顶栏三行：① 标题+节号+明暗 ② 筛选按钮+计数 ③ 搜索（独占整行，手机上才好打字） */
  .bar h1{order:1;flex:1 1 120px;font-size:14px;overflow:hidden;text-overflow:ellipsis}
  .spacer{display:none}
  .jump{order:2}
  #theme{order:3}
  .seg{order:4}
  .count{order:7;margin-left:auto}
  .search{order:8;max-width:none;margin-top:2px}
  .search input{height:34px}
  .lang{order:8;margin-top:2px}
  .search kbd{display:none}
  /* 向下滚动后收成一行（标题+搜索+明暗），把竖向空间还给正文；滚回顶部再展开 */
  body.compact .jump,body.compact .lang,body.compact .seg,body.compact .count{display:none}
  body.compact .search{order:2;flex:1 1 120px;margin-top:0}
  body.compact #theme{order:3}
  :root{--fs-lg:23px;--fs-md:17px;--fs-lead:15.5px;--gutter:16px;--hang:34px;--lbl:76px}
  html[lang^=zh]{--lbl:44px}
  main{padding-top:28px}
  section{margin-bottom:64px}
  .card{padding:26px 0}
  .f{gap:8px}
}
@media (max-width:520px){
  .bar h1 small{display:none}
}
/* 320-380px 的窄屏：按钮和节号下拉都收紧，否则顶栏会被挤到多占一到两行 */
@media (max-width:380px){
  .seg button{padding:0 8px;font-size:var(--fs-2xs)}
  .bar h1{flex:1 1 90px;font-size:13px}
  .jump{max-width:32vw}
}
@media print{
  .bar,.toc,#top{display:none}
  main{max-width:none;padding:0}
  .card{break-inside:avoid;border-color:#ccc}
  .src .sbody{display:block}
  body{font-size:11pt}
}
"""


def render_entry(e, sec_no, lang):
    t = parse_tags(e["tags_raw"])
    f = e["fields"]
    grade = (f.get("证据等级") or "?").strip()[:1]
    ratio = ratio_of(t)
    gcls = {"A": "gA", "B": "gB", "C": "gC"}.get(grade, "gC")
    # 点等级徽章弹出全页共用的一张说明卡（#g-help，见 render_page）
    sig = ('<button class="grade %s" popovertarget="g-help" title="%s">%s</button>'
           % (gcls, tr(lang, "grade.help"), tr(lang, "grade", grade)))
    if ratio:
        # 三格刻度：亮几格 = 性价比档位，CSS 按 r0/r1/r2 点亮
        sig += ('<span class="ratio r%d"><i></i><i></i><i></i>%s</span>'
                % (RATIO_ORDER[ratio], tr(lang, "ratio." + ratio)))
    facts = []
    for k in ("钱", "时间", "毅力", "收益", "口径"):
        if t.get(k):
            key = "tag.%s.%s" % (k, t[k])
            # 上游新增了表里没有的取值时，按原文显示，不翻译
            text = tr(lang, key) if key in STR else "%s %s" % (k, t[k])
            # 葡/英是「标签: 值」（标签里可能有空格），中文是「标签 值」
            label, value = re.split(r":\s*", text, 1) if ":" in text else text.split(" ", 1)
            facts.append('<div><dt>%s</dt><dd>%s</dd></div>' % (label, value))

    rows = []
    for k in ("成本", "收益"):
        if f.get(k):
            rows.append('<div class="f"><b>%s</b><div>%s</div></div>' % (tr(lang, "field." + k), inline(f[k])))
    if f.get("备注"):
        rows.append('<div class="f note"><b>%s</b><div>%s</div></div>' % (tr(lang, "field.备注"), inline(f["备注"])))

    src = f.get("来源", "")
    n = link_count(src)
    src_html = ""
    if src:
        src_html = ('<details class="src"><summary>%s</summary><div class="sbody">%s</div></details>'
                    % (tr(lang, "src.n", n) if n else tr(lang, "src"), inline(src)))

    return ('<article class="card" id="s%d-%d" data-grade="%s" data-ratio="%s">'
            '<span class="num">%d</span><h3>%s</h3>'
            '<div class="sig">%s</div>'
            '<p class="plain">%s</p>'
            '<dl class="facts">%s</dl>'
            '<div class="fields">%s</div>%s</article>') % (
        sec_no, e["no"], grade, ratio or "-", e["no"], inline(e["title"]),
        sig, inline(f.get("说人话", "")), "".join(facts), "".join(rows), src_html)


# 标签页图标：顶栏同款三格刻度
FAVICON = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='%230f7050'>"
           "<rect x='1.5' y='9' width='3.5' height='5.5' rx='.8'/><rect x='6.25' y='5.5' width='3.5' height='9' rx='.8'/>"
           "<rect x='11' y='1.5' width='3.5' height='13' rx='.8'/></svg>")

# 主题要在 <head> 里、页面画出来之前定好；放在 body 末尾的话，暗色用户会先闪一下白屏
THEME_JS = r"""try{
  const t=localStorage.getItem('hltb-theme');
  if(t) document.documentElement.setAttribute('data-theme',t);
  else if(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.setAttribute('data-theme','dark');
  if(localStorage.getItem('hltb-toc')==='off') document.documentElement.classList.add('toc-off');
}catch(e){}"""

JS = r"""
const cards=[...document.querySelectorAll('.card')];
const secs=[...document.querySelectorAll('section')];
const bar=document.querySelector('.bar');
const q=document.getElementById('q');
const cnt=document.getElementById('cnt');
const jump=document.getElementById('jump');
const fAll=document.getElementById('f-all');
const fA=document.getElementById('f-a');
const fP=document.getElementById('f-plain');
const themeBtn=document.getElementById('theme');
const topBtn=document.getElementById('top');
const langSel=document.getElementById('lang');
const toc=document.getElementById('toc');
const tocBtn=document.getElementById('toc-btn');
const grps=[...document.querySelectorAll('.toc .grp')];
const root=document.documentElement;
const narrow=window.matchMedia('(max-width:1080px)');
let grade=null, plainOnly=false, openGrp=null;

/* 目录跟着阅读位置走：展开正在读的那一节、收起上一节，并把它滚进目录可视区 */
function follow(id){
  const g=grps.find(x=>x.dataset.sec===id);
  if(!g||g===openGrp) return;
  if(openGrp){openGrp.classList.remove('current'); if(!q.value.trim()) openGrp.open=false;}
  g.open=true; g.classList.add('current'); openGrp=g;
  const r=g.getBoundingClientRect(), t=toc.getBoundingClientRect();
  if(r.top<t.top||r.top>t.bottom-160) toc.scrollTo({top:g.offsetTop-24});
}

/* 目录开关：宽屏是显示/隐藏侧栏（记住选择），窄屏是滑出抽屉 */
function tocShown(){return narrow.matches?root.classList.contains('toc-on'):!root.classList.contains('toc-off');}
function syncTocBtn(){tocBtn.setAttribute('aria-expanded',String(tocShown()));}
tocBtn.onclick=()=>{
  if(narrow.matches) root.classList.toggle('toc-on');
  else{
    const off=root.classList.toggle('toc-off');
    try{localStorage.setItem('hltb-toc',off?'off':'on');}catch(e){}
  }
  syncTocBtn();
};
function closeDrawer(){root.classList.remove('toc-on');syncTocBtn();}
document.querySelector('.scrim').onclick=closeDrawer;
toc.addEventListener('click',e=>{if(narrow.matches&&e.target.closest('a')) closeDrawer();});
narrow.addEventListener('change',syncTocBtn);
syncTocBtn();

/* 顶栏高度会随换行变化，交给 JS 实测，锚点跳转才不会被顶栏盖住 */
function syncBar(){
  const h=Math.round(bar.getBoundingClientRect().height);
  document.documentElement.style.setProperty('--bar', h+'px');
}

function clearMarks(root){
  const ms=[...root.querySelectorAll('mark')];
  ms.forEach(m=>m.replaceWith(document.createTextNode(m.textContent)));
  if(ms.length) root.normalize();
}
function markAll(root,term){
  if(!term) return;
  const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(n){
    if(!n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
    const p=n.parentElement;
    if(!p) return NodeFilter.FILTER_REJECT;
    if(p.closest('script,style,mark,a')) return NodeFilter.FILTER_REJECT;
    return NodeFilter.FILTER_ACCEPT;
  }});
  const nodes=[]; while(w.nextNode()) nodes.push(w.currentNode);
  const t=term.toLowerCase();
  nodes.forEach(n=>{
    const raw=n.nodeValue.toLowerCase();
    if(raw.indexOf(t)<0) return;
    const frag=document.createDocumentFragment();
    let i=raw.indexOf(t), last=0;
    while(i>=0){
      frag.appendChild(document.createTextNode(n.nodeValue.slice(last,i)));
      const m=document.createElement('mark');
      m.textContent=n.nodeValue.slice(i,i+t.length);
      frag.appendChild(m);
      last=i+t.length; i=raw.indexOf(t,last);
    }
    frag.appendChild(document.createTextNode(n.nodeValue.slice(last)));
    n.replaceWith(frag);
  });
}
function apply(){
  const term=q.value.trim().toLowerCase();
  clearMarks(document.querySelector('main'));
  let shown=0;
  cards.forEach(c=>{
    let ok=true;
    if(grade && c.dataset.grade!==grade) ok=false;
    if(ok && term && !c.textContent.toLowerCase().includes(term)) ok=false;
    c.classList.toggle('hidden',!ok);
    if(ok) shown++;
  });
  secs.forEach(s=>{
    const n=s.querySelectorAll('.card:not(.hidden)').length;
    s.classList.toggle('hidden',n===0);
    if(jump){
      const o=jump.querySelector('option[value="'+s.id+'"]');
      if(o) o.disabled=(n===0);
    }
  });
  document.getElementById('empty').classList.toggle('hidden',shown>0);
  cnt.textContent=COUNT_TPL.replace('{0}',shown).replace('{1}',cards.length);
  if(term) markAll(document.querySelector('main'),term);
  document.querySelectorAll('.toc a').forEach(a=>{
    const el=document.getElementById(a.getAttribute('href').slice(1));
    a.classList.toggle('hidden',!el||el.classList.contains('hidden'));
  });
  // 搜索时把有结果的节全展开；清空后只留正在读的那一节
  grps.forEach(g=>{
    g.classList.toggle('hidden',!g.querySelector('.links a:not(.hidden)'));
    g.open=term?true:(g===openGrp);
  });
  // 筛选或搜索时有些节被藏起来，「下一节」可能指向空处，先收起
  document.querySelectorAll('.next').forEach(n=>n.classList.toggle('hidden',!!(term||grade)));
}
let timer=null;
q.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(apply,90);});
function setMode(mode){
  grade=(mode==='A')?'A':null;
  plainOnly=(mode==='plain');
  document.body.classList.toggle('plain-only',plainOnly);
  const map={'all':fAll,'A':fA,'plain':fP};
  Object.keys(map).forEach(k=>map[k].setAttribute('aria-pressed',String(k===mode)));
  apply();
}
fAll.onclick=()=>setMode('all');
fA.onclick=()=>setMode('A');
fP.onclick=()=>setMode('plain');
fAll.setAttribute('aria-pressed','true');

if(jump){
  jump.addEventListener('change',()=>{
    const el=document.getElementById(jump.value);
    if(el) el.scrollIntoView({block:'start'});
  });
}
themeBtn.onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',cur);
  try{localStorage.setItem('hltb-theme',cur);}catch(e){}
};
/* 每种语言是独立的一页：下拉框的 value 就是目标页的文件名，带上 #锚点 保持阅读位置 */
langSel.onchange=()=>{location.href=langSel.value+location.hash;};
document.addEventListener('keydown',e=>{
  if(e.key==='/'&&document.activeElement!==q&&!/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)){
    e.preventDefault();q.focus();
  }
  if(e.key==='Escape'&&document.activeElement===q){q.value='';apply();q.blur();}
  else if(e.key==='Escape'&&root.classList.contains('toc-on')) closeDrawer();
});
topBtn.onclick=()=>window.scrollTo({top:0,behavior:'smooth'});
/* 滚动状态：① 顶栏收起（手机）② 回到顶部按钮出现。
   用 rAF 节流，避免滚动时每帧都跑；阈值留迟滞区间，防止在临界点来回抖动。 */
let compact=false, ticking=false;
function onScroll(){
  const y=window.scrollY;
  const want = compact ? (y>200) : (y>420);
  if(want!==compact){compact=want;document.body.classList.toggle('compact',compact);syncBar();}
  topBtn.classList.toggle('show',y>900);
}
addEventListener('scroll',()=>{
  if(ticking) return;
  ticking=true;
  requestAnimationFrame(()=>{ticking=false;onScroll();});
},{passive:true});
addEventListener('resize',syncBar);
if(document.fonts&&document.fonts.ready) document.fonts.ready.then(syncBar);
syncBar();

const links=[...document.querySelectorAll('.toc .links a')];
const io=new IntersectionObserver(es=>{
  es.forEach(e=>{ if(e.isIntersecting){
    if(e.target.classList.contains('card')){
      links.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+e.target.id));
      follow(e.target.closest('section').id);
    }
    else if(e.target.tagName==='SECTION'){
      follow(e.target.id);
      if(jump) jump.value=e.target.id;
    }
  }});
},{rootMargin:'-70px 0px -75% 0px'});
cards.forEach(c=>io.observe(c));
secs.forEach(s=>io.observe(s));
"""


def render_intro(text):
    """引言里「**分组名**：条目…」拆成一段导语加分组列表，一整段长文读不动。"""
    if not text:
        return ""
    parts = re.split(r"<strong>([^<]+)</strong>\s*[:：]\s*", inline(text))
    lead = parts[0].strip()
    out = '<p class="intro">%s</p>' % lead if lead else ""
    if len(parts) > 1:
        out += '<ul class="topics">%s</ul>' % "".join(
            '<li><strong>%s</strong>%s</li>' % (parts[i], parts[i + 1].strip())
            for i in range(1, len(parts), 2))
    return out


def page_path(base, lang):
    """默认语言用 -o 指定的文件，其余语言放在它旁边的 <lang>.html。"""
    return base if lang == DEFAULT_LANG else base.with_name(lang + ".html")


def render_page(lang, base, parsed, trans, total, grade_cnt, link_total, rev, rev_date):
    translated = 0
    sec_toc = []
    sec_html = []
    sec_next = []
    jump_opts = []

    for n, title, intro, entries in parsed:
        st = trans.get(src_key(section_src(title, intro)), {})
        title = st.get("title") or title
        intro_text = st.get("intro") or " ".join(intro)
        cards = []
        links = []
        for e in entries:
            e, hit = localize(e, trans)
            translated += hit
            cards.append(render_entry(e, n, lang))
            r = ratio_of(parse_tags(e["tags_raw"]))
            short = toc_title(e["title"])
            links.append('<a href="#s%d-%d" title="%s"><span class="dot d%d"></span>'
                         '<i>%d</i><span>%s</span></a>'
                         % (n, e["no"], html.escape(e["title"], quote=True),
                            RATIO_ORDER.get(r, 2), e["no"], html.escape(short)))
        count = tr(lang, "n.items", len(entries))
        # 目录每节可折叠：标题本身是跳转链接，点右侧箭头才展开；读到哪节由 JS 自动展开哪节
        sec_toc.append('<details class="grp" data-sec="sec%d"><summary class="gt"><a href="#sec%d">%s</a>'
                       '<small>%s</small></summary><div class="links">%s</div></details>'
                       % (n, n, inline(title), count, "".join(links)))
        # 节号挂在左侧页边，标题只留名字
        m = re.match(r"\s*(\d+)\s*[.、．]\s*(.+)", title)
        sec_no, sec_name = (m.group(1), m.group(2)) if m else (str(n), title)
        # 不带 </section>：下面循环结束后再补「下一节」链接
        sec_html.append(
            '<section id="sec%d"><div class="sec-h"><span class="sn">%s</span><h2>%s</h2>'
            '<span class="meta">%s</span></div>%s%s'
            % (n, sec_no, inline(sec_name), count, render_intro(intro_text), "".join(cards)))
        sec_next.append('<a class="next" href="#sec%d"><small>%s</small>%s</a>' % (n, tr(lang, "next"), inline(title)))
        jump_opts.append('<option value="sec%d">%s</option>' % (n, html.escape(title)))

    # 每节末尾指向下一节，最后一节没有
    sec_html = [h + (sec_next[i + 1] if i + 1 < len(sec_next) else "") + "</section>"
                for i, h in enumerate(sec_html)]

    scope = tr(lang, "scope." + SCOPE_KEY, SCOPE_ARG)
    head = ('<!DOCTYPE html><html lang="%s" data-theme="light"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="color-scheme" content="light dark">'
            '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#fcfcfc">'
            '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#18191b">'
            '<meta name="description" content="%s">'
            '<link rel="icon" href="%s">'
            '<title>%s</title><style>%s</style><script>%s</script></head><body>'
            % (LANGS[lang]["tag"],
               html.escape(tr(lang, "doc.desc." + SCOPE_KEY, SCOPE_ARG, total), quote=True),
               FAVICON, html.escape(tr(lang, "doc.title." + SCOPE_KEY, SCOPE_ARG)), CSS, THEME_JS))

    # 语言下拉：value 是目标语言那一页的文件名；autocomplete=off 防止浏览器回退时还原成旧选项
    lang_opts = "".join('<option value="%s"%s>%s</option>'
                        % (page_path(base, code).name, " selected" if code == lang else "", v["name"])
                        for code, v in LANGS.items())
    # 标志就是条目里那个三格性价比刻度；三个筛选互斥，做成一组分段按钮
    bar = ('<header class="bar">'
           '<button class="icon" id="toc-btn" title="%s" aria-label="%s" aria-expanded="true">'
           '<svg viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9.5 4.5v15"/></svg></button>'
           '<h1><span class="logo" aria-hidden="true"><i></i><i></i><i></i></span>'
           '%s<small>%s</small></h1>'
           '<select class="jump" id="jump" aria-label="%s">%s</select>'
           '<div class="spacer"></div>'
           '<div class="seg">'
           '<button id="f-all">%s</button>'
           '<button id="f-a">%s</button>'
           '<button id="f-plain">%s</button></div>'
           '<div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/>'
           '<path d="M20 20l-3.5-3.5"/></svg>'
           '<input id="q" type="search" placeholder="%s" autocomplete="off">'
           '<kbd>/</kbd></div>'
           '<span class="count" id="cnt">%s</span>'
           '<button class="icon" id="theme" title="%s" aria-label="%s">'
           '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z"/></svg></button>'
           '<select class="lang" id="lang" aria-label="%s" autocomplete="off">%s</select></header>' % (
               tr(lang, "toc"), tr(lang, "toc"),
               tr(lang, "title"), scope, tr(lang, "jump.aria"), "".join(jump_opts),
               tr(lang, "filter.all"), tr(lang, "filter.a"), tr(lang, "filter.plain"),
               tr(lang, "search.ph"), tr(lang, "count", total, total), tr(lang, "theme"), tr(lang, "theme"),
               tr(lang, "lang.aria"), lang_opts))

    upstream_link = '<a href="%s" target="_blank" rel="noopener">eternity4719/HowToLiveBetter</a>' % UPSTREAM
    if rev:
        rev_html = '<span style="font-family:var(--mono)">%s</span>' % rev
        footer_1 = tr(lang, "footer.1.rev", upstream_link, rev_html, rev_date)
    else:
        footer_1 = tr(lang, "footer.1", upstream_link)

    notes = [footer_1,
             tr(lang, "footer.2", total, grade_cnt["A"], grade_cnt["B"], grade_cnt["C"], link_total)]
    if lang != SOURCE_LANG:
        notes.append(
            tr(lang, "footer.tr.all", total) if translated == total
            else tr(lang, "footer.tr.some", translated, total) if translated
            else tr(lang, "footer.tr.none"))
    notes.append(tr(lang, "footer.3"))
    footer = "<footer>%s</footer>" % "<br>".join(notes)

    shell = ('<div class="shell"><aside class="toc" id="toc">%s</aside><div class="scrim"></div><main>%s'
             '<div class="empty hidden" id="empty"><p>%s</p><p>%s</p></div>%s'
             '</main></div>'
             '<button id="top" title="%s" aria-label="%s">↑</button>'
             % ("".join(sec_toc), "".join(sec_html), tr(lang, "empty"), tr(lang, "empty.hint"), footer,
                tr(lang, "top"), tr(lang, "top")))
    shell += ('<div id="g-help" class="help" popover><h4>%s</h4>'
              '<button class="icon close" popovertarget="g-help" popovertargetaction="hide" aria-label="%s">×</button>'
              '<dl>%s</dl><p>%s</p></div>'
              % (tr(lang, "grade.help.title"), tr(lang, "close"),
                 "".join('<div><dt><span class="grade g%s">%s</span></dt><dd>%s</dd></div>'
                         % (g, g, tr(lang, "grade.help." + g)) for g in "ABC"),
                 tr(lang, "grade.help.note")))

    # 搜索结果计数的句式随页面语言；"</" 转义，避免字符串里出现 </script> 提前结束脚本
    count_js = "const COUNT_TPL=%s;" % json.dumps(tr(lang, "count", "{0}", "{1}"), ensure_ascii=False).replace("</", "<\\/")

    # 注意：JS 字符串只含脚本体，<script> 开合标签在这里拼。
    # 之前漏了开标签，导致整段 JS 被当纯文本渲染在页面底部、脚本从未执行。
    return head + bar + shell + "<script>" + count_js + JS + "</script></body></html>"


# 各语言的数字写法 (千分位, 小数点)；原文（中文）按英文写法读
NUM_FORMAT = {"pt": (".", ","), "en": (",", "."), "zh": (",", ".")}
# 原文里「数字+单位」在译文里可能换算成别的数：10 万 -> 100 mil / 100.000，170 万 -> 1,7 milhão
UNIT_EQUIV = {"千": (1000, 1), "万": (10 ** 4, 10, Decimal("0.01")), "亿": (10 ** 8, 100, Decimal("0.1"))}


def number_forms(text, lang):
    """文中每个数：[(值, {值, 单位换算后的值…}), ...]，后者是各自可接受的写法。千分位去掉、小数点统一。"""
    thou, dec = NUM_FORMAT[lang]
    grouped = r"\d{1,3}(?:%s\d{3})+(?:%s\d+)?" % (re.escape(thou), re.escape(dec))
    out = []
    for m in re.finditer(r"\d+(?:[.,]\d+)*", text):
        t = m.group(0)
        try:
            v = Decimal((t.replace(thou, "") if re.fullmatch(grouped, t) else t).replace(dec, "."))
        except ArithmeticError:  # 1.2.3 这类版本号之类，不当数字比
            continue
        unit = text[m.end():m.end() + 2].lstrip()[:1]
        out.append((v, {v, *(v * Decimal(f) for f in UNIT_EQUIV.get(unit, ()))}))
    return out


def check_translations(lang, parsed):
    """对照原文检查译文，只提示不改动：数字/链接/加粗标记有没有丢或多出来、字段是否齐全、
    原文是否已被上游改过（改过的译文不会显示）。数字不一致不一定是错（如 17.4 -> 17,4 已自动归一），请人工判断。"""
    flagged = 0
    for n, title, intro, entries in parsed:
        path = TRANSLATIONS_DIR / lang / ("%02d.json" % n)
        if not path.exists():
            print("第 %d 节：没有 %s" % (n, path.relative_to(HERE)))
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        items = ([data["section"]] if "section" in data else []) + data.get("entries", [])
        current = {src_key(section_src(title, intro))} | {src_key(entry_src(e)) for e in entries}
        have = {src_key(it["src"]) for it in items}
        for it in items:
            src, tr_ = it["src"], it["tr"]
            msgs = []
            if src_key(src) not in current:
                msgs.append("原文已变，这条译文不会显示")
            for k, v in src.items():
                if not v:
                    continue
                t = tr_.get(k)
                if not t:
                    msgs.append("%s: 缺译文" % k)
                    continue
                found = {x for _, forms in number_forms(t, lang) for x in forms}
                wanted = number_forms(v, "zh")
                miss = [x for x, forms in wanted if not forms & found]
                extra = found - {x for _, forms in wanted for x in forms}
                if miss:
                    msgs.append("%s: 数字缺 %s" % (k, sorted(miss)))
                if extra:
                    msgs.append("%s: 多出数字 %s" % (k, sorted(extra)))
                urls = re.findall(r"https?://[^\s)），。；]+", v)
                if [u for u in urls if u not in t]:
                    msgs.append("%s: 链接缺 %s" % (k, [u for u in urls if u not in t]))
                if v.count("**") != t.count("**"):
                    msgs.append("%s: ** 加粗标记数量不同" % k)
            msgs += ["%s: 多余字段" % k for k in tr_ if k not in src]
            if msgs:
                flagged += 1
                print("第 %d 节 · %s：" % (n, src["title"][:30]))
                for m in msgs:
                    print("    " + m)
        done = sum(src_key(entry_src(e)) in have for e in entries)
        print("第 %d 节：%d / %d 条有译文，%d 条有提示" % (n, done, len(entries), flagged))


def print_todo(lang, parsed):
    """打印某一节里还没有译文的条目骨架（src 已填、tr 为空），译完存成 translations/<lang>/NN.json。"""
    if len(parsed) != 1:
        raise SystemExit("--todo 一次只处理一节，请只给一个节号")
    _, title, intro, entries = parsed[0]
    trans = load_translations(lang)
    todo = {}
    if src_key(section_src(title, intro)) not in trans:
        todo["section"] = {"src": section_src(title, intro), "tr": {}}
    todo["entries"] = [{"src": entry_src(e), "tr": {}} for e in entries if src_key(entry_src(e)) not in trans]
    print(json.dumps(todo, ensure_ascii=False, indent=2))


def main():
    parsed = [(n,) + parse(find_file(n)) for n in SECTIONS]
    if ARGS.todo:
        print_todo(ARGS.todo, parsed)
        return
    if ARGS.check:
        check_translations(ARGS.check, parsed)
        return
    total = 0
    grade_cnt = {"A": 0, "B": 0, "C": 0}
    link_total = 0
    for _, _, _, entries in parsed:
        for e in entries:
            g = (e["fields"].get("证据等级") or "?").strip()[:1]
            if g in grade_cnt:
                grade_cnt[g] += 1
            total += 1
            link_total += link_count(e["fields"].get("来源", "")) + link_count(e["fields"].get("备注", ""))

    rev, rev_date = source_rev()

    if ARGS.out:
        base = Path(ARGS.out)
        if not base.is_absolute():
            base = HERE / base
    else:
        base = HERE / ("高性价比人生指南_%s.html" % "_".join("第%d节" % n for n in SECTIONS))

    for lang in LANGS:
        trans = {} if lang == SOURCE_LANG else load_translations(lang)
        out = render_page(lang, base, parsed, trans, total, grade_cnt, link_total, rev, rev_date)
        name = page_path(base, lang)
        name.write_text(out, encoding="utf-8")
        print("输出：%s  (%d 字节)" % (name, len(out.encode("utf-8"))))
    print("范围 %s ｜ 节数 %d ｜ 条目 %d ｜ A %d B %d C %d ｜ 外链 %d"
          % (SCOPE, len(SECTIONS), total, grade_cnt["A"], grade_cnt["B"], grade_cnt["C"], link_total))


if __name__ == "__main__":
    main()
