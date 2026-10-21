import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

const EN_DIR = path.resolve('frontend/src/i18n/locales/en');
const AR_DIR = path.resolve('frontend/src/i18n/locales/ar');

// Values that are legitimately identical across EN/AR.
const ACRONYMS = new Set([
  'NDVI', 'NDWI', 'EVI', 'SAVI', 'NDRE', 'GNDVI', 'ET₀', 'ET0',
  'AgriPulse', 'Sentinel',
]);

function isExcludedIdentical(value) {
  if (typeof value !== 'string') return true; // non-strings: skip identical check
  const v = value.trim();
  if (v === '') return true;
  if (ACRONYMS.has(v)) return true;
  // pure numbers (incl decimals, %, units like 10m, 3m)
  if (/^[\d.,%\s]+$/.test(v)) return true;
  // pure punctuation / symbols
  if (/^[^\p{L}]+$/u.test(v)) return true; // no letters at all
  // single brand-ish token with no spaces and no Arabic letters and capitalized/acronym-like
  if (!/\s/.test(v) && !/[؀-ۿ]/.test(v) && /^[A-Za-z][A-Za-z0-9₀-₉.\-]*$/.test(v)) {
    // single ASCII token, no Arabic — treat as brand/code token
    return true;
  }
  return false;
}

function readJson(p) {
  let text = readFileSync(p, 'utf8');
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1); // strip BOM
  return JSON.parse(text);
}

function flatten(obj, prefix = '', out = {}) {
  if (obj === null || typeof obj !== 'object') {
    out[prefix] = obj;
    return out;
  }
  if (Array.isArray(obj)) {
    obj.forEach((item, i) => flatten(item, prefix ? `${prefix}.${i}` : String(i), out));
    return out;
  }
  for (const [k, val] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (val !== null && typeof val === 'object') {
      flatten(val, key, out);
    } else {
      out[key] = val;
    }
  }
  return out;
}

const enFiles = readdirSync(EN_DIR).filter((f) => f.endsWith('.json')).sort();
const arFiles = new Set(readdirSync(AR_DIR).filter((f) => f.endsWith('.json')));

const report = [];
const summary = [];

for (const file of enFiles) {
  const ns = file.replace(/\.json$/, '');
  const enFlat = flatten(readJson(path.join(EN_DIR, file)));
  let arFlat = {};
  let arMissingFile = false;
  if (arFiles.has(file)) {
    arFlat = flatten(readJson(path.join(AR_DIR, file)));
  } else {
    arMissingFile = true;
  }

  const enKeys = Object.keys(enFlat);
  const arKeys = Object.keys(arFlat);
  const enKeySet = new Set(enKeys);
  const arKeySet = new Set(arKeys);

  const missingInAr = enKeys.filter((k) => !arKeySet.has(k)).sort();
  const orphanInAr = arKeys.filter((k) => !enKeySet.has(k)).sort();

  const identical = [];
  for (const k of enKeys) {
    if (!arKeySet.has(k)) continue;
    const ev = enFlat[k];
    const av = arFlat[k];
    if (ev === av && !isExcludedIdentical(ev)) {
      identical.push({ key: k, value: ev });
    }
  }
  identical.sort((a, b) => a.key.localeCompare(b.key));

  report.push({ ns, arMissingFile, enTotal: enKeys.length, missingInAr, orphanInAr, identical });
  summary.push({
    ns,
    enTotal: enKeys.length,
    missing: missingInAr.length,
    orphan: orphanInAr.length,
    identical: identical.length,
    arMissingFile,
  });
}

// Output as JSON for the caller to format.
console.log(JSON.stringify({ report, summary }, null, 2));
