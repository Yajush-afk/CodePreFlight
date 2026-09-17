# Use versioned NDJSON for the local process seam

The TypeScript interface and Python engine exchange one versioned JSON object per line over standard input and output. NDJSON supports correlated progress events without a local server or open port, remains inspectable during failures, and lets either implementation evolve independently as long as generated protocol types and compatibility checks remain current.
