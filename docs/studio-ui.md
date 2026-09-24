# Conversation-first studio UI

Visual reference: `better-tool` upload `caduiux.PNG`, note “Inspi”.

## Layout

- Desktop: persistent left-hand conversation and anchored composer; model canvas on the right; visual history below the canvas.
- Neutral light surfaces, soft borders, compact controls and a restrained orange accent. CAD part colours remain unchanged.
- Model/Parts controls keep the viewport mounted. Parts opens a contextual right-hand inspector rather than permanently taking canvas space.
- Make opens the existing files/manufacturing drawer, not a pretend new manual generator. Reference uploads, instructions, exports and component library remain available.
- Header badges describe the **viewed** revision, not necessarily the working design.
- Mobile retains Model/Parts/Chat panes and existing keyboard-height handling; unsent drafts stay in the mounted composer.

## Visual history

Each history entry uses its own immutable `review-iso.png`, falling back to `render-iso.png`, then an explicit unavailable placeholder. Images are lazy-loaded, authenticated same-origin resources. Icons and names remain. Selecting a thumbnail only browses; restoration still requires the separate explicit agent draft/action, with provenance and concurrency safeguards unchanged.

## Chat cards

Earlier user exchanges are grouped into expandable cards showing the request and a short excerpt of the last assistant answer. The newest exchange remains expanded. Nested tool activity stays available; tool errors open their group by default. Expansion choices survive ordinary polling updates.

This is **visual grouping only**: no messages are deleted, no agent-context compaction is requested, and no server history is rewritten. The server's existing bounded message window still applies; full transcript access remains in Files. Cards say “Earlier request”, not “validated” or “completed”, because a message boundary does not prove successful execution or manufacturing readiness. Previews use textContent and full messages retain the safe formatter.

## Verification

`web/tests/studio.spec.ts`: left-hand placement at1024/1440px, compact cards and retained expansion, real thumbnails, draft preservation, Parts/Make controls, and non-mutating history browsing. Existing mobile tests cover320–844px and desktop transition; cowork tests cover WebGL and image fallback. Legacy-publication viewer tests now use their own fresh project so an existing working head cannot invalidate the fixture assumptions.
