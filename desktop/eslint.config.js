import js from "@eslint/js"
import tseslint from "typescript-eslint"

export default tseslint.config(
  {
    ignores: [
      "out/**",
      "node_modules/**",
      "renderer/src/generated/**",
      "playwright-report/**",
      "test-results/**",
      "electron-builder.config.cjs",
    ],
  },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
)
