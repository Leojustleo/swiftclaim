# Knowledge Graph in "Kunskap" — Design

**Date:** 2026-06-12
**Status:** Approved by Leo

## Goal

Make the legal knowledge vault (`swiftclaim-obsidian/`, ~1,760 notes) visually explorable inside the OS Dashboard's Kunskap view, as an Obsidian-style knowledge graph: nodes = notes, edges = `[[wiki-links]]`.

## Decisions (from brainstorming)

- **Scope:** whole vault by default — all categories including isolated law paragraphs.
- **Static layout:** positions computed once server-side, frozen. No live physics, no gravity, no node dragging. Pan + zoom only.
- **Filters:** category chips, statute dropdown, ARN outcome filter, free-text search highlight.
- **Click:** node opens a preview drawer with note content and clickable links (jump node-to-node), lagen.nu button where the note has a `source_url`.

## Architecture

```
swiftclaim-obsidian/*.md
        │  (rglob + wiki-link parse + force layout, cached)
        ▼
backend/app/graph.py ──► GET /api/graph        (nodes+edges+positions JSON)
                     ──► GET /api/graph/note   (single note content for preview)
        │
        ▼
os/api.js (bridge, graceful degrade) ──► os/graph.js (canvas renderer)
        │
        ▼
Kunskap view: full-width graph panel (filter bar + canvas + preview drawer)
```

## Backend

### `backend/app/graph.py`

**Graph build:**
- Walk `VAULT_PATH.rglob("*.md")` (reuse `rag.py` constants). Skip `Index/` and `README.md`.
- Node id = filename stem (vault convention: links resolve by stem). Category = top-level directory (`ARN`, `Lagstiftning`, `Koncept`, `Villkor`, `Praxis`, `Förarbeten`, `Vägledning`).
- Parse `[[target]]` and `[[target|alias]]` from full file text (frontmatter included). Edge = (source stem → target stem), deduplicated.
- Link targets with no matching file become **ghost nodes** (`exists: false`) — rendered faded.
- Node metadata: `id`, `label`, `category`, `degree`, `exists`, plus `statute` and `outcome` pulled from YAML frontmatter when present (for filters).

**Layout (computed server-side, once):**
- Fruchterman–Reingold force layout over the connected component(s), ~200 iterations, grid-bucket neighbor approximation so 1,760 nodes stays fast. Deterministic seed.
- Isolated nodes (degree 0) are not thrown into the simulation: arranged in compact per-category/per-statute blocks around the periphery of the connected core.
- Node `size` ∝ `sqrt(degree)`, clamped.

**Caching:**
- Result JSON written to `backend/data/graph_layout.json` with a vault fingerprint (file count + max mtime). On request: fingerprint matches → serve cache; else rebuild. First build may take a few seconds; subsequent requests are instant.

### Endpoints (in `main.py`)

- `GET /api/graph` → `{ nodes: [...], edges: [[srcIdx, dstIdx], ...], categories: [...], statutes: [...], stats }`. Edges as index pairs to keep payload small (~1,760 nodes + ~700 edges ≈ a few hundred KB).
- `GET /api/graph/note?id=<stem>` → `{ id, label, category, frontmatter, body, links_out, links_in, source_url }`. 404 for ghosts (frontend shows "note missing in vault" message instead).

## Frontend

### `os/graph.js` (new file, vanilla JS, no libraries)

Canvas renderer module exposing `SwiftclaimGraph.init(container, data)`:
- **Render:** edges first (thin, low alpha), then nodes (filled circles, category color). DevicePixelRatio-aware.
- **Pan/zoom:** wheel = zoom toward cursor, drag = pan. Zoom clamped.
- **Labels:** hidden at far zoom; appear for nodes whose projected size passes a threshold, plus always for hovered/selected node and its neighbors.
- **Hover:** spatial-grid hit test; highlight node + neighbors + connecting edges, dim the rest.
- **Selection:** click → callback to app.js → preview drawer.
- **Filtering:** module takes a predicate; filtered-out nodes/edges skipped at draw time (no re-layout — positions are static).

### Kunskap view changes (`os/index.html`, `os/app.js`, `os/styles.css`)

- New full-width panel **"Kunskapsgraf"** at the top of `#knowledgeView`, above the existing split layout. Height ≈ 60vh.
- **Filter bar:** category chips (toggle, colored to match node colors), statute `<select>`, ARN-outcome `<select>` (bifall/avslag/delvis), search input (matches light up, others dim).
- **Preview drawer:** right-side overlay inside the panel. Shows note title, category badge, minimal markdown rendering of body (headings/bold/lists/links — tiny hand-rolled renderer), outgoing + incoming links as clickable rows (click = select that node, recenter), "Öppna på lagen.nu" button when `source_url` exists.
- **Loading:** graph data fetched lazily the first time Kunskap view is opened (not at app start). Spinner while loading.
- **Degrade:** backend unreachable → panel body shows "Starta backend för att se kunskapsgrafen" (same pattern as other api.js features).

### Colors

Use existing dashboard palette/badge conventions: Lagstiftning green, ARN orange, Koncept purple, Villkor teal, Praxis/Förarbeten/Vägledning assigned distinct muted tones; ghost nodes grey at 40% opacity. Defined as CSS variables → read into canvas at init.

## Error handling

- Vault missing / empty → `/api/graph` returns 503 with detail; frontend shows degrade message.
- Cache file corrupt → silently rebuild.
- Note fetch 404 (ghost) → drawer explains the note is referenced but doesn't exist yet.

## Testing

- **Backend (pytest, pure functions):** wiki-link parsing (incl. alias form), ghost detection, fingerprinting, layout determinism (same input → same positions), isolated-node block placement.
- **Eval-style smoke:** build graph over real vault; assert node count ≈ file count, known edge exists (e.g. an ARN decision → `Avtalslagen 36 §`), no NaN positions.
- **Frontend:** manual verification in browser (project has no JS test rig): pan/zoom, filters, hover, preview, degrade path with backend stopped.

## Out of scope (YAGNI)

- Editing notes from the graph
- Live re-layout / physics / dragging nodes
- Graph for case data (only the vault)
