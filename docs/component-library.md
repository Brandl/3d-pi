# Component reference library

The alpha's Components panel is a **reference library**, not a component package
manager or parametric instancing system. Its bundled entries describe existing
slide-lock and captured-floor mechanisms, with instructions, draft parameters,
source snippets and validation notes.

Use an entry to prepare a chat draft. It does not insert geometry, create a CAD
revision or publish anything. The agent must inspect the target design, adapt
source explicitly, build a candidate and verify the result.

## Scope and limitations

- Entries are bundled application documentation, not persistent user-created
  component releases. There is no versioned release/instance resolver.
- Parameters may be shared across mating parts. A clip is not independent of its
  rails, host walls, clearance conventions or removal envelope.
- Reference dimensions and prior computational checks are not universal defaults
  or physical validation for a new design. Use fit coupons and appropriate tests.
- Source snippets are references to installed generators, not permission to
  execute arbitrary uploaded code or import untrusted modules.
- Library changes do not rewrite existing immutable design revisions.

Persistent releases, namespaced instances and explicit upgrades remain future
work, not alpha functionality. Existing generator source is still project-derived;
excluding personal example documents does not anonymize all application code.

Implementation: `web/src/library.ts`; source extraction is configured in
`web/vite.config.ts`. Part/feature inspection is described in
[CAD tools](agent-tools.md), separately from reusable-component support.
