import globals from "globals";
import pluginJs from "@eslint/js";
import pluginReact from "eslint-plugin-react";
import pluginReactHooks from "eslint-plugin-react-hooks";
import pluginUnusedImports from "eslint-plugin-unused-imports";

export default [
  // built output and the copied workspace client (a built bundle, not source)
  { ignores: ["dist/**", "public/xyz/**"] },
  {
    files: [
      "src/**/*.{js,mjs,cjs,jsx}",
    ],
    ...pluginJs.configs.recommended,
    ...pluginReact.configs.flat.recommended,
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    settings: {
      react: {
        version: "detect",
      },
    },
    plugins: {
      react: pluginReact,
      "react-hooks": pluginReactHooks,
      "unused-imports": pluginUnusedImports,
    },
    rules: {
      ...pluginJs.configs.recommended.rules,
      ...pluginReact.configs.flat.recommended.rules,
      "no-unused-vars": "off",
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "error",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": [
        "warn",
        {
          vars: "all",
          varsIgnorePattern: "^_",
          args: "after-used",
          argsIgnorePattern: "^_",
        },
      ],
      "react/prop-types": "off",
      "react/react-in-jsx-scope": "off",
      "react/no-unknown-property": [
        "error",
        {
          // r3f (react-three-fiber) treats Three.js properties as JSX
          // props on auto-extended elements. The linter doesn't know
          // about these — whitelist the common r3f attributes so the
          // VoiceOverlay 3D scene doesn't trip 12 false positives.
          ignore: ["cmdk-input-wrapper", "toast-close",
                   "position", "args", "vertexShader", "fragmentShader",
                   "uniforms", "angle", "penumbra", "decay", "intensity"],
        },
      ],
      "react-hooks/rules-of-hooks": "error",
    },
  },
];
