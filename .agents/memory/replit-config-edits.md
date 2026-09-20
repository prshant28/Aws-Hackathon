---
name: Validated Replit config edits
description: The workspace-specific procedure for safely changing the .replit configuration file.
---

Direct edits to `.replit` are rejected by the workspace guard.

**Why:** Replit validates the TOML schema and protects workflow, port, package, and deployment settings from malformed edits.

**How to apply:** Read the current file, write the complete proposed TOML to a temporary workspace file, then call `verifyAndReplaceDotReplit` with its absolute path. Use the dedicated workflow/package tools for changes that affect those sections.