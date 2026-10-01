# Protocol v4 migration

Protocol v4 changes the finding severity contract to `critical`, `high`, `medium`, and `low` and
adds typed finding-lifecycle, Git-operation, conflict, and workspace-view contracts. The CLI and
engine must be upgraded together; a mixed v3/v4 process is rejected with restart guidance.

Existing version 1 repository configuration remains valid. Legacy `review.block_severities`
values are read with these mappings:

| Legacy value | v4 value |
| --- | --- |
| `critical` | `critical` |
| `warning` | `high` |
| `suggestion` | `medium` |
| `informational` | `low` |

The existing `review.policy = "warning"` setting remains a compatible non-blocking policy name.
Only `review.policy = "block"` enables blocking, with Critical as the default threshold. A
configured High threshold is also supported. Findings that are not locally verified do not block.

Review and full-scan cache fingerprints include new prompt versions. Cached v3 findings are not
silently relabeled; they are invalidated and receive v4 severity through a new review. Persistent
finding history records its original legacy label separately when imported by the finding ledger.
