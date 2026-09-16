module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs', 'src/api/generated/*'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    'react-refresh/only-export-components': [
      'warn',
      { allowConstantExport: true, allowExportNames: ['buttonVariants', 'badgeVariants', 'toast', 'router'] },
    ],
    // No `any` except axios adapters (coding standard 4)
    '@typescript-eslint/no-explicit-any': 'error',
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
  },
  overrides: [
    { files: ['src/api/axios.ts'], rules: { '@typescript-eslint/no-explicit-any': 'off' } },
  ],
};
