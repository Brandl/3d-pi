# Automatic visual checkpoints

The model receives actual image content blocks, not merely file paths or a claim that rendering passed.

## Checkpoints

- First ready-design `cad_inspect` summary in the current agent extension instance.
- Each newly ready candidate returned by `cad_build` or `cad_parameters`.
- A ready candidate first encountered by summary polling after `wait=false`.
- Before `cad_publish` or `cad_restore` when its checkpoint has not been delivered in this extension instance: the tool returns images and `visual_review_required`, **without performing the mutation**. The agent must inspect them and explicitly call the operation again, with the original generation. Stale-generation checks still apply.

The bounded cache remembers the last 32 revision IDs with complete mandatory image sets. Routine polling does not resend their images. The cache clears after session compaction, so the next inspection or publication attempt gets a fresh checkpoint. This records image delivery, not model approval or proof of perception. For uncertainty or further inspection needs, call `cad_render` again. No visual result automatically publishes anything, and tool-level checkpoints are not a security boundary around the private API.

## Views and colours

Default review: isometric, top, front, plus exploded when generated. Each image is captioned with its exact revision, view and units. New builds create `review-*.png` alongside the original `render-*.png`: separate categorical colours and a named-part legend are used for inspection, consistently across views of the same part set. User-specified source colours and preview geometry are not modified. Transparent parts retain their opacity; this is explicitly labelled.

Old revisions are not regenerated or modified. Where their review images do not exist, the tools fall back to their original renders and identify that fallback. Those legacy images may not have a colour legend.

`cad_render` defaults to `view=review`, or accepts one of `iso/top/front/exploded`. `style=inspection` prefers review images; `style=standard` uses original renders. Each image is limited to 4 MiB and 4096×4096 pixels, with fetch timeouts and PNG checks. Missing required views are reported as incomplete and are not cached as a checkpoint; exploded is optional. A successful CAD build stays successful if images cannot be retrieved—inspect/retry its existing revision rather than rebuilding blindly.

## What the model should inspect

Compare the requested change against silhouettes, proportions, part identity, mating alignment, engagement/removal direction, obvious intersections and unexpected missing geometry. Cross-check dimensions and clearances with `cad_measure` and `cad_validate`; a 0.15 mm fit cannot reliably be judged from pixels at assembly scale. Preview triangles and painter-style rendering are not exact B-rep measurements or proof of manufacturability, strength or leak-tightness.

## Hidden lines: planned, not implemented

The current shaded/edge views are **not hidden-line drawings**. Transparency is not hidden-line removal, and drawing every edge dashed would be misleading.

A future hidden-line mode needs visible/occluded segment classification, solid visible edges and dashed occluded segments, tested against known occluders in each camera. B-rep parts could use OCCT hidden-line algorithms; analytic mesh-only masters need a separate depth/visibility implementation with explicit approximation tolerances. It must work for mixed assemblies and split edges at occlusion transitions. Do not add a “hidden lines” switch until those checks exist.
