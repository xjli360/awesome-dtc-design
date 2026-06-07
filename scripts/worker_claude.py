#!/usr/bin/env python3
"""
Autonomous worker — invokes Claude (`claude -p`) per site to generate DESIGN.md.

Same architecture as worker.py but uses Claude CLI instead of DeepSeek API.
- Pre-extracts HTML hints with curl (cheap, deterministic)
- Calls `claude -p --model <MODEL> --bare` for each site (uses subscription, no API billing)
- Captures output, validates, writes file, updates state

Env vars:
  CLAUDE_MODEL      (default 'opus' — also accepts 'sonnet', 'haiku', or full IDs)
  WORKERS           (default 5)
  LIMIT             (default 0 = process all pending)
"""

import os
import re
import sys
import time
import json
import subprocess
import threading
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "_state" / "queue.txt"
DONE = ROOT / "_state" / "done.txt"
FAILED = ROOT / "_state" / "failed.txt"
DESIGN_DIR = ROOT / "design-md"
REFERENCE = ROOT / "scripts" / "REFERENCE_DESIGN.md"

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "opus")
MAX_WORKERS = int(os.environ.get("WORKERS", "5"))
LIMIT = int(os.environ.get("LIMIT", "0"))
PER_CALL_TIMEOUT = int(os.environ.get("PER_CALL_TIMEOUT", "360"))  # 6 min cap

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

state_lock = threading.Lock()
print_lock = threading.Lock()


def log(msg: str):
    with print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_done() -> set:
    if not DONE.exists():
        return set()
    return {ln.strip() for ln in DONE.read_text().splitlines() if ln.strip()}


def load_failed_slugs() -> set:
    if not FAILED.exists():
        return set()
    out = set()
    for ln in FAILED.read_text().splitlines():
        parts = ln.split("\t")
        if parts:
            out.add(parts[0].strip())
    return out


def load_queue():
    rows = []
    for ln in QUEUE.read_text().splitlines():
        parts = ln.split("\t")
        if len(parts) >= 4:
            rows.append({
                "slug": parts[0],
                "brand_name": parts[1],
                "url": parts[2],
                "category": parts[3],
            })
    return rows


def append_done(slug: str):
    with state_lock, DONE.open("a", encoding="utf-8") as f:
        f.write(slug + "\n")


def append_failed(slug: str, reason: str, url: str):
    with state_lock, FAILED.open("a", encoding="utf-8") as f:
        f.write(f"{slug}\t{reason}\t{url}\n")


def fetch(url: str, timeout: int = 25) -> str:
    try:
        result = subprocess.run(
            [
                "curl", "-sL", "--compressed",
                "--max-time", str(timeout),
                "-A", UA,
                "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "-H", "Accept-Language: en-US,en;q=0.9",
                "-H", "Cache-Control: no-cache",
                "-H", "Sec-Fetch-Dest: document",
                "-H", "Sec-Fetch-Mode: navigate",
                "-H", "Sec-Fetch-Site: none",
                "-H", "Upgrade-Insecure-Requests: 1",
                url,
            ],
            capture_output=True,
            timeout=timeout + 5,
        )
        if result.returncode == 0 and result.stdout:
            text = result.stdout.decode("utf-8", errors="replace")
            if len(text) > 200:
                return text
        return ""
    except Exception:
        return ""


HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
FONT_RE = re.compile(r"font-family\s*:\s*([^;{}]+)[;}]", re.IGNORECASE)
CSS_HREF_RE = re.compile(r'<link[^>]+rel=["\']?stylesheet["\']?[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
THEME_RE = re.compile(r'<meta\s+name=["\']theme-color["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE)
TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)

FRAMEWORK_HEXES = {
    "#007bff", "#0056b3", "#1990c6", "#136f99",
    "#28a745", "#1d8734", "#26b144", "#218838",
    "#17a2b8", "#dc3545", "#ffc107", "#6c757d", "#5a6268",
    "#212529", "#343a40", "#495057", "#adb5bd", "#ced4da",
    "#dee2e6", "#e9ecef", "#f8f9fa",
    "#2196f3", "#4caf50", "#f44336", "#ff9800", "#9c27b0",
    "#0000ee", "#551a8b", "#0066cc",
    "#cccccc", "#999999", "#666666", "#333333", "#dddddd",
    "#3b82f6", "#10b981", "#ef4444",
}


def extract_hints(url: str, html: str) -> dict:
    hints = {"title": "", "theme_color": "", "top_colors": [], "fonts": [], "shopify": False, "css_urls": []}
    if not html:
        return hints
    m = TITLE_RE.search(html)
    if m:
        hints["title"] = m.group(1).strip()[:200]
    m = THEME_RE.search(html)
    if m:
        hints["theme_color"] = m.group(1).strip()
    hints["shopify"] = "shopify" in html.lower() or "/cdn/shop/" in html

    for href in CSS_HREF_RE.findall(html)[:6]:
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = urljoin(url, href)
        elif not href.startswith("http"):
            href = urljoin(url, href)
        hints["css_urls"].append(href)

    blob = html[:200000]
    css_blobs = []
    for css_url in hints["css_urls"][:3]:
        css_text = fetch(css_url, timeout=15)
        if css_text:
            css_blobs.append(css_text[:200000])
    full = blob + "\n".join(css_blobs)

    colors = HEX_RE.findall(full)
    norm = []
    for c in colors:
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        c = "#" + c.lower()
        if c in ("#ffffff", "#000000"):
            continue
        if c in FRAMEWORK_HEXES:
            continue
        norm.append(c)
    cnt = Counter(norm)
    hints["top_colors"] = [c for c, _ in cnt.most_common(40)]

    fonts = set()
    for f in FONT_RE.findall(full):
        for fam in re.split(r",", f):
            fam = fam.strip().strip("'").strip('"').strip()
            if fam and len(fam) < 60 and not fam.startswith("var(") and "$" not in fam:
                fonts.add(fam)
    hints["fonts"] = sorted(fonts)[:30]

    return hints


def load_reference_excerpt() -> str:
    text = REFERENCE.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) > 220:
        lines = lines[:220] + ["", "# ... (reference truncated for token budget) ..."]
    return "\n".join(lines)


SYSTEM_PROMPT = """You produce DESIGN.md files for DTC brands — YAML+Markdown design-system specs that AI coding agents read to generate brand-faithful UI.

CRITICAL RULES (violations = file rejected):

1. **Use extracted hex colors and fonts, not brand memory.** If hints contain `top hex colors`, those are your palette source. Do NOT override with what you "remember" about the brand. If extraction is sparse (2-3 colors), say so in `## Known Gaps` — don't invent.

2. **Banned opening patterns for `description:`**:
   - "X is a [category] brand that..."
   - "A [adjective] [category] brand..."
   - "X is the [category] brand built on..."
   Lead with a specific observation, an unusual design choice, or a sensory image with a concrete object.

3. **Banned vacuum words** (use at most ONCE if at all): tactile, rugged yet refined, quiet luxury, carefully chosen, thoughtful typography, considered palette. Banned phrases: "speaks in [adj]", "[place] translated into digital".

4. **Token reference closure**: every `{typography.X}`, `{colors.X}`, `{rounded.X}`, `{spacing.X}` reference inside `components:` MUST be defined in the corresponding YAML block above. If you mention `{typography.button-lg}`, you MUST define `button-lg:` in typography. Do NOT use dot-paths like `{typography.logo.fontSize}` — flatten to a single key like `{typography.logo-display}`.

5. **Output format**: ONLY the file content. No preamble, no code fences, no commentary. Output is written verbatim to disk."""


def build_user_prompt(site: dict, hints: dict, reference_excerpt: str) -> str:
    return f"""# Task: Produce DESIGN.md for the DTC brand below

Match the EXACT structural format of the reference shown after the inputs (YAML frontmatter, then YAML blocks for colors/typography/rounded/spacing/components, then Markdown sections ## Components, ## Responsive Behavior, ## Known Gaps).

## Brand
- name: {site['brand_name']}
- slug: {site['slug']}
- url: {site['url']}
- category: {site['category']}

## Extracted Hints (live site, framework defaults already filtered)
- page title: {hints.get('title') or '(none)'}
- meta theme-color: {hints.get('theme_color') or '(none)'}
- platform-shopify: {hints.get('shopify')}
- top hex colors (most distinctive first; the brand's TRUE primary is usually the most unique color, not the generic blue/gray): {', '.join(hints.get('top_colors', [])[:30]) or '(none)'}
- font-family stacks found: {', '.join(hints.get('fonts', [])[:15]) or '(none)'}

If hints are very sparse (≤3 colors / 0 fonts), the site likely loads tokens via JS or is behind anti-bot. Note this in `## Known Gaps` and use brand-knowledge cautiously, citing only widely-documented brand-color facts (e.g. "Tiffany blue is famously #0abab5") rather than fabricating.

## Required structure (see reference at bottom)

```
---
version: alpha
name: {site['brand_name']}
description: (200-400 word editorial paragraph — flowing prose, NOT bullets. Open with a brand-particular observation. Weave hex values and {{rounded.full}}-style token refs naturally. NEVER open with "X is a [category] brand that...")

colors:
  primary: "#hex"
  primary-active: "#hex"
  primary-disabled: "#hex"
  ink: "#hex"
  body: "#hex"
  muted: "#hex"
  hairline: "#hex"
  canvas: "#hex"
  surface-soft: "#hex"
  surface-card: "#hex"
  on-primary: "#hex"
  (+ brand-specific tokens)

typography:
  display-xl: {{fontFamily, fontSize, fontWeight, lineHeight, letterSpacing}}
  display-md: {{...}}
  title-md: {{...}}
  body-md: {{...}}
  body-sm: {{...}}
  caption: {{...}}
  button-md: {{...}}
  (+ any other scales you reference)

rounded:
  none: 0px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 20px
  xl: 32px
  full: 9999px

spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  base: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  section: 64px

components:
  button-primary: {{...}}
  button-secondary: {{...}}
  text-input: {{...}}
  nav-bar: {{...}}
  product-card: {{...}}
  (+ 5-10 brand-signature components: hero, badges, search, footer, etc.)

## Components

### Buttons
**`button-primary`** — 2-4 sentence prose description with state variants.
...

## Responsive Behavior

| Name | Width | Key Changes |
|---|---|---|
| Mobile | < 744px | ... |
| Tablet | 744-1128px | ... |
| Desktop | 1128-1440px | ... |
| Wide | > 1440px | ... |

### Touch Targets
- bullets

### Collapsing Strategy
- bullets

## Known Gaps

- bullet list of design data that couldn't be reliably extracted
```

## Quality Bar
- Use the extracted hex values as source of truth. The brand's primary is almost always the most DISTINCTIVE color in the extracted list (an unusual pink/sage/marigold), not a common blue or gray.
- Description must open with a brand-particular observation. Avoid the banned patterns.
- 350-600 lines total. Be generous with detail in `## Components`.
- All token refs in `components:` must resolve to defined tokens above.

## Reference Format

{reference_excerpt}

---

Output ONLY the DESIGN.md content for "{site['brand_name']}", nothing else."""


def call_claude(system: str, user: str, timeout: int = PER_CALL_TIMEOUT) -> str:
    """Invoke `claude -p` headless via stdin. Uses Popen + group-kill on timeout
    so hung children don't survive past the deadline."""
    full_prompt = f"<system>\n{system}\n</system>\n\n{user}"
    proc = subprocess.Popen(
        [
            "claude", "-p",
            "--model", CLAUDE_MODEL,
            "--dangerously-skip-permissions",
            "--output-format", "text",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,  # own process group so we can SIGKILL the tree
    )
    try:
        stdout, stderr = proc.communicate(input=full_prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        # Hard-kill the entire process group
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            pass
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise RuntimeError(f"claude timeout after {timeout}s (killed)")
    if proc.returncode == 0 and stdout:
        return stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace")[:300] if stderr else ""
    raise RuntimeError(f"claude exit {proc.returncode}: {err}")


REQUIRED_SECTIONS = [
    re.compile(r"^---\s*$", re.MULTILINE),
    re.compile(r"^name:\s*", re.MULTILINE),
    re.compile(r"^description:\s*", re.MULTILINE),
    re.compile(r"^colors:\s*$", re.MULTILINE),
    re.compile(r"^typography:\s*$", re.MULTILINE),
    re.compile(r"^rounded:\s*$", re.MULTILINE),
    re.compile(r"^spacing:\s*$", re.MULTILINE),
    re.compile(r"^components:\s*$", re.MULTILINE),
    re.compile(r"^## Components\s*$", re.MULTILINE),
    re.compile(r"^## Responsive Behavior\s*$", re.MULTILINE),
    re.compile(r"^## Known Gaps\s*$", re.MULTILINE),
]


def validate_output(content: str) -> tuple[bool, str]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*\n", "", content)
        content = re.sub(r"\n```\s*$", "", content)
    if not content.startswith("---"):
        return False, "missing YAML frontmatter marker"
    for rx in REQUIRED_SECTIONS:
        if not rx.search(content):
            return False, f"missing pattern: {rx.pattern!r}"
    hexes = HEX_RE.findall(content)
    if len(hexes) < 10:
        return False, f"too few hex colors ({len(hexes)})"
    if content.count("\n") < 200:
        return False, f"too short ({content.count(chr(10))} lines)"
    return True, "ok"


def process_site(site: dict) -> tuple[str, str]:
    slug = site["slug"]
    url = site["url"]
    out_dir = DESIGN_DIR / slug
    out_path = out_dir / "DESIGN.md"

    if out_path.exists():
        log(f"[skip] {slug} already exists")
        append_done(slug)
        return slug, "skip-exists"

    log(f"[start] {slug}  {url}")
    html = fetch(url)
    hints = extract_hints(url, html) if html else {"title": "", "theme_color": "", "top_colors": [], "fonts": [], "shopify": False, "css_urls": []}
    log(f"[hints] {slug}  colors={len(hints['top_colors'])} fonts={len(hints['fonts'])} html={'yes' if html else 'NO'}")

    ref = load_reference_excerpt()
    user_prompt = build_user_prompt(site, hints, ref)

    try:
        content = call_claude(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        append_failed(slug, f"LLM_FAIL:{str(e)[:120]}", url)
        log(f"[fail]  {slug}  LLM: {e}")
        return slug, "llm-fail"

    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*\n", "", content)
        content = re.sub(r"\n```\s*$", "", content)

    ok, reason = validate_output(content)
    if not ok:
        append_failed(slug, f"VALIDATE_FAIL:{reason}", url)
        log(f"[fail]  {slug}  validate: {reason}")
        return slug, f"validate-fail:{reason}"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    append_done(slug)
    log(f"[done]  {slug}  {content.count(chr(10))} lines")
    return slug, "ok"


def main():
    done = load_done()
    failed = load_failed_slugs()
    queue = load_queue()
    pending = [s for s in queue if s["slug"] not in done and s["slug"] not in failed]

    if LIMIT > 0:
        pending = pending[:LIMIT]

    log(f"queue:{len(queue)} done:{len(done)} failed:{len(failed)} pending:{len(pending)}")
    log(f"workers:{MAX_WORKERS} model:{CLAUDE_MODEL} timeout:{PER_CALL_TIMEOUT}s")

    if not pending:
        log("nothing to do.")
        return

    DESIGN_DIR.mkdir(parents=True, exist_ok=True)

    n_ok = n_fail = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process_site, s): s for s in pending}
        for fut in as_completed(futures):
            slug, status = fut.result()
            if status in ("ok", "skip-exists"):
                n_ok += 1
            else:
                n_fail += 1
            if (n_ok + n_fail) % 10 == 0:
                log(f"progress: ok={n_ok} fail={n_fail} of {len(pending)}")

    log(f"FINAL: ok={n_ok} fail={n_fail} of {len(pending)}")


if __name__ == "__main__":
    main()
