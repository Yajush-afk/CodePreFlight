# Local commit graph

Wide terminals show a display-only graph to the right of the conversation. `B` is the
configured base lane and `C` is the current branch lane; colors supplement these labels,
not replace them. A base-branch session has one lane. Feature branches show both lanes
and their merge base, with recent commit subjects and a working-tree marker.

Below 100 columns, the graph becomes a one-line branch summary. `/graph` opens the
full-width graph view. The panel never receives keyboard focus; use `/commits`,
`/branches`, or `/files` for interactive navigation. Only local references are read.
Missing-base guidance does not trigger a fetch or guess a remote branch.
