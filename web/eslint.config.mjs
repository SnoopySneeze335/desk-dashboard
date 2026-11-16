// SPDX-License-Identifier: GPL-3.0-or-later
import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["assets/**/*.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: globals.browser },
    rules: { "no-unused-vars": ["error", { caughtErrors: "none" }] },
  },
];
