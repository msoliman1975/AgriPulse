# AgriPulse documentation site — simulation

The AgriPulse documentation site, served at `docs.agripulse.cloud`.
Plain HTML, no build step at serve time, no JavaScript framework.

## Open it

Open `index.html` in a browser. Every page is a plain file and every link is relative,
so it also works from a static host or an S3-style bucket with no configuration.

## Pages

| File | What it is |
| --- | --- |
| `index.html` | Landing page. Short hero, then the eight process tiles, then what AgriPulse is, then the crop tiles and support. |
| `process-*.html` | Eight processes, one page each. Each carries a clip slot, a written step-by-step guide, and one clip slot per step. |
| `kb.html` | Knowledge Base index: twelve crop tiles, then the catalogs that are not crop specific. |
| `kb-crop-*.html` | Twelve crop pages covering all 23 seeded crops. |
| `kb-*.html` | Nine catalogs across all crops: indices, weather, decision trees, signals, phenology, taxonomy, attributes, plans, platform. |
| `concepts.html` | The vocabulary the rest of the site uses. |
| `support.html` | FAQs, ask the AgriPulse team, request a feature. Placeholders. |
| `credits.html` | Photograph sources and licences. |
| `_structure-proposal.html` | The first structure proposal, kept for reference. Not linked from the site. |

## Rebuild

All page content lives in `build.py`. Edit the content there and run:

```
python docs/website/build.py
```

It rewrites every page except `_structure-proposal.html`. The stylesheet
`assets/site.css` and the images in `img/` are edited by hand, not generated.

## Photographs

The photographs come from Wikimedia Commons and public agencies. Licences and
attributions are listed on `credits.html`, which the footer links to on every page.
Replace them with AgriPulse field photographs before the site goes public.

## Not done yet

- No Arabic pages. The `العربية` button only flips the layout to right to left,
  so the layout can be checked early. Crop tiles already carry the Arabic crop name.
- No search. The site has no search box yet.
- No clips. Every process page has a slot for a full walkthrough and a slot for each
  step, all marked "Not recorded".
- The three support pages are described, not designed.
- No screenshots of the product inside the process pages.
- Counts on the Knowledge Base pages were typed from the seed files on
  18 August 2026. They should be generated from the database instead.
