# Review evaluation corpus

`cases.json` records the initial positive, verification, privacy, and negative-control
scenarios for repeatable provider evaluation. It intentionally contains no performance
claims. A provider run should record its CodePreFlight revision, provider and model version,
case revision, verified detections, rejected findings, false positives, context size,
latency, and failure state. Results are comparable only when all of those inputs are fixed.

Normal tests use deterministic fake providers and do not spend tokens. Live adapter tests
run only when explicitly enabled. Published measurements must include raw structured results
and enough environment metadata to reproduce them.
