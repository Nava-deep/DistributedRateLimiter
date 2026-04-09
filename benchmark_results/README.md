# Benchmark Results

This directory is the output target for generated synthetic benchmark runs.

When `scripts/run_benchmark.py` is executed, it creates timestamped subfolders here and writes:

- `summary.json`
- `summary.md`
- `metadata.json`
- Locust CSV and HTML artifacts
- raw Locust logs

Generated benchmark run folders are intentionally gitignored. The directory itself is kept in the repository so the output location is visible.
