module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['@typescript-eslint'],
  extends: ['eslint:recommended'],
  ignorePatterns: ['dist/', 'node_modules/', 'tests/'],
  rules: {
    'no-undef': 'off',
    'no-unused-vars': 'off',
    'no-empty': ['error', { allowEmptyCatch: true }],
    'no-useless-escape': 'off',
    'no-case-declarations': 'off',
  },
}
