"""Publication-page integration tests; fixtures and output stay in Hermes scratch.

Run directly: python -B tests/test_publication_pages.py -v
"""

from __future__ import annotations

import importlib.util
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
import unittest
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
BLOG = Path(__file__).resolve().parents[1]


class Element:
    def __init__(self, tag, attrs, ancestors):
        self.tag = tag
        self.attrs = dict(attrs)
        self.ancestors = tuple(ancestors)
        self.content = []

    @property
    def text(self):
        return "".join(self.content)


class Markup(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.stack = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs, self.stack)
        self.elements.append(element)
        if tag not in self.VOID:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for element in self.stack:
            element.content.append(data)

    def select(self, tag=None, css_class=None):
        return [element for element in self.elements
                if (tag is None or element.tag == tag)
                and (css_class is None or css_class in element.attrs.get("class", "").split())]


class PublicationPagesTests(unittest.TestCase):
    def setUp(self):
        if os.name == "nt":
            scratch = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "hermes/cache/scratch"
        else:
            scratch = Path(os.environ.get("TMPDIR", Path.home() / ".hermes/cache/scratch"))
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="publication-pages-", dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copy2(BLOG / "site.toml", self.root / "site.toml")

        spec = importlib.util.spec_from_file_location("_publication_build_test", BLOG / "build.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load the site generator")
        self.site: Any = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.site
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(self.site)
        self.site.ROOT = self.root
        self.site.CONTENT = self.root / "content"
        self.site.THEME = BLOG / "theme"
        self.site.OUT = self.root / "public"

    def add_doc(self, lang, folder, slug, front_matter, body=""):
        path = self.site.CONTENT / lang / folder / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\n{front_matter.strip()}\n---\n\n{body}", encoding="utf-8")

    def output(self, url):
        path = self.site.OUT / url.lstrip("/") / "index.html"
        self.assertTrue(path.is_file(), f"missing detail page: {url}")
        return path.read_text(encoding="utf-8")

    def test_bilingual_paper_detail_pages_are_written(self):
        for lang, title in (("en", "A paper <test>"), ("zh", "论文 <测试>")):
            self.add_doc(lang, "papers", "fixture-paper", f"title: {title}")
        self.assertEqual(self.site.build(verbose=False), 0)
        for lang, prefix, title, locale, other in (
            ("en", "", "A paper &lt;test&gt;", "en", "/zh"),
            ("zh", "/zh", "论文 &lt;测试&gt;", "zh-CN", ""),
        ):
            with self.subTest(lang=lang):
                rendered = self.output(f"{prefix}/papers/fixture-paper/")
                self.assertIn(f'<html lang="{locale}"', rendered)
                self.assertIn(f'<h1 class="art-title">{title}</h1>', rendered)
                self.assertIn(f'<link rel="canonical" href="https://explosion-awas.github.io{prefix}/papers/fixture-paper/">', rendered)
                self.assertIn(f'href="{other}/papers/fixture-paper/" hreflang=', rendered)
                self.assertIn(f'href="{prefix}/papers/fixture-paper/"', self.output(f"{prefix}/papers/"))

    def test_paper_details_are_in_sitemap(self):
        for lang in ("en", "zh"):
            self.add_doc(lang, "papers", "indexed-paper", "title: Indexed paper\ndate: 2026-10-24", "## Abstract\n\nPublic result.")
            self.add_doc(lang, "papers", "draft-paper", "title: Draft paper\ndraft: true")
            self.add_doc(lang, "papers", "_template", "title: Template paper")
        self.site.build(verbose=False)
        sitemap = ET.parse(self.site.OUT / "sitemap.xml")
        locations = {element.text or "" for element in sitemap.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")}
        paper_locations = {url for url in locations if "/papers/" in url and not url.endswith("/papers/")}
        self.assertEqual(paper_locations, {
            "https://explosion-awas.github.io/papers/indexed-paper/",
            "https://explosion-awas.github.io/zh/papers/indexed-paper/",
        }, "published paper detail URLs belong in the sitemap")
        for prefix in ("", "/zh"):
            index = json.loads((self.site.OUT / prefix.lstrip("/") / "search-index.json").read_text(encoding="utf-8"))
            self.assertEqual([item["u"] for item in index], [f"{prefix}/papers/indexed-paper/"])
            self.output(f"{prefix}/papers/indexed-paper/")
            self.assertFalse((self.site.OUT / prefix.lstrip("/") / "papers/draft-paper").exists())
            self.assertFalse((self.site.OUT / prefix.lstrip("/") / "papers/_template").exists())

    def test_project_cards_have_sibling_title_and_repository_links(self):
        repo = "https://code.example.invalid/project?tab=readme&version=1"
        for lang in ("en", "zh"):
            self.add_doc(lang, "projects", "with-repo",
                         f"title: With repository\nsummary: Existing summary\nrepo: {repo}\n"
                         "status: archived\ntags: [code, numerics]", "## Reproduce\n\nRun the code.")
            self.add_doc(lang, "projects", "no-repo", 'title: No repository\nrepo: ""')
        self.site.build(verbose=False)
        for prefix in ("", "/zh"):
            for index in (f"{prefix}/projects/", f"{prefix}/"):
                with self.subTest(index=index):
                    rendered = Markup(self.output(index))
                    cards = rendered.select(css_class="card")
                    self.assertEqual(len(cards), 2)
                    repo_buttons = rendered.select("a", "btn")
                    repo_buttons = [e for e in repo_buttons if e.text == "Repository"]
                    self.assertEqual(len(repo_buttons), 1, "project index needs an explicit Repository button")
                    self.assertEqual(repo_buttons[0].attrs["href"], repo)
                    self.assertEqual(repo_buttons[0].attrs["target"], "_blank")
                    self.assertIn("noopener", repo_buttons[0].attrs["rel"].split())
                    self.assertTrue(all(card.tag != "a" for card in cards), "cards must not wrap separate links in an anchor")
                    for card in cards:
                        headings = [e for e in rendered.select("h3", "card-title") if card in e.ancestors]
                        self.assertEqual(len(headings), 1)
                        title_links = [e for e in rendered.select("a") if headings[0] in e.ancestors]
                        self.assertEqual(len(title_links), 1, "keep the project title linked to its detail page")
                        slug = "with-repo" if headings[0].text == "With repository" else "no-repo"
                        self.assertEqual(title_links[0].attrs["href"], f"{prefix}/projects/{slug}/")
                        repository = [e for e in repo_buttons if card in e.ancestors]
                        self.assertEqual(len(repository), int(slug == "with-repo"))
                    self.assertTrue(all(not any(parent.tag == "a" for parent in link.ancestors)
                                        for link in rendered.select("a")), "nested anchors are invalid")
                    self.assertEqual(rendered.select("p", "card-sum")[0].text, "Existing summary")

    def test_paper_math_assets_follow_rendered_math(self):
        bodies = {
            "equations": "## Equation\n\nInline $x_1$ stays intact.\n\n$$x_1^2 = 1$$\n",
            "plain": "## Notes\n\nNo equation, even with a price of $5.\n",
            "code": '## Code\n\n`$not_math$`\n\n```sh\nprintf "$HOME"\n```\n',
        }
        for lang in ("en", "zh"):
            for slug, body in bodies.items():
                self.add_doc(lang, "papers", slug, f"title: {slug}", body)
        self.site.build(verbose=False)
        expected = {"/theme/katex/katex.min.css", "/theme/katex/katex.min.js", "/theme/katex/auto-render.min.js"}
        for prefix in ("", "/zh"):
            for slug in bodies:
                with self.subTest(prefix=prefix, slug=slug):
                    text = self.output(f"{prefix}/papers/{slug}/")
                    rendered = Markup(text)
                    resources = {e.attrs.get("src", e.attrs.get("href", "")) for e in rendered.elements if e.tag in ("script", "link")}
                    resources = {url for url in resources if url.startswith("/theme/katex/")}
                    self.assertEqual(resources, expected if slug == "equations" else set(),
                                     "load local math assets only when the paper body contains rendered math")
                    self.assertNotIn("MTHPH", text)
                    self.assertNotIn("CDEPH", text)
                    if slug == "equations":
                        self.assertEqual(rendered.select(css_class="math--inline")[0].text, "$x_1$")
                        self.assertEqual(rendered.select(css_class="math--display")[0].text, "$$x_1^2 = 1$$")
                    else:
                        self.assertEqual(rendered.select(css_class="math"), [])

    def test_paper_resource_buttons_match_available_links(self):
        available = {
            "PDF": "https://papers.example.invalid/manuscript.pdf?download=1&version=2",
            "Code": "https://code.example.invalid/repository",
            "DOI": "https://doi.org/10.0000/example",
            "arXiv": "https://arxiv.org/abs/0000.00000",
        }
        all_links = "\n".join(f"{key.lower()}: {value}" for key, value in available.items())
        for lang in ("en", "zh"):
            self.add_doc(lang, "papers", "all-links", f"title: All links\n{all_links}")
            self.add_doc(lang, "papers", "pdf-only",
                         f'title: PDF only\npdf: {available["PDF"]}\ncode: ""\ndoi: ""\narxiv: ""')
            self.add_doc(lang, "papers", "no-links", "title: No links")
        self.site.build(verbose=False)
        for prefix in ("", "/zh"):
            for slug, expected in (("all-links", available), ("pdf-only", {"PDF": available["PDF"]}), ("no-links", {})):
                with self.subTest(prefix=prefix, slug=slug):
                    text = self.output(f"{prefix}/papers/{slug}/")
                    rendered = Markup(text)
                    actions = rendered.select("div", "art-actions")
                    self.assertEqual(len(actions), int(bool(expected)), "resource buttons must match supplied links")
                    buttons = [e for e in rendered.select("a", "btn") if actions and actions[0] in e.ancestors]
                    self.assertEqual({e.text: e.attrs["href"] for e in buttons}, expected)
                    for button in buttons:
                        self.assertIn("btn--ghost", button.attrs["class"].split())
                        self.assertEqual(button.attrs["target"], "_blank")
                        self.assertIn("noopener", button.attrs["rel"].split())
                    if expected:
                        self.assertIn("download=1&amp;version=2", text)

    def test_paper_toc_links_to_rendered_sections(self):
        for lang in ("en", "zh"):
            self.add_doc(lang, "papers", "sections-paper", "title: Sections paper",
                         "## Abstract\n\nResult.\n\n## Method & limitations\n\nMethod.\n\n"
                         "### Validation\n\nChecks.\n")
            self.add_doc(lang, "papers", "no-sections", "title: No sections", "Plain prose.")
        self.site.build(verbose=False)
        for prefix, label in (("", "Contents"), ("/zh", "目录")):
            with self.subTest(prefix=prefix):
                rendered = Markup(self.output(f"{prefix}/papers/sections-paper/"))
                navigation = rendered.select("nav", "toc")
                self.assertEqual(len(navigation), 1, "paper detail needs a section TOC")
                self.assertEqual(navigation[0].attrs["aria-label"], label)
                links = [e.attrs["href"] for e in rendered.select("a") if navigation[0] in e.ancestors]
                self.assertEqual(links, ["#abstract", "#method-limitations", "#validation"])
                ids = {e.attrs.get("id") for e in rendered.elements}
                self.assertTrue(all(href[1:] in ids for href in links), "TOC targets must exist")
                plain = Markup(self.output(f"{prefix}/papers/no-sections/"))
                self.assertEqual(plain.select("nav", "toc"), [], "omit a TOC with no sections")

    def test_paper_metadata_displays_only_supplied_values(self):
        for lang in ("en", "zh"):
            self.add_doc(lang, "papers", "metadata-paper",
                         "title: Metadata paper\nauthors: A. Author & B. <Contributor>\n"
                         "venue: Independent manuscript\nyear: 2026\nstatus: in-prep")
            self.add_doc(lang, "papers", "absent-metadata", "title: No metadata")
            self.add_doc(lang, "papers", "blank-metadata",
                         'title: Blank metadata\nauthors: ""\nvenue: ""\nyear: ""\nstatus: ""')
        self.site.build(verbose=False)
        for prefix, labels, status in (
            ("", ("Authors", "Venue", "Year", "Status"), "in prep"),
            ("/zh", ("作者", "刊物 / 会议", "年份", "状态"), "准备中"),
        ):
            with self.subTest(prefix=prefix):
                rendered = Markup(self.output(f"{prefix}/papers/metadata-paper/"))
                metadata = rendered.select("dl", "art-meta")
                self.assertEqual(len(metadata), 1, "paper detail must show supplied bibliographic metadata")
                terms = [e.text for e in rendered.select("dt") if metadata[0] in e.ancestors]
                values = [e.text for e in rendered.select("dd") if metadata[0] in e.ancestors]
                self.assertEqual(dict(zip(terms, values)), dict(zip(labels, (
                    "A. Author & B. <Contributor>", "Independent manuscript", "2026", status))))
                self.assertEqual(rendered.select(css_class="chip--in-prep")[0].text, status)
                for slug in ("absent-metadata", "blank-metadata"):
                    minimal = Markup(self.output(f"{prefix}/papers/{slug}/"))
                    self.assertEqual(minimal.select("dl", "art-meta"), [], "do not invent missing metadata")
                    self.assertEqual(minimal.select(css_class="chip"), [], "do not assume a publication status")

    def test_paper_body_renders_markdown_in_existing_article_layout(self):
        for lang in ("en", "zh"):
            self.add_doc(lang, "papers", "body-paper", "title: Body paper\nsummary: A <summary>",
                         "## Abstract\n\nA **rendered result**, not raw Markdown.\n\n"
                         "```python\nprint('result')\n```\n\n"
                         "| Item | Value |\n| --- | --- |\n| result | 1 |\n")
        self.site.build(verbose=False)
        for prefix in ("", "/zh"):
            with self.subTest(prefix=prefix):
                rendered = Markup(self.output(f"{prefix}/papers/body-paper/"))
                prose = rendered.select("div", "prose")
                self.assertEqual(len(prose), 1, "paper detail must render its Markdown body")
                self.assertIn("data-prose", prose[0].attrs)
                self.assertEqual(rendered.select("p", "art-lede")[0].text, "A <summary>")
                self.assertEqual(rendered.select("strong")[0].text, "rendered result")
                self.assertNotIn("**rendered result**", prose[0].text)
                self.assertEqual(rendered.select("div", "highlight")[0].attrs["data-lang"], "python")
                self.assertEqual(len(rendered.select("div", "table-wrap")), 1)
                self.assertEqual(len(rendered.select("div", "art-grid")), 1)


if __name__ == "__main__":
    unittest.main()
