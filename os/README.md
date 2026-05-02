# Swiftclaim OS-prototyp

Det här är en självständig kontrollpanelsprototyp för hantering av svenska egendomsskador för privatkonsumenter.

## Det som fungerar

- Exempelintag från Swiftclaim.se
- Regelbaserat AI-utkast till bedömningskort
- Ärenderegister med filter och sök
- Flödestavla efter status
- Ärendedetalj med ansvarig, status, prioritet, anteckningar, uppgifter, filer och tidslinje
- Lokal fillagring i webbläsaren via IndexedDB
- Import och export av kontrollpaneldata som JSON
- LLM-wiki-liknande markdownexport per ärende

## Riktning för datamodellen

Prototypen håller isär operativt system och kunskapslager:

- Operativ data: ärenden, kunder, bedömningskort, anteckningar, uppgifter, filer, händelser och utfall
- Råkällor: intag som JSON, dokument, anteckningar, tidslinje och utfall
- Kunskapsexport: en markdownsida per ärende med YAML-frontmatter och källreferenser

Det gör att en framtida bakände kan skala, samtidigt som varje avslutat ärende blir användbart för AI-baserad granskning och analys av försäkringsbolagens mönster.

## Kör lokalt

Öppna `index.html` direkt i en webbläsare, eller servera mappen med valfri statisk webbserver.
