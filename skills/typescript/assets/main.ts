#!/usr/bin/env node
import { readFile } from 'node:fs/promises'
import { parseArgs } from 'node:util'
import { mapLimit } from './pool.ts'

const USAGE = `Usage: linkcheck [--concurrency N] [--timeout MS] FILE

Checks every URL in FILE (one per line) with a HEAD request.
Exit codes: 0 all reachable, 1 some failed, 2 bad input.`

export interface Io {
  readonly stdout: (line: string) => void
  readonly stderr: (line: string) => void
  readonly fetch: typeof fetch
}

export interface Check {
  readonly url: string
  readonly ok: boolean
  readonly detail: string
}

async function check(url: string, timeoutMs: number, signal: AbortSignal, io: Io): Promise<Check> {
  try {
    const res = await io.fetch(url, {
      method: 'HEAD',
      redirect: 'follow',
      signal: AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]),
    })
    return { url, ok: res.ok, detail: String(res.status) }
  } catch (error) {
    // Per-URL failures are results, not reasons to stop the run.
    return { url, ok: false, detail: error instanceof Error ? error.name : 'error' }
  }
}

/** Everything but process wiring, so tests call it with fake io. Returns the exit code. */
export async function run(argv: readonly string[], io: Io): Promise<number> {
  let parsed: ReturnType<typeof parse>
  try {
    parsed = parse(argv)
  } catch (error) {
    io.stderr(`linkcheck: ${error instanceof Error ? error.message : String(error)}\n${USAGE}`)
    return 2
  }
  if (parsed.values.help) {
    io.stdout(USAGE)
    return 0
  }
  const [file] = parsed.positionals
  const concurrency = Number(parsed.values.concurrency)
  const timeout = Number(parsed.values.timeout)
  if (
    !file ||
    !Number.isInteger(concurrency) ||
    concurrency < 1 ||
    !Number.isInteger(timeout) ||
    timeout < 1
  ) {
    io.stderr(USAGE)
    return 2
  }

  let text: string
  try {
    text = await readFile(file, 'utf8')
  } catch (error) {
    io.stderr(`linkcheck: cannot read ${file}`)
    io.stderr(String(error instanceof Error ? error.message : error))
    return 2
  }
  const urls = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '' && !line.startsWith('#'))
  if (!urls.every((u) => URL.canParse(u))) {
    io.stderr('linkcheck: FILE contains a line that is not a URL')
    return 2
  }

  const checks = await mapLimit(urls, concurrency, (url, signal) => check(url, timeout, signal, io))
  for (const c of checks) io.stdout(`${c.ok ? 'ok  ' : 'FAIL'} ${c.detail.padEnd(12)} ${c.url}`)
  return checks.every((c) => c.ok) ? 0 : 1
}

function parse(argv: readonly string[]) {
  return parseArgs({
    args: [...argv],
    allowPositionals: true,
    options: {
      concurrency: { type: 'string', short: 'c', default: '8' },
      timeout: { type: 'string', short: 't', default: '5000' },
      help: { type: 'boolean', short: 'h', default: false },
    },
  })
}

if (import.meta.main) {
  process.exitCode = await run(process.argv.slice(2), {
    stdout: (line) => process.stdout.write(`${line}\n`),
    stderr: (line) => process.stderr.write(`${line}\n`),
    fetch,
  })
}
