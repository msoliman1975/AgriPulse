// Zero-dependency CSV export. The platform ships no CSV/PDF library, so
// reports export their raw tabular data through here and rely on the
// browser's print-to-PDF for the formatted version. Builds an RFC-4180
// CSV from a header + row matrix and triggers a download.

// UTF-8 byte-order mark (U+FEFF), prepended to downloads so Excel
// detects the encoding (otherwise Arabic column data shows as mojibake).
// Built from a char code so no invisible literal lives in the source.
const BOM = String.fromCharCode(0xfeff);

export type CsvCell = string | number | boolean | null | undefined;

function escapeCell(value: CsvCell): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  // Quote cells containing a comma, quote, or newline; double up any
  // embedded quotes (RFC 4180).
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function toCsv(headers: readonly string[], rows: readonly CsvCell[][]): string {
  const lines = [headers.map(escapeCell).join(",")];
  for (const row of rows) {
    lines.push(row.map(escapeCell).join(","));
  }
  return lines.join("\r\n");
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([BOM, csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
