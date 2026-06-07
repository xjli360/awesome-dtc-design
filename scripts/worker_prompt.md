# Site Processor Prompt Template

You are processing ONE DTC brand site to produce a `DESIGN.md` token file.

## Inputs
- **brand_name**: {{brand_name}}
- **url**: {{url}}
- **category**: {{category}}
- **slug**: {{slug}}
- **style_hint** (from CSV, optional): {{style}}
- **products_hint** (from CSV, optional): {{products}}

## Output
- **Write to**: `/Users/jieli/Code/awesome-dtc-design/design-md/{{slug}}/DESIGN.md`
- **Reference format**: `/Users/jieli/Code/awesome-dtc-design/scripts/REFERENCE_DESIGN.md` — match this structure **exactly** (YAML frontmatter, then YAML blocks for `colors`, `typography`, `rounded`, `spacing`, `components`, then Markdown sections `## Components`, `## Responsive Behavior`, `## Known Gaps`).

## Workflow (3 roles, sequenced)

### Role 1 — Scraper
1. `WebFetch` the homepage at `{{url}}` with this extraction prompt:
   > Extract design system data for this brand: (a) Dominant color palette — give hex values from CSS variables, inline styles, or visible page sections; identify the brand's primary CTA color, primary surface color, primary text color, accent colors, and any seasonal/promotional colors. (b) Typography — list the font-family stacks used (look for @font-face, font-family in CSS or visible text rendering), with size/weight for hero headline, body, button, caption. (c) Button styles — describe primary CTA: shape (rectangle, pill, rounded-rect), corner radius, padding, height, hover state if visible. (d) Layout — describe homepage hero, product grid layout, card style, navigation bar style. (e) Brand mood — atmospheric one-paragraph description of how the site feels (editorial, industrial, minimalist, playful, heritage, etc.).
2. If the homepage extraction is thin, optionally `WebFetch` a product page or category page from the same domain.
3. Save raw findings mentally — do not write them to a file yet.

### Role 2 — Generator
4. Compose the `DESIGN.md` following the Airbnb reference format:
   - **YAML frontmatter**: `version: alpha`, `name: {{brand_name}}`, `description:` (200-400 word editorial paragraph capturing brand voice, dominant colors as named tokens, typography character, signature components, layout philosophy — NOT a bulleted list, written as flowing prose with token references like `#hex` and `{rounded.full}` interspersed).
   - **colors:** YAML block. Include at minimum: `primary`, `primary-active`, `ink` (text), `body`, `muted`, `hairline`, `canvas` (background), `surface-soft`, `surface-card`, `on-primary`. Add brand-specific tokens (accent, sale, badge, etc.).
   - **typography:** YAML block. Include at minimum: `display-xl`, `display-md`, `title-md`, `body-md`, `body-sm`, `caption`, `button-md`. Each entry has `fontFamily`, `fontSize`, `fontWeight`, `lineHeight`, `letterSpacing` (omit `letterSpacing` only if truly 0).
   - **rounded:** scale `none`, `xs`, `sm`, `md`, `lg`, `xl`, `full`.
   - **spacing:** scale `xxs`, `xs`, `sm`, `md`, `base`, `lg`, `xl`, `xxl`, `section`.
   - **components:** YAML block referencing tokens via `{namespace.key}` form. Include at least: `button-primary`, `button-secondary`, `text-input`, `nav-bar`, `product-card`, plus 5-10 brand-signature components (search bar, hero, footer, badges, etc.).
   - **`## Components`** (Markdown): For each component listed in the YAML, write 2-4 sentence prose description with state variants (default, active/pressed, disabled, hover if known).
   - **`## Responsive Behavior`**: Markdown table with breakpoint columns (Mobile / Tablet / Desktop / Wide), brief description of what changes. Plus a `### Touch Targets` and `### Collapsing Strategy` subsection.
   - **`## Known Gaps`**: Bullet list of what couldn't be reliably extracted (hover state colors, error states, sub-brand palettes, secondary fonts only loaded on specific pages, etc.).

### Role 3 — Validator (do this BEFORE finalizing the file)
5. Re-read your generated DESIGN.md and check:
   - [ ] All YAML blocks are syntactically valid (no missing quotes, no broken keys)
   - [ ] Every `{colors.xxx}`, `{typography.xxx}`, `{rounded.xxx}`, `{spacing.xxx}` reference in `components:` resolves to a defined token above
   - [ ] Description paragraph is editorial prose, not a bulleted spec
   - [ ] All three Markdown sections (`## Components`, `## Responsive Behavior`, `## Known Gaps`) are present and non-empty
   - [ ] Brand name and slug match inputs
   - [ ] No invented/hallucinated hex values without basis — if uncertain, list in `## Known Gaps` and use a sensible approximation noted there
6. If any check fails, fix it before writing the final file.

## Quality Bar
- Description must read like editorial copy that captures **why this brand feels the way it does**, not a generic "Modern minimalist with muted tones."
- Tokens should be **specific** — `#1a3d2e` (brand-deep-green), not `#000000` (black) when the brand is clearly green.
- Components should reflect what's **actually on the site** — if the site has a unique element (e.g., "scroll-snap product carousel with magnetic hover"), document it as a component token.

## Failure Handling
- If `WebFetch` returns 404 / blocked / heavy JS-only site with no useful content: write `_state/failed.txt` entry as `{{slug}}\tNO_CONTENT\t{{url}}` and exit without writing DESIGN.md.
- If you genuinely cannot extract colors or fonts (heavily Cloudflare-blocked, etc.): still produce a best-effort DESIGN.md using `style_hint` and `products_hint`, but mark generously in `## Known Gaps`.

## Return Format (back to orchestrator)
After writing the file, return ONE line as your final message:
```
STATUS=OK slug={{slug}} path=design-md/{{slug}}/DESIGN.md colors=N types=M components=K notes="any quirks"
```
or on failure:
```
STATUS=FAIL slug={{slug}} reason="..."
```
