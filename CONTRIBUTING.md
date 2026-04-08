# Contributing

Thanks for contributing to `distributed-rate-limiter`.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
docker compose up -d postgres redis
alembic upgrade head
pytest -q
```

## Branching

Use short, descriptive branch names:

- `feature/token-bucket-metrics`
- `fix/policy-cache-invalidation`
- `docs/readme-improvements`

## Pull request expectations

Every PR should:

- explain the user-facing or operational impact
- include tests for new logic or regressions
- document schema, config, or migration changes
- describe failure-mode implications if Redis or Postgres behavior changes
- mention observability changes when metrics or logs are affected

## Backend quality bar

Changes to the rate limiter should preserve:

- atomic Redis coordination
- deterministic rate-limit key generation
- predictable `429` responses and headers
- route fallback and selector precedence behavior
- clear fail-open or fail-closed behavior under dependency outages

## Before opening a PR

Run:

```bash
ruff check .
pytest -q
```

If you touch Docker, migrations, or request flows, also run:

```bash
docker compose up --build
```

## Commit style

Keep commits focused and readable. A good pattern is:

- `Add token bucket retry-after coverage`
- `Fix Redis pubsub shutdown race`
- `Document scaling and fallback behavior`

