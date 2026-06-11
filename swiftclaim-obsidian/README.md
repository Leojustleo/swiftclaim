---
type: index
---

# Swiftclaim Legal Vault — MVP

Detta är en RAG-vault byggd från svenska försäkringsbeslut och lagrum. Använd den för att hitta argument när du driver skadeärenden för Swiftclaim.

## Struktur

- **[[ARN/]]** — Anonymiserade beslut från Allmänna reklamationsnämnden (5 st i MVP, skalas senare)
- **[[Lagstiftning/]]** — Lagrum med text från lagen.nu (FAL, Avtalslagen, Distansavtalslagen, Konsumentköplagen, Konsumenttjänstlagen)
- **[[Koncept/]]** — Juridiska koncept som ARN refererar till (stubs som fylls i över tid)
- **[[Index/]]** — Auto-genererade kategori-index

## Demo: ARN-beslut att utforska

- [[ARN 2021-17230]] — Maskinskada på bil, säkerhetsföreskrift om service
- [[ARN 2018-14272]] — Tidigt referat-beslut
- [[ARN 2019-04350]]
- [[ARN 2021-17441]]
- [[ARN 2022-15738]]

## Mest relevanta lagrum

- [[FAL 4 kap 6 §]] — Nedsättning vid åsidosättande av säkerhetsföreskrift
- [[FAL 4 kap 11 §]] — Förbud mot att klä säkerhetsföreskrift som omfattningsvillkor
- [[FAL 1 kap 6 §]] — Tvingande regler
- [[Avtalslagen 36 §]] — Generalklausulen om oskäliga villkor

## Köra RAG från terminal

```bash
cd ~/claude-code/Swiftclaim/law-pipeline
source .venv/bin/activate
python query.py "din fråga på svenska"
```

Voyage embeddings + Claude (via OpenRouter). Cache i `.embeddings.json`.

## Lägga till fler beslut

```bash
python main.py --limit 50          # skala till 50 beslut
python fill_stubs.py               # fyll nya lagrum-stubs från lagen.nu
python query.py --reindex "..."    # bygg om embedding-index
```
