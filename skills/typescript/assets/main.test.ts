import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import fc from 'fast-check'
import { describe, expect, it } from 'vitest'
import { type Io, run } from './main.ts'
import { mapLimit } from './pool.ts'

function fakeIo(statusFor: (url: string) => number) {
  const out: string[] = []
  const err: string[] = []
  const io: Io = {
    stdout: (l) => out.push(l),
    stderr: (l) => err.push(l),
    fetch: async (input) => new Response(null, { status: statusFor(String(input)) }),
  }
  return { io, out, err }
}

async function urlFile(lines: string[]): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), 'linkcheck-'))
  const file = join(dir, 'urls.txt')
  await writeFile(file, lines.join('\n'))
  return file
}

describe('linkcheck', () => {
  it('exits 0 when every URL is reachable', async () => {
    const { io, out } = fakeIo(() => 200)
    const file = await urlFile(['https://a.test', '# comment', '', 'https://b.test'])
    expect(await run([file], io)).toBe(0)
    expect(out).toHaveLength(2)
  })

  it('exits 1 when a URL fails', async () => {
    const { io, out } = fakeIo((u) => (u.includes('bad') ? 500 : 200))
    const file = await urlFile(['https://ok.test', 'https://bad.test'])
    expect(await run([file, '-c', '1'], io)).toBe(1)
    expect(out.join('\n')).toContain('FAIL 500')
  })

  it('reports network errors as failures instead of crashing', async () => {
    const { io, out } = fakeIo(() => 200)
    const failing: Io = { ...io, fetch: () => Promise.reject(new TypeError('fetch failed')) }
    expect(await run([await urlFile(['https://down.test'])], failing)).toBe(1)
    expect(out.join('\n')).toContain('FAIL TypeError')
  })

  it('prints usage for --help', async () => {
    const { io, out } = fakeIo(() => 200)
    expect(await run(['--help'], io)).toBe(0)
    expect(out.join('\n')).toContain('Usage:')
  })

  it('rejects files with lines that are not URLs', async () => {
    const { io, err } = fakeIo(() => 200)
    expect(await run([await urlFile(['not a url'])], io)).toBe(2)
    expect(err.join('\n')).toContain('not a URL')
  })

  it.each([[[]], [['--concurrency', '0', 'x']], [['--nope']], [['/does/not/exist']]])(
    'exits 2 on bad input %j',
    async (argv) => {
      expect(await run(argv, fakeIo(() => 200).io)).toBe(2)
    },
  )
})

describe('mapLimit', () => {
  it('never exceeds the limit and keeps order', async () => {
    let active = 0
    let peak = 0
    const result = await mapLimit([1, 2, 3, 4, 5, 6], 2, async (n) => {
      active++
      peak = Math.max(peak, active)
      await new Promise((r) => setTimeout(r, 5))
      active--
      return n * 2
    })
    expect(result).toEqual([2, 4, 6, 8, 10, 12])
    expect(peak).toBe(2)
  })
})

describe('mapLimit errors', () => {
  it('rejects with the first error and stops starting new work', async () => {
    const started: number[] = []
    const pending = mapLimit([1, 2, 3, 4], 1, async (n) => {
      started.push(n)
      if (n === 2) throw new Error('boom')
      return n
    })
    await expect(pending).rejects.toThrow('boom')
    expect(started).toEqual([1, 2])
  })

  it('rejects an invalid limit', async () => {
    await expect(mapLimit([1], 0, async (n) => n)).rejects.toThrow(RangeError)
  })
})

describe('mapLimit properties', () => {
  it('returns fn(x) for every item, in order, for any limit', async () => {
    await fc.assert(
      fc.asyncProperty(fc.array(fc.integer()), fc.integer({ min: 1, max: 16 }), async (items, limit) => {
        const out = await mapLimit(items, limit, async (n) => n + 1)
        expect(out).toEqual(items.map((n) => n + 1))
      }),
    )
  })
})
