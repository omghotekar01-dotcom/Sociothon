import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {globals: {window:'readonly', document:'readonly', localStorage:'readonly', location:'readonly', history:'readonly', fetch:'readonly', setTimeout:'readonly', clearTimeout:'readonly', setInterval:'readonly', clearInterval:'readonly', addEventListener:'readonly', removeEventListener:'readonly', URL:'readonly', URLSearchParams:'readonly', Blob:'readonly', FormData:'readonly', File:'readonly', HTMLElement:'readonly', KeyboardEvent:'readonly', RequestInit:'readonly', crypto:'readonly', React:'readonly', console:'readonly'}},
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      'no-undef': 'off',
      'no-empty': ['error', {allowEmptyCatch:true}]
    }
  }
);
