# Interactive command guidance

Type `/` to open suggestions above the composer. Type part of a command to filter it.
Use Up/Down to choose, Tab to complete without running, Enter to select, and Escape to
dismiss. Commands with arguments offer reachable commits, installed providers, local
branches, or repository paths. File suggestions prioritize changed paths.

Start with `/provider`, `/model`, `/variant`, and `/review`: these open guided pickers.
Picker choices invoke typed actions rather than hidden commands. `/reviewstaged`,
`/reviewworking`,
`/reviewbranch`, `/reviewcommit <revision>`, `/reviewpr`,
`/reviewmergedpr <number-or-url>`, and `/scanfull` are direct actions. Merged-PR review
uses authenticated, read-only GitHub CLI data and does not switch or fetch branches.
Use `/files`, `/file <path>`, `/branches`, `/switchbranch <branch>`, and `/commits` to navigate.
`/providerlogin <provider>`, `/providertest <provider>`, and `/providerswitch <provider>`
are the provider shortcuts. `/mode`, `/jobs`, `/automationgrant`, `/automationrevoke`,
and `/activity` expose automation and operation details.

After any review, `/findings` opens the scrollable findings explorer. Select one to read its
details and ask follow-up questions, including multiple finding numbers. With an empty composer,
Up/Down scroll the transcript; Ctrl+P/Ctrl+N recall prior commands.

Arguments remain separate values; only command names are single tokens. Old spaced
commands offer a correction for one compatibility release. Shell CLI syntax is unchanged.
Use `/help` for the complete command list and `/quit` to leave the ephemeral session.
