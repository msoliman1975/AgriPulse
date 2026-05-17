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
    },
  },
  {
    // mapbox-gl's TypeScript types are loose around runtime mutators
    // (addSource, setData, queryRenderedFeatures…). The
    // `@typescript-eslint/no-unsafe-*` rules cascade through every map
    // interaction and add noise without value — these are stable APIs
    // we exercise heavily in production. Keep typed rules on for the
    // rest of src/ where they catch real bugs.
    files: ["src/modules/labs/map/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
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
