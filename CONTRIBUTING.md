# Contributing to the alpha

3d-pi is experimental, single-owner software. Discuss substantial architecture or
dependency changes first. Keep changes focused, add regression tests and update
current documentation rather than historical project logs.

Contributions intentionally submitted for inclusion are under Apache-2.0 unless
explicitly stated otherwise. Submit only material you have rights to license;
identify copied material and retain [third-party notices](THIRD_PARTY_NOTICES.md).

## Local checks

Use the [README](README.md) prerequisites. From the repository root:

```sh
uv sync --locked
uv run ruff check cad tests
uv run ruff format --check cad tests
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run pytest -q -rs
node --test scripts/cad-presentation.test.mjs
(cd agent && npm ci --ignore-scripts && npm test)
(cd web && npm ci && npm run build)
```

The built-in demo and general service/kernel tests do not require personal example
files. Some specialized historical regressions use optional local `examples/`
fixtures through `tests/local_examples.py`. They explicitly skip when the files
are absent; report these skips, not a claim of full historical-design coverage.
Do not copy excluded models into a public fixtures directory to suppress skips.
Maintainers retaining the original private inputs can run those regressions locally.
The installation-specific migration test also skips when its utility is omitted
from a source archive; normal project isolation tests remain part of the public suite.

## Isolated tool and browser tests

These tests intentionally build, publish, restore and create projects. **Never run
them against production.** Choose a free loopback port and a new disposable data
root. In one terminal:

```sh
TEST_DATA=$(mktemp -d)
CAD_DATA_DIR="$TEST_DATA" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  uv run python -m cad.cli serve --port 8799
```

In another terminal at the repository root, after the npm installs above:

```sh
CAD_URL=http://127.0.0.1:8799 \
  PI_PACKAGE_DIR="$PWD/agent/node_modules/@earendil-works/pi-coding-agent" \
  node scripts/test-pi.mjs
(cd web && npx playwright install chromium)
(cd web && CAD_URL=http://127.0.0.1:8799 npm test)
```

Stop the isolated service afterward. On a fresh Linux machine Playwright may also
need system browser dependencies (`npx playwright install --with-deps chromium`).
The tool smoke test uses the real extension loader without a paid model call and
seeds a small workspace. Authentication, provider and specialized-data browser
scenarios have additional environment requirements and may skip. Read the test
output; these commands do not replace an authenticated end-to-end install check.
CI similarly uses isolated data, never an operator workspace.

## Preservation and security

- Keep immutable revisions, original source provenance, scoped URLs and optimistic
  generation checks. Viewing or streaming an intermediary must not commit/publish.
- Do not store credentials, provider sessions, transcripts, uploads, runtime data,
  personal designs, build outputs or dependency directories in source Git.
- Keep private CAD/agent APIs private and preserve gateway authentication, origin
  and CSRF checks. Treat uploaded reference material as untrusted.
- Back up before runtime changes and never interrupt an active agent/build to
  deploy unrelated work. Code changes are not automatic deployment permission.
- Test archive/checkout contents without ignored local files before proposing a
  release. Review the exact tree and any history intended for publication.

Report evidence honestly. Numerical assertions, valid solids and screenshots do
not certify printability, physical fit, strength or safe mechanical use. Release
approval and publication follow the separate [source-release checklist](docs/source-release.md).
