import { defineConfig, type UserConfig } from 'tsdown'

// Typed const, not `export default defineConfig(...)`: isolatedDeclarations (TS9037)
// rejects default exports whose type must be inferred.
const config: UserConfig = defineConfig({
  entry: ['src/index.ts'],
  format: 'esm',
  platform: 'neutral',
  target: 'es2022',
  dts: true,
  sourcemap: true,
  clean: true,
})

export default config
