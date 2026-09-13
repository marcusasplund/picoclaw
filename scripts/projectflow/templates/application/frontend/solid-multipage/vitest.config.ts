import path from "path";
import { defineConfig } from 'vitest/config';
import solidPlugin from 'vite-plugin-solid';

export const vitestConfig = defineConfig({
  // Hot-reload branches are development tooling, not application behavior.
  plugins: [solidPlugin({ hot: false })],
  resolve: {
    alias: {
      "~": path.resolve(__dirname, "./src"),
    },
    conditions: ['development', 'browser'],
  },
  test: {
    coverage: {
      exclude: ['components', '**/*.css'],
      provider: "v8",
      reporter: ["text", "html"],
      thresholds: {
        branches: 100,
        functions: 100,
        lines: 100,
        statements: 100,
      },
    },
    environment: 'happy-dom',
    globals: true,
    include: ['src/**/*.{test,spec}.?(c|m)[jt]s?(x)'],
    setupFiles: './src/setupTests.ts',
  },
});

export default vitestConfig;
