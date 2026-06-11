# Swiftclaim Design Guidelines

Based on `site/landing_v2.html` — the single source of truth for all design decisions.

---

## Google Fonts

```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fraunces:ital,opsz,wght@1,9..144,400;1,9..144,500&display=swap">
```

---

## Color Palette (ColorHunt: `#F9F7F7 #DBE2EF #3F72AF #112D4E`)

| Variable | Hex | Role |
|----------|-----|------|
| `--bg` | `#F9F7F7` | Page background |
| `--bg-card` | `#DBE2EF` | Card/surface background |
| `--bg-deep` | `#CDD6E8` | Deeper surface variant |
| `--bg-dark` | `#112D4E` | Dark section bg (footer, dark CTA, nav glass) |
| `--bg-dark-2` | `#0F2642` | Dark bg secondary |
| `--ink` | `#0A0A0A` | Primary text |
| `--ink-2` | `#2C2C2C` | Secondary text / body copy |
| `--muted` | `#6F6F6F` | Muted labels, captions |
| `--line` | `rgba(0,0,0,0.10)` | Subtle borders on light bg |
| `--line-strong` | `rgba(0,0,0,0.18)` | Stronger borders |
| `--line-on-dark` | `rgba(249,247,247,0.14)` | Borders on dark bg |
| `--brand` | `#3F72AF` | Accent blue (stat numbers, links, icons) |
| `--brand-dark` | `#2E5B9E` | Brand dark variant |
| `--lime` | `#112D4E` | Dark navy (decorative squares, selection, footer highlights) |
| `--lime-deep` | `#0A1E36` | Darker navy |
| `--cta` | `#f7d154` | **Call-to-action yellow** (all "Anmäl skada" buttons) |
| `--cta-hover` | `#e6c44d` | CTA button hover |

### Usage rules
- **`--lime` (= `#112D4E`)**: Used for decorative elements only — `.pixel` squares, `.eyebrow::before`, selection background, footer link hovers, `::selection`. Never for text or primary actions.
- **`--cta` (= `#f7d154`)**: Used ONLY for "Anmäl skada" CTAs. Always paired with `color: var(--ink)` (dark text). Never used elsewhere.
- **`--brand` (= `#3F72AF`)**: Used for section labels, stat numbers, pill badges, team avatars, quote marks.

---

## Typography

| Usage | Family | Weight | Size | Letter-spacing |
|-------|--------|--------|------|----------------|
| Body text | Inter (`var(--sans)`) | 400 | 14-16px | 0 |
| Headings (h1-h2) | Inter | 600 | 2-4rem | `-0.04em` to `-0.05em` |
| Hero display | Inter | 600 | `clamp(3rem, 11vw, 9.5rem)` | `-0.05em` |
| Eyebrow label | Inter | 500 | 12px | `0.12em`, uppercase |
| Section labels | Inter | 500-600 | 12-13px | `0.08em`, uppercase |
| **Italic accent** | Fraunces (`var(--serif)`) | 400 italic | +5% of parent | `-0.02em` |
| Legal section h2 | Inter | 600 | 1.125rem | `-0.3px` |
| Legal section h3 | Inter | 600 | 15px | 0 |
| Legal body | Inter | 400 | 14px | 0 |

### `.serif-em` class
```css
.serif-em {
    font-family: var(--serif);
    font-weight: 400;
    font-style: italic;
    letter-spacing: -0.02em;
}
```
Use inline inside headings for emphasis: `<h2>Vi <span class="serif-em">kämpar</span> för din ersättning</h2>`

---

## Spacing & Radius

| Token | Value | Use |
|-------|-------|-----|
| `--r-card` | `14px` | Card border-radius |
| `--r-pill` | `999px` | Pill buttons, badges, nav |
| Section padding | `7rem` | Desktop section top/bottom |
| Section padding (mobile) | `4rem` | Under 720px |

---

## Shadows

| Variable | Value |
|----------|-------|
| `--shadow-soft` | `0 1px 2px rgba(0,0,0,0.04), 0 8px 28px rgba(0,0,0,0.06)` |
| `--shadow-float` | `0 2px 16px rgba(0,0,0,0.10), 0 30px 60px -20px rgba(0,0,0,0.18)` |

Cards: `border: 0.5px solid var(--line); border-radius: var(--r-card); box-shadow: var(--shadow-soft); background: var(--bg-card);`

---

## Key Components

### 1. Eyebrow Label
```html
<div class="eyebrow">Label Text</div>
```
```css
.eyebrow {
    display: inline-flex; align-items: center; gap: 10px;
    font-size: 12px; font-weight: 500;
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--ink);
}
.eyebrow::before {
    content: "";
    display: inline-block;
    width: 14px; height: 14px;
    background: var(--lime);  /* decorative square */
    border-radius: 2px;
}
```

### 2. Floating Pill Nav
```css
.topnav {
    position: fixed; top: 16px; left: 0; right: 0;
    z-index: 90;
    display: flex; justify-content: center;
    pointer-events: none;
}
.topnav__bar {
    pointer-events: auto;
    display: flex; align-items: center; gap: 0;
    background: rgba(17,45,78,0.92);  /* navy glass */
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border: 0.5px solid rgba(249,247,247,0.08);
    border-radius: var(--r-pill);
    padding: 7px 8px 7px 22px;
    box-shadow: 0 10px 40px -10px rgba(0,0,0,0.35);
    color: var(--bg);
}
.topnav__logo { font-weight: 600; font-size: 1rem; letter-spacing: -0.5px; color: var(--bg); display: inline-flex; align-items: center; gap: 6px; }
.topnav__logo .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--lime); }
.topnav__links > * { font-size: 14px; font-weight: 500; color: rgba(249,247,247,0.78); padding: 9px 14px; border-radius: var(--r-pill); }
.topnav__links > *:hover { color: var(--bg); background: rgba(249,247,247,0.06); }
.topnav__links .active { color: var(--bg); background: rgba(249,247,247,0.1); }
.topnav__cta {
    background: var(--cta);  /* yellow */
    color: var(--ink) !important;
    font-weight: 600;
    margin-left: 8px;
    padding: 9px 18px !important;
}
.topnav__cta:hover { background: var(--cta-hover) !important; }
```
On mobile (`max-width: 880px`): hide `.topnav__links`, show hamburger button.

### 3. Section Header
```html
<div class="wrap">
    <div class="sec-head">
        <div class="sec-head__label"><div class="eyebrow">Label</div></div>
        <div class="sec-head__title"><h2>Section <span class="serif-em">title</span></h2></div>
        <div class="sec-head__meta">Description text goes here.</div>
    </div>
</div>
```
```css
.sec-head {
    display: grid;
    grid-template-columns: 200px 1fr 320px;
    gap: 3rem; align-items: end;
    margin-bottom: 4rem;
}
.sec-head__label { align-self: start; position: sticky; top: 100px; }
.sec-head__title h2 {
    font-size: clamp(2rem, 5vw, 4rem);
    font-weight: 600; letter-spacing: -0.04em;
    line-height: 1; max-width: 14ch;
}
.sec-head__meta { font-size: 15px; color: var(--ink-2); line-height: 1.65; max-width: 30ch; }
@media (max-width: 880px) { .sec-head { grid-template-columns: 1fr; gap: 1.25rem; } .sec-head__label { position: static; } }
```

### 4. Buttons
```css
.btn-pill {
    display: inline-flex; align-items: center; gap: 10px;
    padding: 14px 24px 14px 28px;
    border-radius: var(--r-pill);
    font-weight: 600; font-size: 15px;
    transition: transform 0.2s var(--ease-out), background 0.18s;
    cursor: pointer; border: none;
}
.btn-pill .arrow {
    width: 28px; height: 28px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    transition: transform 0.25s var(--ease-out);
}
.btn-pill:hover .arrow { transform: translateX(4px) rotate(-15deg); }

.btn-pill--dark  { background: var(--ink); color: var(--bg); }            /* General dark bg */
.btn-pill--dark .arrow { background: var(--lime); color: var(--ink); }
.btn-pill--dark:hover { background: var(--ink-2); }

.btn-pill--ghost { background: transparent; border: 1px solid var(--line-strong); color: var(--ink); }
.btn-pill--ghost:hover { background: var(--bg-card); }

.btn-pill--cta   { background: var(--cta); color: var(--ink); }            /* CTA yellow */
.btn-pill--cta:hover { background: var(--cta-hover); }
.btn-pill--cta .arrow { background: var(--ink); color: var(--bg); }
```

### 5. Cards (general)
```css
.card {
    background: var(--bg-card);
    border: 0.5px solid var(--line);
    border-radius: var(--r-card);
    padding: 1.5rem;
    box-shadow: var(--shadow-soft);
}
```
Hover lift: `transform: translateY(-4px); box-shadow: var(--shadow-float);` (optional, depending on context)

### 6. Footer
```css
footer {
    background: var(--bg-dark);  /* navy */
    color: var(--bg);
    padding: 4rem 0 2rem;
}
.footer__grid {
    display: grid;
    grid-template-columns: 1.4fr repeat(4, 1fr);
    gap: 2rem;
    padding-bottom: 3rem;
    border-bottom: 0.5px solid var(--line-on-dark);
}
.footer__col h4 {
    font-size: 13px; font-weight: 600;
    color: rgba(249,247,247,0.55);
    text-transform: uppercase; letter-spacing: 0.08em;
    margin-bottom: 1.25rem;
}
.footer__col a { font-size: 14px; color: rgba(249,247,247,0.85); }
.footer__col a:hover { color: var(--lime); }  /* navy highlight on hover */
.footer__brand .logo .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--lime); }
```

### 7. FAQ Accordion
Use native `<details>` + `<summary>` — no JS required.
```html
<details class="faq__item">
    <summary>Question text here</summary>
    <div class="faq__answer">Answer text here</div>
</details>
```
```css
.faq__item { border-top: 0.5px solid var(--line); }
.faq__item summary {
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 0.85rem 0; cursor: pointer;
    font-weight: 500; font-size: 14px; color: var(--ink);
    list-style: none;
}
.faq__item summary::-webkit-details-marker { display: none; }
.faq__item summary::after {
    content: "+"; /* or use SVG background */
    flex-shrink: 0; width: 20px; height: 20px;
    text-align: center; line-height: 20px;
    font-size: 16px; font-weight: 400;
    color: var(--muted);
}
.faq__item[open] summary::after { content: "−"; }
.faq__answer { padding-bottom: 0.85rem; font-size: 14px; color: var(--ink-2); line-height: 1.6; }
```
FAQ cards: 2-column grid (`grid-template-columns: 1fr 1fr`), each card is a `.faq__cat` with `.faq__item` children.

### 8. Page Hero (subpages)
```css
.page-hero {
    background: var(--lime);  /* dark navy */
    text-align: center;
    padding: 10rem 1.25rem 5rem;
}
.page-hero .eyebrow { color: rgba(249,247,247,0.65); margin-bottom: 1.25rem; }
.page-hero .eyebrow::before { background: rgba(249,247,247,0.3); }
.page-hero h1 {
    font-size: clamp(2rem, 4.5vw, 3.5rem);
    font-weight: 600; color: var(--bg);
    line-height: 1.05; letter-spacing: -0.04em;
    max-width: 640px; margin: 0 auto 1rem;
}
.page-hero p {
    font-size: 16px; color: rgba(249,247,247,0.7);
    max-width: 520px; margin: 0 auto; line-height: 1.7;
}
```

### 9. Legal Content Sections
```css
.legal-section { margin-bottom: 2.5rem; }
.legal-section h2 {
    font-size: 1.125rem; font-weight: 600;
    color: var(--lime); letter-spacing: -0.3px;
    margin-bottom: 1rem;
}
.legal-section h3 {
    font-size: 15px; font-weight: 600;
    color: var(--ink); margin: 1.25rem 0 0.5rem;
}
.legal-section p {
    font-size: 14px; line-height: 1.8;
    color: var(--ink-2); margin-bottom: 0.75rem;
}
.legal-section ul { list-style: disc; padding-left: 1.5rem; margin-bottom: 0.75rem; }
.legal-section li { font-size: 14px; line-height: 1.7; color: var(--ink-2); margin-bottom: 0.35rem; }
.legal-section .def { margin-bottom: 0.5rem; }
.legal-section .def strong { font-weight: 600; color: var(--ink); }
```

---

## Animations

| Animation | Trigger | Implementation |
|-----------|---------|----------------|
| Scroll reveal | `IntersectionObserver` | Add `.reveal-pending` class, swap to `.is-visible` on intersect |
| Hero word split | Page load | JS splits heading into `<span class="word">` elements with staggered `--i` delays |
| Counter count-up | Scroll into view | `requestAnimationFrame` easing from 0 to target |
| Marquee scroll | CSS animation | Infinite `translateX` loop, paused on hover |
| Parallax pixels | Scroll position | `[data-speed]` attribute, `translate3d` on scroll |
| Card hover lift | CSS `:hover` | `translateY(-4px)` + shadow change |
| CTA magnetic | `mousemove` | Subtle translate toward cursor on `.cta-dark__btn` |

---

## Responsive Breakpoints

| Breakpoint | Behavior |
|------------|----------|
| `max-width: 880px` | Section headers stack vertically; nav links hide |
| `max-width: 720px` | Grids collapse to single column; section padding reduces; hero size shrinks |

---

## Language & Content Rules

- **Swedish** for all public-facing text (UI labels, nav, headings, body, legal)
- **English** for code comments only (rare, avoid comments generally)
- Always use `lang="sv"` on `<html>`
- Swedish number formatting: space as thousand separator, comma as decimal (`1 000 000 kr`, `30,0 %`)

---

## File Checklist for New Pages

Every page must include:
- [ ] Google Fonts link (Inter + Fraunces)
- [ ] Complete `:root` CSS variable block (all variables above)
- [ ] Base reset: `*{box-sizing:border-box;margin:0;padding:0}`
- [ ] Body: `font-family:var(--sans);background:var(--bg);color:var(--ink)`
- [ ] Floating pill nav (`.topnav` + `.topnav__bar`) with all links + CTA
- [ ] Dark footer (exact copy from landing_v2)
- [ ] Heading includes at least one `<span class="serif-em">` for brand voice
- [ ] All "Anmäl skada" buttons use `var(--cta)` or `#f7d154` with dark text
- [ ] No hardcoded hex colors — use CSS variables except for `#f7d154` and `#e6c44d` in CTA contexts
- [ ] Responsive: works at 375px and 1280px wide
