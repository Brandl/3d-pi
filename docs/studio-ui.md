# Using the alpha studio

The authenticated studio keeps conversation, model and history together. Desktop
has persistent chat beside the model; mobile switches between Model, Parts and
Chat without discarding the composer. The viewer uses locally served fonts/assets.

## Model and parts

Orbit, pan, zoom and Fit inspect the viewed revision. Fitted views reframe on
resize; deliberate camera manipulation is preserved. Grid/axes are optional.
Parts exposes the revision-bound tree and contextual measurements. Selection and
visual clipping are passed to the agent as context, not authorization to restore
or change geometry. Clipping is not an exact solid section.

History thumbnails are rendered from each revision's actual immutable mesh on
white, not repurposed screenshots. Loading is lazy and bounded; a software
projection supports clients without WebGL. An unavailable thumbnail is shown as
unavailable, never replaced by another revision's image.

## Live, intermediary and saved states

**Live** follows successful CAD builds before they are saved. Eligible builds must
be ready, pass declared geometry checks, differ from the saved document, have
been created after the saved head, and not be registered outputs. The newest 32
eligible builds appear as dashed **Intermediary** timeline entries. Raw source
edits and unfinished/failed builds do not stream. Failures leave the last good
preview visible.

Intermediary means **not committed**. It is not approval, a manufacturing package
or proof of physical fit. Chat context distinguishes this preview from the saved
working head. Project WebSocket updates normally arrive within about two seconds;
polling recovers missed updates. A persisted event sequence rejects stale snapshots.

**Working design** follows saved commits only. Clicking its current thumbnail
also follows saved commits rather than pinning that particular revision. Older
history and explicitly selected intermediaries stay pinned; **Live** resumes
previews. A new saved head during historical browsing offers **New working design**
instead of switching the view underneath you.

A new commit replaces the current intermediary group, without deleting underlying
builds. A preview already on screen gets its saved name/status without reloading
geometry. A late-finishing build started before the commit cannot replace it.
Named print/test/inspection outputs leave the intermediary feed when attached.
None of these view updates commits, restores, attaches or publishes anything.

## Make and Files

Make shows named print/test sets and their instructions beside the conversation.
During an uncommitted preview, those sets still belong to the saved design and
need not match the viewed geometry. Other builds contains raw viewed-revision
exports, not automatically approved print sets. Check part identity, units,
orientation, instructions and relevant physical tests before manufacturing.

Files also contains reference uploads/notes, transcript access and the
[component reference library](component-library.md). Views and downloads remain
project-scoped and authenticated. Historical downloads retain their original
bytes. A restore action prepares an agent request; browsing alone never restores.

## Conversation and interruptions

- Enter sends; Shift+Enter adds a newline; IME composition does not submit.
- Earlier exchanges collapse visually; this does not delete messages or compact
  the agent's context. Full transcript access remains separate.
- Progress is quiet and inline. Each raw tool result/error can expand independently.
  A final response or passed geometry check is not a manufacturing certificate.
- Drafts and unconfirmed outgoing payloads are retained per project and browser
  tab in session storage. Storage failure prevents sending. Explicit logout clears
  these records; use a trusted device.
- **Check / retry** reuses the original payload, context and key. A matching
  polled job receipt can acknowledge lost delivery without resubmission. There
  is no automatic replay, and newer typing survives an older acknowledgement.
- Very old uncertain requests require manual history inspection because server
  deduplication retention is bounded. Discarding a receipt does not cancel work
  that the server already accepted.
- Stop, timeout and provider interruption do not roll back changes. Inspect source,
  CAD history and attachments before asking the agent to continue.

The agent has a 15-minute no-progress timeout and a one-hour turn bound. Connection
loss is reported as reconnecting, not invented evidence that the agent stopped.
“View model” and “Open files” response actions navigate the workspace; they do not
prove a response has a revision-bound manufacturing attachment.

## Implementation and testing

Core UI files are under `web/src/`. Browser tests cover live commits/intermediaries,
stale events, failed previews, draft recovery, thumbnails, mobile controls and
historical browsing. See [isolated test instructions](../CONTRIBUTING.md).
