# Packaging, releases, deploy, and interop

Sources: uv packaging and Docker guides
(https://docs.astral.sh/uv/guides/package/,
https://docs.astral.sh/uv/guides/integration/docker/), the uv build backend
(https://docs.astral.sh/uv/concepts/build-backend/), PyPI trusted publishing
(https://docs.pypi.org/trusted-publishers/), pypa/gh-action-pypi-publish
(https://github.com/pypa/gh-action-pypi-publish), Kamal 2
(https://kamal-deploy.org/docs/configuration/), and Cloudflare SSL modes
(https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/).

## Contents
- Building wheels
- Versioning
- Publishing to PyPI (trusted publishing)
- Distributing CLIs
- The Docker image
- Kamal 2
- Cloudflare in front
- Interop: C, Rust, and WASM

## Building wheels

- `uv build` writes an sdist and a wheel to `dist/`; `uv build --package
  acme-core` builds one workspace member, `--all-packages` builds all of them.
- **Always build with `--no-sources` in CI.** It ignores `[tool.uv.sources]`
  (workspace paths), so it proves the published metadata resolves on its own,
  like `pip install` will.
- Backend: `uv_build` (default for `uv init`, pure Python, fast, src layout
  by convention) with a bounded requirement: `requires = ["uv_build>=0.12.18,<0.13"]`.
  Use `hatchling` when you need build hooks or non-Python files outside the
  package; use `maturin` for Rust extensions.
- Check the wheel: `python -m zipfile -l dist/*.whl` should show `py.typed`,
  package data (migrations, templates), and no tests. The template's wheel
  includes `migrations/env.py`, `script.py.mako`, and `versions/`
  (verified), because they live inside the package.
- Pure-Python wheels are `py3-none-any`. Only extension modules need a
  platform matrix (`cibuildwheel`).

## Versioning

- SemVer for libraries; bump with `uv version --bump patch|minor|major`
  (or `--bump minor --bump beta` for pre-releases). Tag `acme-core-v1.2.0` per
  package in a workspace.
- Deprecate before removing: `warnings.deprecated` (PEP 702, 3.13+) on the old
  API for at least one minor release.
- Applications don't need a published version; the image tag (git SHA) is
  the version.

## Publishing to PyPI (trusted publishing)

No API tokens. On pypi.org, add a trusted publisher (the GitHub repo,
workflow `release.yml`, environment `pypi`), then:

```yaml
jobs:
  build:     # no special permissions
    steps: [checkout, setup-uv, "uv build --package acme-core --no-sources", upload-artifact dist/]
  publish:
    needs: build
    environment: pypi
    permissions:
      id-token: write              # only this job gets the OIDC token
    steps: [download-artifact dist/, pypa/gh-action-pypi-publish@release/v1]
```

- Separate build and publish jobs, so build steps (and their dependencies)
  never hold the publish credential.
- `pypa/gh-action-pypi-publish` generates **PEP 740 attestations** by
  default with trusted publishing. `uv publish` supports trusted publishing too,
  and uploads attestation files it finds, but it doesn't *generate* them yet;
  hence the action is the default.
- Test the pipeline against TestPyPI first (`repository-url:
  https://test.pypi.org/legacy/`).

## Distributing CLIs

- Python users: `uv tool install acme-cli` (or `uvx acme-cli`), or pipx.
  Publish the CLI as its own package with `[project.scripts]`.
- Internal scripts: a single file with PEP 723 inline metadata, run with
  `uv run script.py`; uv creates the environment on the fly.
- Non-Python users: a container image, or a standalone bundle (PyInstaller)
  when you must ship one binary. Python can't produce a truly static binary;
  if that's a hard requirement, the CLI may belong in Go or Rust.

## The Docker image

`assets/Dockerfile` (not built during verification; no Docker was available,
but its two `uv sync` steps were run locally in an empty directory to confirm
the layering works):

1. **Build stage** `python:3.14.7-slim-trixie` + `COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv`.
   Env: `UV_COMPILE_BYTECODE=1` (faster cold start), `UV_LINK_MODE=copy`
   (cache mounts are another filesystem), `UV_NO_DEV=1`,
   `UV_PYTHON_DOWNLOADS=0` (use the image's Python), and
   `UV_PROJECT_ENVIRONMENT=/app/.venv`.
2. **Dependencies layer:** bind-mount only `pyproject.toml` + `uv.lock`, then
   `uv sync --frozen --no-install-workspace --package acme-api`. `--frozen`
   because the member manifests aren't there yet; this layer rebuilds only when
   the lock changes.
3. **Project layer:** `COPY . .` then `uv sync --locked --no-editable
   --package acme-api`. `--locked` fails the build on a stale lock;
   `--no-editable` installs real packages so the venv works without the source.
   Only the service's members and their dependencies are installed (the CLI and
   the dev tools aren't).
4. **Runtime stage:** the **same** base image (the venv's `python` is a symlink
   to `/usr/local/bin/python3.14`), a system user, `COPY --chown` of
   `/app/.venv`, `PATH=/app/.venv/bin:$PATH`, `USER app`, exec-form
   `CMD ["acme-api", "serve"]`. No uv, pip, or compilers at runtime.

Why not distroless: `gcr.io/distroless/python3-debian13` ships Debian's Python
3.13 (checked 2026-09), so a 3.14 venv can't run on it, and its Python is
tied to Debian's release cycle. Alpine uses musl, so many wheels must build
from source and some run slower. Use slim.

`.dockerignore` excludes `.venv`, caches, `.git`, `.env*`, and Kamal secrets:
a copied local `.venv` would shadow the built one, and secrets must never enter
a layer.

## Kamal 2

`assets/deploy.yml` + `assets/kamal-pre-deploy`:
- `web` role behind kamal-proxy: `proxy.app_port: 8000` (kamal-proxy defaults
  to 80), `healthcheck.path: /up`.
- `worker` role: `cmd: acme-api worker --concurrency 4`, `proxy: false`.
- Env: `DATABASE_URL` secret; `WEB_CONCURRENCY`, `LOG_LEVEL`, and
  `SHUTDOWN_GRACE_SECONDS=8` in the clear. Kamal stops containers with
  Docker's default 10 s timeout; kamal-proxy has already drained in-flight
  requests before SIGTERM arrives, and the app finishes within 8 s.
- Migrations: `.kamal/hooks/pre-deploy` runs `kamal app exec --primary
  --roles=web --version="$KAMAL_VERSION" "acme-api migrate"`, the new image
  migrating once before it boots. The old version is still serving, so
  migrations must be backward compatible (expand, then contract).
- Postgres as an accessory: `postgres:18` mounts
  `data:/var/lib/postgresql` (18 moved `PGDATA` under
  `/var/lib/postgresql/18/docker`; mounting the old `.../data` path loses data
  on container replacement). Use a managed Postgres when you can.
- `builder.arch: amd64` matching the servers; building wheels under QEMU is
  slow.

## Cloudflare in front

- Proxied DNS record → SSL mode **Full (strict)** with a Cloudflare **Origin
  CA** certificate on kamal-proxy (`ssl.certificate_pem` /
  `private_key_pem` secrets). Let's Encrypt HTTP challenges don't work behind
  the proxy.
- Real client IP: Cloudflare sends `CF-Connecting-IP`; kamal-proxy with
  `forward_headers: true` passes `X-Forwarded-For`; uvicorn's
  `proxy_headers=True` + `forwarded_allow_ips="*"` (safe because only
  kamal-proxy reaches the container) puts it in `request.client`.
- Cache public GETs at the edge; rate-limit and WAF there before writing app
  code for it.
- Firewall the origin to Cloudflare's IP ranges plus your SSH source.

## Interop: C, Rust, and WASM

- **Calling C:** `ctypes` (stdlib) for a few functions in an existing shared
  library; `cffi` for larger APIs. Release the GIL in the C code for long calls.
- **Writing extensions:** Rust + PyO3 + maturin is the default for new native
  code (memory safety, `abi3` wheels that work across Python versions). The
  free-threaded build needs extensions that declare support; the stable ABI for
  free-threaded builds (`abi3t`, PEP 803) arrives in 3.15.
- **Subprocess over FFI** when the other side is a CLI: `subprocess.run([...],
  check=True, timeout=...)` with JSON on stdout is simpler and safer than bindings.
- **WASM:** Pyodide runs CPython in the browser (Emscripten, which 3.14
  supports officially as a tier 3 platform, PEP 776). Most pure-Python
  wheels work; packages with C extensions need Pyodide builds. Don't pick
  Python for a WASM-first product.
