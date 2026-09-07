import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import globals from "globals";

// Flat ESLint config for the apps/* workspace (soothe-web, soothe-bridge, sobo).
// Mirrors the conventions used in client/typescript/eslint.config.js.
export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/node_modules/**",
      "apps/sobo/out/**",
      "apps/sobo/src/preload.cjs",
      "apps/sobo/src/setup-preload.cjs",
    ],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
  // Browser scripts (sobo setup wizard, web frontend).
  {
    files: ["apps/sobo/src/setup.js", "apps/soothe-web/src/**/*.tsx"],
    languageOptions: {
      globals: {
        ...globals.browser,
      },
    },
  },
  // Electron main process (Node.js + Electron globals).
  {
    files: ["apps/sobo/src/main.ts"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
);
