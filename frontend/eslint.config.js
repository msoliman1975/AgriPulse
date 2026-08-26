import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Tooling configs (vite/tailwind/postcss/eslint) parse fine via their own
  // toolchains; linting them adds friction without much benefit.
  {
    ignores: [
      "dist",
      "node_modules",
      "coverage",
      "vite.config.ts",
      "vitest.config.ts",
      "tailwind.config.ts",
      "postcss.config.js",
      "eslint.config.js",
      "prettier.config.js",
      // Playwright e2e suite lives in its own tsconfig project (referenced
      // from the root tsconfig.json). Type-checking happens via
      // `tsc -b` / `playwright test`; pulling e2e into eslint's typed
      // rules here would require a second parserOptions.project entry
      // and adds no signal over what the Playwright runner already gives
      // us.
      "e2e",
    ],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    files: ["src/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        project: ["./tsconfig.app.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "jsx-a11y": jsxA11y,
    },
    settings: {
      react: { version: "detect" },
    },
    rules: {
      ...react.configs.recommended.rules,
      ...react.configs["jsx-runtime"].rules,
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-misused-promises": [
        "error",
        { checksVoidReturn: { attributes: false } },
      ],
      // TypeScript already enforces prop types via component signatures;
      // react/prop-types is the JS-era equivalent and only generates noise
      // here (false-positives on `id` props that are typed via TS).
      "react/prop-types": "off",
      // Fire-and-forget promises in event handlers (`onClick={() => foo()}`)
      // are common and idiomatic; the rule's `void`/`.catch()` requirements
      // add ceremony without surfacing real bugs. Demoted to warn so the
      // signal stays but CI doesn't fail.
      "@typescript-eslint/no-floating-promises": "warn",
      // Design-system guard (F-6/F-11): forbid the pre-rename Tailwind palette
      // (slate/gray/zinc/neutral/stone/brand/emerald/rose/red) — new code must
      // use the `ap-*` tokens. Promoted to `error` once the codebase reached
      // zero legacy usages (the full migration is complete); labs/map is
      // exempt below while it's WiP.
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "Literal[value=/(?:text|bg|border|ring|divide|from|via|to|fill|stroke|outline|placeholder|accent|caret|shadow)-(?:slate|gray|zinc|neutral|stone|brand|emerald|rose|red)-\\d/]",
          message:
            "Use the ap-* design tokens (text-ap-ink, bg-ap-panel, border-ap-line, text-ap-crit, …) instead of the pre-rename palette.",
        },
        {
          selector:
            "TemplateElement[value.raw=/(?:text|bg|border|ring|divide|from|via|to|fill|stroke|outline|placeholder|accent|caret|shadow)-(?:slate|gray|zinc|neutral|stone|brand|emerald|rose|red)-\\d/]",
          message:
            "Use the ap-* design tokens (text-ap-ink, bg-ap-panel, border-ap-line, text-ap-crit, …) instead of the pre-rename palette.",
        },
        // Design-system guard, part 2 (DS-8). The primitives in
        // src/components/ existed for two months and got 0-10 adopters each,
        // because every one of them competed with a className string that was
        // already there. The two that reached full adoption (<Skeleton>,
        // <Pill>) are the two with no such rival. Convention was tried and it
        // lost; these rules are what make it stick. src/components/** is
        // exempt below — the primitives legitimately contain the raw markup.
        {
          selector: "JSXOpeningElement[name.name='table']",
          message:
            "Use <DataTable> for data, or the <Table>/<Thead>/<Tbody>/<Tr>/<Th>/<Td> primitives for a bespoke table.",
        },
        {
          selector: "JSXOpeningElement[name.name='h1']",
          message:
            "Page titles go through <PageHeader> so the type scale stays single-valued (F-11).",
        },
        {
          selector: "Literal[value=/(?:^|\\s)btn(?:-primary|-ghost|-sm)?(?:\\s|$)/]",
          message: "The .btn layer was retired in DS-8 — use <Button> or <LinkButton>.",
        },
        {
          selector: "Literal[value=/(?:^|\\s)card(?:\\s|$)/]",
          message: "The .card layer was retired in DS-8 — use <Card>.",
        },
        {
          selector:
            "Literal[value=/rounded-(?:xl|lg|card)\\s+border\\s+border-ap-line\\s+bg-ap-panel/]",
          message: "This is <Card>. Inlining it is how we ended up with three card styles.",
        },
        // Shadowing a shipped primitive re-creates the divergence the
        // primitive exists to prevent. `Row` is deliberately NOT listed — it
        // is a reasonable local name for a row renderer and no primitive
        // claims it.
        {
          selector:
            "FunctionDeclaration[id.name=/^(Card|Field|Page|PageHeader|Pagination|Toolbar|DataTable|RowList|AsyncBoundary)$/]",
          message:
            "Import the primitive from @/components instead of declaring a local one that shadows it.",
        },
      ],
    },
  },
  {
    // mapbox-gl's TypeScript types are loose around runtime mutators
    // (addSource, setData, queryRenderedFeatures…). The
    // `@typescript-eslint/no-unsafe-*` rules cascade through every map
    // interaction and add noise without value — these are stable APIs
    // we exercise heavily in production. Keep typed rules on for the
    // rest of src/ where they catch real bugs.
    files: [
      "src/modules/labs/map/**/*.{ts,tsx}",
      "src/modules/labs/mapnext/**/*.{ts,tsx}",
      // The Farm Timeline's own canvas. Same reasoning as the two above:
      // it is a MapLibre surface that talks to the same loose runtime
      // mutators and passes raw colour strings to paint specs. Only the
      // canvas is listed — the rest of src/modules/timeline/** keeps the
      // full rule set.
      "src/modules/timeline/components/TimelineMap.tsx",
    ],
    rules: {
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      // Map layers legitimately pass raw color strings to mapbox paint specs,
      // and the surface is WiP — exempt it from the palette guard for now.
      // `mapnext` (the live Farm Console) joins it under the same reasoning:
      // its panels are map overlays being actively reshaped, and freezing
      // their surface markup now would just create churn. Revisit when the
      // console settles.
      "no-restricted-syntax": "off",
    },
  },
  {
    // The primitives are where the raw markup is supposed to live, and where
    // these component names are supposed to be declared.
    files: ["src/components/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": "off",
    },
  },
  {
    // Test files legitimately mock with `any`, spy on instance methods
    // (vi.spyOn flags as unbound), and may return mock values whose type
    // can't be derived. Disable the type-strict rules here so the signal
    // stays high in src/ where it matters.
    files: ["**/*.{test,spec}.{ts,tsx}", "tests/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-return": "off",
      "@typescript-eslint/unbound-method": "off",
    },
  },
);
