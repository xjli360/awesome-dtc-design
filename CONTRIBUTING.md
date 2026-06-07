# Contributing to awesome-dtc-design

This collection documents the design systems of 3,000 leading direct-to-consumer (DTC) e-commerce brands as plain-text `DESIGN.md` token files that AI agents can read to generate consistent, brand-faithful UI.

The format follows the [`awesome-design-md`](https://github.com/VoltAgent/awesome-design-md) specification.

## Adding a New Brand

1. Pick a brand that is genuinely DTC (sells directly to consumer, not just a marketplace listing).
2. Create a folder under `design-md/` using a lowercase, hyphenated slug derived from the brand name (e.g. `our-place`, `caraway`, `nothing`).
3. Inside that folder, add a `DESIGN.md` following the 9-section structure described below.
4. Open a PR. One brand per PR.

## DESIGN.md Structure

Every `DESIGN.md` must contain these nine sections, in this order:

| Section | Content |
|---|---|
| YAML frontmatter | `version`, `name`, `description` (200-400 word brand-design summary) |
| `colors:` | Semantic token names → hex values. Include neutrals, surfaces, accents, semantic roles. |
| `typography:` | Each scale step has `fontFamily`, `fontSize`, `fontWeight`, `lineHeight`, `letterSpacing`. |
| `rounded:` | Border-radius scale (`xs`, `sm`, `md`, `lg`, `xl`, `full`). |
| `spacing:` | Spacing scale (`xxs`–`section`). |
| `components:` | Buttons, cards, inputs, navigation, etc. Each with token references in `{namespace.key}` form. |
| `## Components` (Markdown) | Prose descriptions of each component with state variants. |
| `## Responsive Behavior` | Breakpoint table + touch target + collapse strategy notes. |
| `## Known Gaps` | What couldn't be extracted reliably (hover states, error states, sub-brands, etc.). |

## Quality Bar

- **Real tokens, not invented ones.** Colors and font stacks must be sampled from the live site.
- **Description must capture brand voice**, not just list visual attributes. Read like editorial copy, not a tech spec.
- **Slug is canonical**: `airbnb`, not `Airbnb` or `air-bnb`.

## License

By contributing, you agree your work is licensed under the project's MIT License.
