# CodePreFlight

CodePreFlight is a terminal-based Git workflow and AI code review tool. It helps developers inspect repository changes, understand Git state, review code before it is committed or merged, and move changes through Git with greater confidence.

CodePreFlight sits around the coding process rather than replacing it. A developer or coding agent writes the code; CodePreFlight examines the resulting changes. Reviews combine repository context, deterministic engineering checks, repository-specific rules, and an AI provider selected by the developer.

The tool is local-first, provider-agnostic, and explicit about when repository content is sent to an external provider. It supports local models, compatible AI command-line tools that use an existing subscription, and user-supplied API credentials. CodePreFlight does not operate its own inference service.

Its core responsibilities are:

- presenting repository and branch state clearly;
- reviewing staged, branch, and pull-request changes;
- identifying correctness, security, compatibility, and testing concerns;
- validating AI findings against repository evidence;
- explaining diffs, affected areas, and relevant Git history;
- assisting with safe commit and pull-request workflows;
- keeping every repository mutation under explicit developer control.

CodePreFlight is not a coding agent, code editor, IDE, or autonomous software engineer. It is the quality-control layer between code generation and the Git workflow.
