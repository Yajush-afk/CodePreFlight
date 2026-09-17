# Use TypeScript for the terminal interface and Python for the review engine

CodePreFlight uses TypeScript with Ink for terminal interaction and Python for repository analysis, provider orchestration, and evidence verification. This keeps the user interface in the Node terminal ecosystem while allowing the review engine to use the user's primary AI-engineering stack; replacing either side requires changing only the process seam rather than the other implementation.
