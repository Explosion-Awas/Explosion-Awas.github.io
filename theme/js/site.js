/* Explosion Awas — lamps, code blocks, reading progress, and client-side search.
   No dependencies, no network calls except the local search index. */

(() => {
  "use strict";

  const doc = document;
  const root = doc.documentElement;
  const langPrefix = (root.lang || "en").toLowerCase().startsWith("zh") ? "/zh" : "";

  /* ---------------------------------------------------------------------- */
  /* lamps (theme)                                                          */
  /* ---------------------------------------------------------------------- */
  const themeBtn = doc.querySelector("[data-theme-toggle]");
  const metaTheme = doc.querySelector('meta[name="theme-color"]');

  function paintTheme() {
    const dark = root.dataset.theme === "dark";
    if (metaTheme) metaTheme.setAttribute("content", dark ? "#12100d" : "#f3e9d7");
    if (themeBtn) themeBtn.setAttribute("aria-pressed", String(dark));
  }
  paintTheme();

  themeBtn?.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    paintTheme();
  });

  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (event) => {
    try { if (localStorage.getItem("theme")) return; } catch (e) {}
    root.dataset.theme = event.matches ? "dark" : "light";
    paintTheme();
  });

  /* ---------------------------------------------------------------------- */
  /* math                                                                   */
  /* ---------------------------------------------------------------------- */
  if (window.renderMathInElement) {
    try {
      window.renderMathInElement(doc.body, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false },
          { left: "$", right: "$", display: false },
        ],
        throwOnError: false,
        errorColor: "#b8430f",
        ignoredClasses: ["highlight", "codeblock", "katex"],
      });
    } catch (error) {
      console.warn("math rendering skipped:", error);
    }
  }

  /* ---------------------------------------------------------------------- */
  /* code blocks: label + copy                                              */
  /* ---------------------------------------------------------------------- */
  doc.querySelectorAll(".prose .highlight").forEach((block) => {
    const pre = block.querySelector("pre");
    if (!pre) return;
    const code = pre.querySelector("code");
    const lang =
      block.dataset.lang ||
      [...(code?.classList || [])].filter((c) => c.startsWith("language-")).map((c) => c.slice(9))[0] ||
      "";

    const wrap = doc.createElement("div");
    wrap.className = "codeblock";
    block.parentNode.insertBefore(wrap, block);
    wrap.appendChild(block);

    const bar = doc.createElement("div");
    bar.className = "codeblock-bar";
    const label = doc.createElement("span");
    label.textContent = lang || "code";
    const copy = doc.createElement("button");
    copy.type = "button";
    copy.className = "codeblock-copy";
    copy.textContent = "copy";
    copy.setAttribute("aria-label", "Copy code to clipboard");
    bar.append(label, copy);
    wrap.insertBefore(bar, block);

    copy.addEventListener("click", async () => {
      const text = code ? code.innerText : pre.innerText;
      try {
        await navigator.clipboard.writeText(text);
        copy.textContent = "copied";
        copy.classList.add("is-done");
      } catch (error) {
        copy.textContent = "failed";
      }
      setTimeout(() => {
        copy.textContent = "copy";
        copy.classList.remove("is-done");
      }, 1600);
    });
  });

  /* ---------------------------------------------------------------------- */
  /* reading progress                                                       */
  /* ---------------------------------------------------------------------- */
  const bar = doc.getElementById("read-progress-bar");
  const prose = doc.querySelector("[data-prose]");
  if (bar && prose) {
    let ticking = false;
    const update = () => {
      const rect = prose.getBoundingClientRect();
      const start = rect.top + window.scrollY - 120;
      const total = prose.offsetHeight - window.innerHeight * 0.55;
      const value = Math.min(1, Math.max(0, (window.scrollY - start) / Math.max(total, 1)));
      bar.style.transform = `scaleX(${value})`;
      ticking = false;
    };
    window.addEventListener("scroll", () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    }, { passive: true });
    update();
  }

  /* ---------------------------------------------------------------------- */
  /* table of contents highlight                                            */
  /* ---------------------------------------------------------------------- */
  const tocLinks = [...doc.querySelectorAll(".toc a")];
  if (tocLinks.length) {
    const targets = tocLinks
      .map((a) => ({ link: a, node: doc.getElementById(decodeURIComponent(a.hash.slice(1))) }))
      .filter((x) => x.node);
    const seen = new Map();
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const match = targets.find((t) => t.node === entry.target);
        if (match) seen.set(match.link, entry.isIntersecting);
      });
      const active = targets.find((t) => seen.get(t.link));
      tocLinks.forEach((a) => a.classList.remove("is-active"));
      if (active) active.link.classList.add("is-active");
    }, { rootMargin: "-96px 0px -70% 0px", threshold: 0 });
    targets.forEach((t) => observer.observe(t.node));
  }

  /* ---------------------------------------------------------------------- */
  /* search                                                                 */
  /* ---------------------------------------------------------------------- */
  const overlay = doc.getElementById("search");
  const input = doc.getElementById("search-input");
  const results = doc.getElementById("search-results");
  const pageInput = doc.getElementById("page-search-input");
  const pageResults = doc.getElementById("page-search-results");
  let index = null;
  let cursor = -1;

  const normalize = (text) =>
    (text || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "");

  async function loadIndex() {
    if (index) return index;
    const response = await fetch(`${langPrefix}/search-index.json`);
    index = await response.json();
    return index;
  }

  function score(entry, terms) {
    const title = normalize(entry.t);
    const summary = normalize(entry.s);
    const tags = normalize((entry.g || []).join(" "));
    let total = 0;
    for (const term of terms) {
      let hit = 0;
      if (title.includes(term)) hit += title.startsWith(term) ? 12 : 7;
      if (tags.includes(term)) hit += 4;
      if (summary.includes(term)) hit += 2;
      if (!hit) return 0;
      total += hit;
    }
    return total;
  }

  function render(entries, container, query) {
    if (!container) return;
    const empty = container.dataset.empty || "Start typing.";
    const miss = container.dataset.miss || `Nothing matches “${query}”.`;
    container.innerHTML = "";
    if (!entries.length) {
      const note = doc.createElement("div");
      note.className = "search-empty";
      note.textContent = query ? miss.replace("{q}", query) : empty;
      container.appendChild(note);
      return;
    }
    entries.forEach((entry, i) => {
      const link = doc.createElement("a");
      link.href = entry.u;
      link.innerHTML = `<span class="sr-title"></span><span class="sr-kind"></span><span class="sr-sub"></span>`;
      link.querySelector(".sr-title").textContent = entry.t;
      link.querySelector(".sr-kind").textContent = entry.k;
      link.querySelector(".sr-sub").textContent = entry.s || entry.u;
      if (i === 0) link.setAttribute("aria-selected", "true");
      container.appendChild(link);
    });
  }

  async function search(query, container) {
    const terms = normalize(query).split(/\s+/).filter(Boolean);
    if (!terms.length) {
      render([], container, "");
      return;
    }
    const data = await loadIndex();
    const hits = data
      .map((entry) => ({ entry, value: score(entry, terms) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
      .map((x) => x.entry);
    render(hits, container, query);
    cursor = -1;
  }

  function move(delta) {
    if (!results) return;
    const links = [...results.querySelectorAll("a")];
    if (!links.length) return;
    cursor = (cursor + delta + links.length) % links.length;
    links.forEach((a, i) => a.setAttribute("aria-selected", String(i === cursor)));
    links[cursor].scrollIntoView({ block: "nearest" });
  }

  function openOverlay() {
    if (!overlay) return;
    overlay.hidden = false;
    doc.body.style.overflow = "hidden";
    input?.focus();
    input?.select();
    if (input && input.value) search(input.value, results);
  }

  function closeOverlay() {
    if (!overlay) return;
    overlay.hidden = true;
    doc.body.style.overflow = "";
    cursor = -1;
  }

  doc.querySelectorAll("[data-search-open]").forEach((btn) => btn.addEventListener("click", openOverlay));
  overlay?.addEventListener("click", (event) => {
    if (event.target === overlay) closeOverlay();
  });

  input?.addEventListener("input", (event) => search(event.target.value, results));

  doc.addEventListener("keydown", (event) => {
    const typing = /^(input|textarea|select)$/i.test(event.target.tagName) || event.target.isContentEditable;
    if (event.key === "/" && !typing && overlay?.hidden) {
      event.preventDefault();
      openOverlay();
      return;
    }
    if (!overlay || overlay.hidden) return;
    if (event.key === "Escape") closeOverlay();
    if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
    if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
    if (event.key === "Enter") {
      const selected = results?.querySelector('a[aria-selected="true"]');
      if (selected) window.location.href = selected.href;
    }
  });

  if (pageInput) {
    pageInput.addEventListener("input", (event) => search(event.target.value, pageResults));
    const query = new URLSearchParams(location.search).get("q");
    if (query) {
      pageInput.value = query;
      search(pageInput.value, pageResults);
    }
  }
})();
