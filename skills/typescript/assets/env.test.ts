import { describe, expect, it } from 'vitest'
import { loadEnv } from './env.ts'

describe('loadEnv', () => {
  it('applies defaults and coerces numbers', () => {
    expect(loadEnv({ PORT: '8080' })).toMatchObject({ PORT: 8080, NODE_ENV: 'development' })
  })

  it('lists every invalid variable', () => {
    expect(() => loadEnv({ PORT: 'nope', LOG_LEVEL: 'loud' })).toThrow(
      /PORT[\s\S]*LOG_LEVEL|LOG_LEVEL[\s\S]*PORT/,
    )
  })
})
