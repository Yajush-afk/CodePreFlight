# Contributing

Install both workspaces with `make install`. Before opening a pull request, run:

```bash
make check
make test
npm run build
```

Keep repository inspection read-only and place every Git mutation behind explicit user
approval. Provider adapters must accept a curated prompt and schema without receiving
repository editing or shell permission. Add deterministic fake-provider coverage for normal
tests; live provider tests must remain opt-in so CI never requires credentials or spends
tokens.

Changes to the TypeScript-Python boundary must update `protocol/schema.json`, Python models,
TypeScript types, and process tests together. New Findings must remain evidence-grounded and
must not represent model agreement as proof.
