# Benchmark Results

This directory is the output target for generated synthetic benchmark runs.

When `scripts/run_benchmark.py` is executed, it creates timestamped subfolders here and writes:

- `summary.json`
- `summary.md`
- `metadata.json`
- Locust CSV and HTML artifacts
- raw Locust logs

Most generated benchmark run folders remain gitignored to avoid committing every local run.
The repository includes a committed sample benchmark run in `20260409T100908Z_shared-protected` so the output format is visible on GitHub.
