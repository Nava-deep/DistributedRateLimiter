# Sample Multi-Instance Benchmark

This sample report shows the benchmark output format for a synthetic load run against two API instances sharing one Redis backend.

## Configuration

- API instances: `2`
- Concurrent virtual users: `6`
- Spawn rate: `3.0` users/s
- Run time: `3s`
- Target hosts: `http://localhost:8001`, `http://localhost:8002`
- Correctness tests available: `48`

## Results

- Total requests: `86`
- Allowed requests: `86`
- Blocked requests: `0`
- Error requests: `0`
- Throughput: `31.24 requests/s`
- Average latency: `7.0 ms`
- P95 latency: `12.0 ms`

## Notes

- This is a synthetic benchmark, not production traffic.
- The purpose of this sample is to show the benchmark result format in a clean and readable way.
