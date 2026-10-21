# Egyptian pesticide register extract

`apc-egypt-register.csv` — registered plant protection products for mango,
potato, and date palm, with the crop and pest each one is approved for.

## Where it comes from

The Agricultural Pesticide Committee (APC) of the Ministry of Agriculture and
Land Reclamation. The register is an online database, not a document.

- Product list and crop search: `http://www1.apc.gov.eg/en/products/showall.aspx`
- One product: `http://www1.apc.gov.eg/en/products/{id}/details.aspx`
- Print view of one product: `http://www1.apc.gov.eg/en/print.aspx?id={id}`

The site is HTTP only and ASP.NET WebForms. It rejects a POST that omits the
`__VIEWSTATEENCRYPTED` hidden field, so a scraper has to send every hidden
input from the page it just read, not only the viewstate.

**Pulled 2026-08-27.** The site footer read "Last Update 8/25/2026".

## How it was pulled

`apc-harvest.ps1`, in this directory. It searches by crop name for Mango,
Potato, Date palm, and Dates, walks the paged result grid, then reads each
product page. Run it again to refresh.

One correction pass ran after it. The product page renders several active
ingredients inside a nested table, and the first script captured only the
first name. The print view lists them all, so a second pass re-read every
product through `print.aspx` and replaced the `active_ing` column.

## What is in it

753 rows, one per product and crop and pest. 721 products.

| Crop | Registered products | Rows |
|---|---|---|
| Potato | 528 | 608 |
| Mango | 100 | 120 |
| Date palm | 9 | 24 |
| Dates (stored fruit) | 1 | 1 |

631 of the 721 products are still registered. The other 90 have the status
`Registration didn't renew` and must not be seeded as usable.

## Columns

| Column | Example |
|---|---|
| `product_id` | 31027 (the site's internal id, not the registration number) |
| `reg_no` | 5391 |
| `cas_no` | 131860-33-8 |
| `trade_name` | Agonay 32.5% SC |
| `active_ing` | Azoxystrobin + Difenoconazole |
| `concentration` | 20 + 12.5 |
| `status` | Registered / Registration didn't renew / Registration cancelled |
| `manufacturer` | Jiangyin Suli Chemical Co., Ltd |
| `usage_class` | Fungicide, Insecticide, Herbicide, acaricide, Nematicide, and combinations |
| `who_class` | Low III, Mod II, and so on |
| `formulation` | SC, EC, WP, WG, SL, FS, CS, DF, AS |
| `country` | China |
| `crop_id`, `crop` | 115, Mango |
| `crop_description` | Growth stage restriction. Blank on 621 of 656 registered rows |
| `pest` | Anthracnose |
| `rate` | 60 cc/ 100 Liter water |
| `phi` | 60 Day |
| `notes` | Poison bait, Sandy Soil, and so on. Filled on 5 rows |

## What the data says about rates

Of 656 registered rows:

| Rate basis | Rows |
|---|---|
| Per 100 litres of water | 421 |
| Per feddan | 195 |
| Per 1 litre of water | 5 |
| Per ton or per kg of seed | 10 |
| Per 20 litres of water | 1 |
| Per cubic metre (fumigation) | 2 |

**No registered dose is written per plant or per hectare.** Per-plant rates for
date palm and mango come from the literature, not from the register.

**No dose is a range.** All 656 are single numbers. Leading units are cc (319),
g (268), Liter (57), Kg (5).

## Known gaps in this extract

- 198 products list two active ingredients. On 26 of them the register gives
  one combined concentration instead of one per active, so the split cannot be
  recovered from this data. Example: Rolex 50% WP is copper oxychloride plus
  metalaxyl at "50".
- Arabic product names are not captured. The English page carries only the
  English trade name.
- Maximum applications per season is not in the register. It has to come from
  the label or the recommendations book.
- The register gives the legal dose. It does not give the spray programme: how
  many sprays, at what interval, in what order. That is in the 2025 edition of
  the approved recommendations book for agricultural pest control, published by
  the same committee in October 2025.

## Fertilizers

There is no public fertilizer register. Fertilizers fall under Ministerial
Decree 84 of 2023 on registration, import, and trade of fertilizers and soil
conditioners, but no searchable database exists. Nutrient content is chemistry,
so fertilizer rows can be seeded from the compound itself.

## Related

`docs/proposals/quantified-plan-procedures-and-work-orders.md` uses this file
as the source for the `input_products` catalog.
