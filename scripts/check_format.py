#!/usr/bin/env python3
"""Format Auditor for DESIGN.md files.

Runs deterministic structural checks on every DESIGN.md under design-md/.
Produces a JSON report on stdout and writes _state/quality_format.md.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN_ROOT = ROOT / "design-md"
STATE_DIR = ROOT / "_state"

HEX_RE = re.compile(r'#[0-9a-fA-F]{3,8}\b')
TOKEN_REF_RE = re.compile(r'\{(colors|typography|rounded|spacing)\.([^}]+)\}')

# Keys we expect inside frontmatter
FRONTMATTER_KEYS = ("version", "name", "description")
# Top-level YAML block headers (must appear at col 0 followed by colon)
TOP_BLOCKS = ("colors", "typography", "rounded", "spacing", "components")
# Markdown sections (## level)
MD_SECTIONS = ("## Components", "## Responsive Behavior", "## Known Gaps")


def split_sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Return mapping of top-level YAML block name -> (start_line, end_line) 1-indexed.

    A 'top-level' block is a line matching ^([a-z][a-z0-9_-]*):$ at column 0
    that occurs BEFORE the first '## ' markdown header. The block ends just
    before the next top-level block or first '## ' header.
    """
    block_starts: list[tuple[int, str]] = []
    md_start = None
    block_re = re.compile(r'^([a-z][a-z0-9_-]*):\s*$')
    for i, line in enumerate(lines):
        if line.startswith("## "):
            md_start = i
            break
        m = block_re.match(line)
        if m:
            block_starts.append((i, m.group(1)))
    # Compute end as next start or md_start or EOF
    end_anchor = md_start if md_start is not None else len(lines)
    boundaries: dict[str, tuple[int, int]] = {}
    for idx, (start, name) in enumerate(block_starts):
        if idx + 1 < len(block_starts):
            end = block_starts[idx + 1][0]
        else:
            end = end_anchor
        boundaries[name] = (start, end)
    return boundaries


def parse_simple_yaml_keys(lines: list[str], start: int, end: int) -> set[str]:
    """Extract the top-level keys inside a YAML block (between start exclusive and end exclusive).

    A key here = a line indented (typically 2 spaces) with `<key>:` and either
    a scalar value on the same line or a nested mapping below. We collect
    the immediate child keys at the first indent level.
    """
    keys: set[str] = set()
    first_indent: int | None = None
    key_re = re.compile(r'^(\s+)([A-Za-z0-9_-][A-Za-z0-9_.-]*):')
    for i in range(start + 1, end):
        line = lines[i]
        if not line.strip():
            continue
        # Skip comments
        if line.lstrip().startswith('#'):
            continue
        m = key_re.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        if first_indent is None:
            first_indent = indent
        if indent == first_indent:
            keys.add(m.group(2))
    return keys


def parse_yaml_loose(text: str, label: str) -> list[str]:
    """Run cheap syntactic sanity checks on a YAML block. Returns list of issue strings."""
    issues: list[str] = []
    # We'll examine the textual block for obvious problems:
    # - unbalanced single/double quotes per line
    # - missing colon after a non-blank, non-list, non-indent-continuation line at top indent
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        # Count quotes outside of comments
        # Strip trailing inline comment (rough)
        no_comment = re.sub(r'(?<!\\)\s+#.*$', '', line)
        dq = no_comment.count('"') - no_comment.count('\\"')
        sq = no_comment.count("'") - no_comment.count("\\'")
        if dq % 2 != 0:
            issues.append(f"{label}:{i} unbalanced double-quote: {line.strip()[:80]}")
        if sq % 2 != 0:
            issues.append(f"{label}:{i} unbalanced single-quote: {line.strip()[:80]}")
        # If line has no ':' and no '-' and no inherited continuation, that's suspicious
        # But this is too noisy in practice; skip.
    return issues


def audit_file(path: Path) -> dict:
    slug = path.parent.name
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    n_lines = len(lines)
    result: dict = {
        "slug": slug,
        "path": str(path),
        "lines": n_lines,
        "checks": {},
        "broken_refs": [],
        "yaml_issues": [],
        "fails": [],
    }

    # Check 1: starts with `---` YAML frontmatter
    has_fm_start = bool(lines) and lines[0].strip() == "---"
    fm_end_idx = None
    if has_fm_start:
        # Find closing '---' (next line starting with --- at col 0)
        for i in range(1, min(len(lines), 200)):
            if lines[i].strip() == "---":
                fm_end_idx = i
                break
        # If no closing '---' before content blocks, we treat the frontmatter as
        # "the block from line 0 up to the first top-level YAML block header
        # (e.g. `colors:`)". The repo's reference convention puts frontmatter
        # keys (version, name, description) inline at the top without an
        # explicit closing '---', so we accept that pattern as valid frontmatter.
    result["checks"]["frontmatter_start"] = has_fm_start

    # Frontmatter scan region: lines[0:fm_end_idx] if closing found,
    # otherwise lines[0 : first_top_block_start]
    sections = split_sections(lines)
    if fm_end_idx is not None:
        fm_region = lines[1:fm_end_idx]
    else:
        # Use up to first top block
        first_top = min((v[0] for v in sections.values()), default=len(lines))
        fm_region = lines[1:first_top]

    fm_text = "\n".join(fm_region)
    # Check 2: frontmatter keys present
    fm_keys_present = {k: bool(re.search(rf'^{re.escape(k)}\s*:', fm_text, re.MULTILINE)) for k in FRONTMATTER_KEYS}
    result["checks"]["frontmatter_keys"] = fm_keys_present
    result["checks"]["frontmatter_keys_ok"] = all(fm_keys_present.values())

    # Check 3: top-level YAML blocks
    blocks_present = {b: (b in sections) for b in TOP_BLOCKS}
    result["checks"]["top_blocks"] = blocks_present
    result["checks"]["top_blocks_ok"] = all(blocks_present.values())

    # Check 4: markdown sections
    md_present = {s: (s in raw) for s in MD_SECTIONS}
    result["checks"]["md_sections"] = md_present
    result["checks"]["md_sections_ok"] = all(md_present.values())

    # Check 5: at least 10 hex color tokens
    # Count unique hex tokens defined inside the colors: block specifically.
    color_hex_count = 0
    color_keys: set[str] = set()
    if "colors" in sections:
        cs, ce = sections["colors"]
        block_text = "\n".join(lines[cs + 1:ce])
        color_hex_count = len(set(HEX_RE.findall(block_text)))
        color_keys = parse_simple_yaml_keys(lines, cs, ce)
    # Also fall back to hex anywhere in file if colors block missing
    if color_hex_count == 0:
        color_hex_count = len(set(HEX_RE.findall(raw)))
    result["checks"]["hex_color_count"] = color_hex_count
    result["checks"]["hex_color_ok"] = color_hex_count >= 10

    # Check 6: at least 200 lines
    result["checks"]["line_count_ok"] = n_lines >= 200

    # Collect defined keys for all four scopes
    defined: dict[str, set[str]] = {"colors": color_keys, "typography": set(), "rounded": set(), "spacing": set()}
    for scope in ("typography", "rounded", "spacing"):
        if scope in sections:
            s, e = sections[scope]
            defined[scope] = parse_simple_yaml_keys(lines, s, e)

    result["defined_counts"] = {k: len(v) for k, v in defined.items()}

    # Check 7: token references inside components: resolve
    broken_refs: list[str] = []
    total_refs = 0
    if "components" in sections:
        cs, ce = sections["components"]
        for i in range(cs, ce):
            line = lines[i]
            for m in TOKEN_REF_RE.finditer(line):
                total_refs += 1
                scope = m.group(1)
                key = m.group(2).strip()
                if scope in defined and key not in defined[scope]:
                    broken_refs.append(f"{slug}:{i + 1} — {{{scope}.{key}}} not defined")
    result["checks"]["total_token_refs"] = total_refs
    result["checks"]["broken_token_refs"] = len(broken_refs)
    result["checks"]["token_refs_ok"] = len(broken_refs) == 0
    result["broken_refs"] = broken_refs

    # Check 8: YAML loose sanity in colors: and typography: blocks
    yaml_issues: list[str] = []
    for scope in ("colors", "typography"):
        if scope in sections:
            s, e = sections[scope]
            block_text = "\n".join(lines[s:e])
            yaml_issues.extend(parse_yaml_loose(block_text, f"{slug}/{scope}"))
    result["yaml_issues"] = yaml_issues
    result["checks"]["yaml_loose_ok"] = len(yaml_issues) == 0

    # Aggregate failures
    if not result["checks"]["frontmatter_start"]:
        result["fails"].append("frontmatter_start")
    if not result["checks"]["frontmatter_keys_ok"]:
        result["fails"].append("frontmatter_keys")
    if not result["checks"]["top_blocks_ok"]:
        result["fails"].append("top_blocks")
    if not result["checks"]["md_sections_ok"]:
        result["fails"].append("md_sections")
    if not result["checks"]["hex_color_ok"]:
        result["fails"].append("hex_colors")
    if not result["checks"]["line_count_ok"]:
        result["fails"].append("line_count")
    if not result["checks"]["token_refs_ok"]:
        result["fails"].append("token_refs")
    if not result["checks"]["yaml_loose_ok"]:
        result["fails"].append("yaml_loose")

    return result


def main() -> int:
    files = sorted(DESIGN_ROOT.glob("*/DESIGN.md"))
    reports = [audit_file(p) for p in files]

    n = len(reports)
    counts = Counter()
    failers = defaultdict(list)
    for r in reports:
        for ch, ok in [
            ("frontmatter_start", r["checks"]["frontmatter_start"]),
            ("frontmatter_keys", r["checks"]["frontmatter_keys_ok"]),
            ("top_blocks", r["checks"]["top_blocks_ok"]),
            ("md_sections", r["checks"]["md_sections_ok"]),
            ("hex_colors_ge_10", r["checks"]["hex_color_ok"]),
            ("lines_ge_200", r["checks"]["line_count_ok"]),
            ("token_refs_resolve", r["checks"]["token_refs_ok"]),
            ("yaml_loose_sanity", r["checks"]["yaml_loose_ok"]),
        ]:
            counts[(ch, "pass" if ok else "fail")] += 1
            if not ok:
                failers[ch].append(r["slug"])

    # All broken refs
    all_broken = []
    for r in reports:
        all_broken.extend(r["broken_refs"])

    # Files failing multiple checks
    multi_fail = sorted(
        [(r["slug"], r["fails"]) for r in reports if len(r["fails"]) >= 2],
        key=lambda x: (-len(x[1]), x[0]),
    )

    # All-pass count
    fully_passing = sum(1 for r in reports if not r["fails"])
    pct_passing = round(fully_passing / max(1, n) * 100)

    # Build report markdown
    md = []
    md.append("# Format Audit Report")
    md.append("")
    md.append(f"- Files audited: **{n}**")
    md.append(f"- Fully passing all 8 checks: **{fully_passing} ({pct_passing}%)**")
    md.append(f"- Total broken token references: **{len(all_broken)}**")
    md.append(f"- Files failing 2+ checks: **{len(multi_fail)}**")
    md.append("")
    md.append("## Per-check results")
    md.append("")
    md.append("| Check | Pass | Fail |")
    md.append("|---|---:|---:|")
    check_order = [
        "frontmatter_start",
        "frontmatter_keys",
        "top_blocks",
        "md_sections",
        "hex_colors_ge_10",
        "lines_ge_200",
        "token_refs_resolve",
        "yaml_loose_sanity",
    ]
    for ch in check_order:
        p = counts[(ch, "pass")]
        f = counts[(ch, "fail")]
        md.append(f"| {ch} | {p} | {f} |")
    md.append("")

    md.append("## Top 20 broken token references")
    md.append("")
    if all_broken:
        md.append("```")
        for line in all_broken[:20]:
            md.append(line)
        md.append("```")
        if len(all_broken) > 20:
            md.append(f"_(+{len(all_broken) - 20} more)_")
    else:
        md.append("_None — all token references resolve._")
    md.append("")

    md.append("## Files failing 2+ checks")
    md.append("")
    if multi_fail:
        md.append("| Slug | # Fails | Failing checks |")
        md.append("|---|---:|---|")
        for slug, fails in multi_fail[:40]:
            md.append(f"| {slug} | {len(fails)} | {', '.join(fails)} |")
        if len(multi_fail) > 40:
            md.append("")
            md.append(f"_(+{len(multi_fail) - 40} more worst offenders)_")
    else:
        md.append("_None._")
    md.append("")

    # Per-check failer roster (compact)
    md.append("## Slugs failing each check")
    md.append("")
    for ch in check_order:
        slugs = failers.get(ch, [])
        if not slugs:
            continue
        shown = ", ".join(slugs[:20])
        more = f" _(+{len(slugs) - 20} more)_" if len(slugs) > 20 else ""
        md.append(f"- **{ch}** ({len(slugs)}): {shown}{more}")
    md.append("")

    # Verdict
    critical_issues = len(all_broken) + sum(counts[(ch, "fail")] for ch in (
        "frontmatter_start", "frontmatter_keys", "top_blocks", "md_sections", "yaml_loose_sanity"
    ))
    if fully_passing == n:
        verdict = "PASS"
    elif fully_passing / max(1, n) >= 0.85 and len(all_broken) == 0:
        verdict = "NEEDS_FIXES"
    elif fully_passing / max(1, n) >= 0.6:
        verdict = "NEEDS_FIXES"
    else:
        verdict = "FAIL"
    md.append(f"**Verdict: {verdict}**")
    md.append("")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = STATE_DIR / "quality_format.md"
    out_path.write_text("\n".join(md), encoding="utf-8")

    summary = {
        "n": n,
        "fully_passing": fully_passing,
        "pct_passing": pct_passing,
        "broken_refs_total": len(all_broken),
        "critical_issues": critical_issues,
        "verdict": verdict,
        "report_path": str(out_path),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
