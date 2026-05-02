# Swiftclaim — Design System

Drop this file into your project root. Reference it in every prompt to Claude Code:
> "Follow the design system in DESIGN_SYSTEM.md"

---

## Brand identity

**Product**: Swiftclaim.se — Swedish property damage insurance claim service  
**Tone**: Urgent, trustworthy, direct. We fight for the user. No fluff.  
**Language**: Swedish throughout. Formal enough to feel credible, human enough to feel approachable.

---

## Color palette

| Token | Hex | Usage |
|---|---|---|
| `--bg` | `#EFECE3` | Page background. Never use white. |
| `--bg-card` | `#E5E1D6` | Cards, inset surfaces, team tiles |
| `--accent` | `#4A70A9` | Primary CTA buttons, links, active states, hero backgrounds, stat numbers |
| `--accent-dark` | `#3a5a8f` | Hover state for accent |
| `--text-primary` | `#000000` | All body text, headings |
| `--text-secondary` | `#333333` | Body copy paragraphs |
| `--text-muted` | `#777777` | Subtitles, roles, hints |
| `--text-on-accent` | `#EFECE3` | Text placed on `--accent` backgrounds |
| `--border` | `rgba(0,0,0,0.10)` | All dividers, card borders, nav borders |
| `--border-strong` | `rgba(0,0,0,0.18)` | Button outlines, stronger separators |

### Rules
- **Never use pure white** (`#ffffff`) anywhere — use `--bg` or `--bg-card` instead
- Accent color is used sparingly: CTAs, active nav links, stat numbers, section eyebrows, hero backgrounds on inner pages
- All overlays use `rgba(0,0,0,N)` — never colored overlays

---

## Typography

**Font family**: `Inter, system-ui, sans-serif`  
No external font imports needed — Inter is the single typeface across all pages.

| Role | Size | Weight | Notes |
|---|---|---|---|
| Logo | `1.15rem` | `600` | Letter-spacing `-0.5px` |
| Hero h1 | `clamp(1.75rem, 4.5vw, 3rem)` | `600` | Letter-spacing `-1px`, line-height `1.1` |
| Section h2 | `clamp(1.4rem, 2.5vw, 1.9rem)` | `600` | Letter-spacing `-0.3px` |
| Body copy | `15px` | `400` | Line-height `1.8`, color `--text-secondary` |
| Small / meta | `13px` | `400–500` | Color `--text-muted` |
| Eyebrow label | `12px` | `500` | `text-transform: uppercase`, `letter-spacing: 0.08–0.1em`, color `--accent` or muted |
| Nav links | `14px` | `500` | |
| Button | `14–15px` | `600` | |

---

## Spacing

Base unit: `8px`. All spacing should be multiples of this.

| Token | Value | Usage |
|---|---|---|
| `--space-xs` | `8px` | Tight gaps between related elements |
| `--space-sm` | `16px` | Component internal padding |
| `--space-md` | `24px` | Between components in a section |
| `--space-lg` | `48px` | Between sections |
| `--space-xl` | `80px` | Hero and page-level breathing room |

Content max-width: **960px**, centered with `margin: 0 auto`.  
Horizontal page padding: `1.25rem` (mobile), auto-contained on desktop.

---

## Border radius

| Context | Value |
|---|---|
| Buttons (pill CTAs) | `999px` |
| Cards, panels | `12px` |
| Small buttons, inputs | `6–8px` |
| Avatars | `50%` |

---

## Components

### Navigation (header)

- **Landing page**: `position: fixed`, fully transparent over the hero image. Logo and links are white. Hamburger button has frosted glass style (`rgba(255,255,255,0.15)` bg, `1px solid rgba(255,255,255,0.35)` border).
- **Inner pages**: `position: fixed`, `background: rgba(239,236,227,0.95)`, `backdrop-filter: blur(12px)`, `border-bottom: 0.5px solid rgba(0,0,0,0.1)`. Logo is `--accent`. Links are `--text-primary`.
- Height: `56px`
- Max-width inner: `960px`
- Active link: color `--accent`, background `rgba(74,112,169,0.08)`
- Mobile: links collapse, hamburger icon appears at `≤ 767px`

### Mobile sheet (left drawer)

- Slides in from the **left**
- Background: `rgba(239,236,227,0.97)` with `backdrop-filter: blur(12px)`
- Border right: `0.5px solid rgba(0,0,0,0.1)`
- Width: `min(300px, 82vw)`
- Transition: `transform 0.32s cubic-bezier(0.4,0,0.2,1)`
- Overlay behind: `rgba(0,0,0,0.3)` when open
- Body: primary nav links, divider, then legal/utility links
- Footer: pinned CTA button

### Buttons

```css
/* Primary CTA (pill) */
background: #4A70A9;
color: #EFECE3;
font-size: 15px;
font-weight: 600;
padding: 14px 32px;
border-radius: 999px;
box-shadow: 0 2px 16px rgba(0,0,0,0.25);

/* Hover */
background: #3a5a8f;
transform: translateY(-1px);

/* Solid small (nav) */
padding: 6px 16px;
border-radius: 6px;
/* same colors, no shadow */

/* Inverse (on accent bg) */
background: #EFECE3;
color: #4A70A9;
border-radius: 999px;
```

### Cards

```css
background: #E5E1D6;
border: 0.5px solid rgba(0,0,0,0.1);
border-radius: 12px;
padding: 1rem 1.1rem;
```

### Section layout (inner pages)

Two-column grid for content sections:
```css
display: grid;
grid-template-columns: 180px 1fr;
gap: 3rem;
```
- Left: eyebrow label in `--accent`, `12px`, uppercase
- Right: `h2` + body copy
- Separated from the next section by `border-top: 0.5px solid rgba(0,0,0,0.1)`
- Collapses to single column on mobile (`≤ 640px`)

### Stats row

```css
display: grid;
grid-template-columns: repeat(3, 1fr);
border: 0.5px solid rgba(0,0,0,0.1);
border-radius: 12px;
overflow: hidden;
```
- Cells separated by `border-right: 0.5px solid rgba(0,0,0,0.1)`
- Number: `2.5rem`, `font-weight: 600`, `color: --accent`
- Label: `13px`, `color: --text-muted`

### Hero — landing page

- `height: 100vh`, `min-height: 560px`
- Background image with `background-size: cover`
- Overlay: `linear-gradient(to bottom, rgba(0,0,0,0.3) 0%, rgba(0,0,0,0.48) 55%, rgba(0,0,0,0.62) 100%)`
- Parallax: `transform: scale(1.04) translateY(scrollY * 0.25px)` on scroll
- Scroll indicator: animated arrow at bottom center

### Hero — inner pages

- `background: #4A70A9`
- `padding: clamp(3.5rem, 8vw, 6rem) 1.25rem`
- `text-align: center`
- Eyebrow in `rgba(239,236,227,0.65)`
- `h1` in `#EFECE3`, max-width `640px`
- Subtext in `rgba(239,236,227,0.75)`

### CTA strip (page footer)

```css
background: #4A70A9;
text-align: center;
padding: 4rem 1.25rem;
```
- `h2` in `#EFECE3`
- Subtext in `rgba(239,236,227,0.75)`
- Inverse pill button

### Trust badges

```css
background: rgba(239,236,227,0.12);
border: 1px solid rgba(239,236,227,0.25);
backdrop-filter: blur(4px);
border-radius: 999px;
padding: 5px 14px;
font-size: 13px;
color: rgba(255,255,255,0.9);
```
Used on landing page hero only, displayed in a flex-wrap row.

---

## Animation

| Effect | Values |
|---|---|
| Scroll reveal | `opacity: 0 → 1`, `translateY(20px → 0)`, `0.5s ease` via `IntersectionObserver` |
| Parallax (hero bg) | `translateY(scrollY * 0.25px)` |
| Sheet slide | `translateX(-100% → 0)`, `0.32s cubic-bezier(0.4,0,0.2,1)` |
| Button hover lift | `translateY(-1px)`, `0.1s` |
| Scroll indicator | `translateY(0 → 6px)` bounce, `2s infinite` |
| Testimonial columns | CSS `animation: scrollUp linear infinite`, speeds: `40s / 32s / 25s` |

---

## Navigation structure

| Page | File | Status |
|---|---|---|
| Landing / Hem | `swiftclaim_testimonials_page.html` | ✅ Built |
| Om oss | `om-oss.html` | ✅ Built |
| Priser | `priser.html` | 🔲 Placeholder |
| Blogg / Kundberättelser | `blogg.html` | 🔲 Placeholder |
| Vanliga frågor | `faq.html` | 🔲 Placeholder |
| Kontakta oss | `kontakt.html` | 🔲 Placeholder |
| Dataskydd | `dataskydd.html` | 🔲 Placeholder |
| Användarvillkor | `anvandarvillkor.html` | 🔲 Placeholder |

### Nav link order (desktop, left → right)
`Om oss` → `Priser` → `Blogg` → `Vanliga frågor` → `Kontakt` → **[Anmäl skada CTA]**

### Sheet order (mobile)
Primary: Om oss, Priser, Blogg & kundberättelser, Vanliga frågor  
Divider  
Utility: Kontakta oss, Dataskydd, Användarvillkor  
Footer: Anmäl skada (full-width solid button)

---

## Page template (inner pages)

Every inner page follows this structure:

```
<header>        ← Fixed nav, #EFECE3 bg, same across all pages
<sheet>         ← Mobile left drawer
<div.page-hero> ← Accent bg (#4A70A9) hero with eyebrow + h1 + subtext
<div.content>   ← max-width 960px, section blocks
  <div.section.reveal> × N
    <div.section-grid>
      <div.section-label>
      <div.section-body>
<div.cta-strip> ← Accent bg CTA strip, full width, links to anmäl skada
```

All sections use `.reveal` class with IntersectionObserver for fade-in on scroll.

---

## Do / Don't

| ✅ Do | ❌ Don't |
|---|---|
| Use `#EFECE3` as the base background | Use `#ffffff` anywhere |
| Use `Inter` as the font | Import decorative or display fonts |
| Use `#4A70A9` for accents sparingly | Apply accent to every element |
| Keep borders at `0.5px` and subtle | Use thick or colored borders |
| Write Swedish copy | Mix English and Swedish in UI |
| Keep CTAs as pill buttons (`border-radius: 999px`) | Use square CTA buttons |
| Use `clamp()` for responsive font sizes | Use fixed px font sizes on headings |
| Collapse to single column on mobile | Let two-column grids overflow on small screens |
