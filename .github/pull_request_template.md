## Summary

- What changed?
- Why did it change?

## Testing

- [ ] `pytest -q`
- [ ] `docker compose up --build`
- [ ] Manual API verification

## Checklist

- [ ] I updated documentation when behavior changed.
- [ ] I added or updated tests for the change.
- [ ] I considered rate-limit correctness under concurrency.
- [ ] I considered failure behavior when Redis or PostgreSQL is degraded.
- [ ] I checked metrics, logs, and headers for any affected endpoints.

## Operational Notes

- Policy or schema changes:
- Rollout or migration concerns:
- Follow-up work:

