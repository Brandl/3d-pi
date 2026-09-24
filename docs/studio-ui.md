# Conversation-first studio UI

Visual reference: `better-tool` upload `caduiux.PNG`, note “Inspi”.

## Layout

- Desktop: persistent left-hand conversation and anchored composer; model canvas on the right; visual history below the canvas.
- Self-hosted Inter Variable typography, a consistent spacing/type scale, neutral surfaces and a restrained orange accent. Part colours come from the revision's geometry data.
- Separate navigation and camera-control rows, a white model stage with a clear title, and optional grid/axes (off initially). Fit uses projected bounds rather than an oversized bounding sphere.
- Model/Parts controls keep the viewport mounted. Parts opens a contextual right-hand inspector rather than permanently taking canvas space.
- Make is a central manufacturing sheet beside the conversation, with real output previews, print/test files and instructions. It does not block the chat with a modal. Files remains a separate drawer for reference uploads, exports and component library. No fake manual or certification is generated.
- Header badges describe the **viewed** revision, not necessarily the working design.
- Mobile retains Model/Parts/Chat panes and existing keyboard-height handling; unsent drafts stay in the mounted composer.

## Visual history

`web/src/revision-thumbnails.ts` renders each revision's actual immutable preview mesh into a dedicated320×200 orthographic PNG, on opaque white. It fits and centres the **projected vertices**, not the image canvas of a labelled review screenshot. No grids, legends, axes, emoji overlays, screenshot crops or background replacement. A single shared WebGL renderer is reused and geometries/materials are disposed after each render. A depth-sorted software projection supports non-WebGL clients (approximate occlusion, not exact hidden-line analysis).

Requests are visibility-driven and serialized, with a48-bitmap cache and explicit geometry/download budgets (64MiB input,1M triangles with WebGL,100K for software). Failures show an unavailable placeholder, never an unrelated or dark screenshot. Geometry data remains project-scoped/authenticated; no CAD rebuilds, new revisions or artifact rewrites. Selecting a thumbnail only browses; restoration retains the separate explicit agent action and provenance/concurrency safeguards.

## Chat cards

Earlier user exchanges are grouped into expandable cards showing the request and a short excerpt of the last assistant answer. The newest exchange remains expanded. Tool-calling progress notes join the expandable activity group instead of looking like separate final answers. Nested tool activity stays available; tool errors open their group by default. Expansion choices survive ordinary polling updates.

This is **visual grouping only**: no messages are deleted, no agent-context compaction is requested, and no server history is rewritten. The server's existing bounded message window still applies; full transcript access remains in Files. Cards say “Earlier request”, not “validated” or “completed”, because a message boundary does not prove successful execution or manufacturing readiness. Previews use textContent and full messages retain the safe formatter.

## Verification

`web/tests/thumbnails.spec.ts` checks opaque-white corners, visible mesh content, equal opposing margins and safe padding with both WebGL and software rendering. `web/tests/studio.spec.ts`: left-hand placement at1024/1440px, compact cards and retained expansion, real thumbnails, draft preservation, Parts/Make controls, and non-mutating history browsing. Existing mobile tests cover320–844px and desktop transition; cowork tests cover WebGL and image fallback. Legacy-publication viewer tests now use their own fresh project so an existing working head cannot invalidate the fixture assumptions.
