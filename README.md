# Swiftclaim

Swiftclaim.se — a Swedish service that helps property owners get the full insurance payout they're entitled to after damage claims.

This repo contains two surfaces and a shared design contract.

## Layout

```
.
├── site/                 Public marketing site (Swedish, static HTML)
│   ├── landing_v2.html                     Current landing page
│   ├── swiftclaim_testimonials_page.html   Earlier landing page with testimonials
│   └── om-oss.html                         About-us page
│
└── os/                   Internal claims-handling dashboard prototype
    ├── index.html
    ├── styles.css
    ├── app.js
    └── README.md         Details on the OS prototype
```

## Run locally

**Public site** — open `site/swiftclaim_testimonials_page.html` in a browser. The "Om oss" nav link reaches the about page; both pages link back to each other.

**OS dashboard** — open `os/index.html` in a browser, or serve the `os/` folder with any static server. State is persisted locally via IndexedDB; data can be exported as JSON or per-case Markdown. See `os/README.md` for the full feature list.
