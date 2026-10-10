# Licensing and third-party components

Original 3d-pi source, documentation and checked-in examples are licensed under
[Apache License 2.0](LICENSE), except where a file supplies another licence.
This does not relicense dependencies, fonts, user uploads, private project data,
or designs created with the application. No rights to third-party trademarks
or designs are implied. Review example/design provenance before publication.

## Pi compatibility

The pinned `@earendil-works/pi-coding-agent` and `@earendil-works/pi-ai` **1.1.0**
packages declare MIT. The upstream licence at
<https://github.com/earendil-works/pi/blob/v1.1.0/LICENSE> is MIT, copyright
2025 Mario Zechner. Its full text is retained in [LICENSES/pi-MIT.txt](LICENSES/pi-MIT.txt).
MIT permits use with Apache-2.0 project code; preserve the upstream copyright
and permission notices when redistributing Pi. This finding is version-specific.
Pi's transitive dependencies retain their individual licences.

## Important: GPL and LGPL runtime components

**The complete runtime must not be represented as Apache-only.**

- **PyMeshLab 2025.7.post1 declares GPLv3** and is imported directly by
  `cad/gentle_twist.py` for mesh verification. Apache-2.0 source can be included
  in a GPLv3 combination, but Apache-2.0 does not replace GPL obligations.
  Treat distribution of the combined runtime/container as requiring GPLv3
  compliance, including applicable Corresponding Source and licence notices.
  A link to an upstream repository alone is not a complete compliance plan.
  Making the import optional would not, by itself, resolve distribution terms.
- **Open CASCADE (OCCT)**, reached through `cadquery-ocp-novtk`, uses
  LGPL-2.1 with the OCCT exception. The binding's Apache metadata is not the
  licence of the native kernel. Preserve the applicable licences and satisfy
  source/modification/relinking requirements for the actual binaries shipped.
  See <https://dev.opencascade.org/resources/licensing>.
- Native wheels and container base images bundle further libraries. Audit the
  actual platform-specific release image, not only Python/npm metadata.

The repository's original source can be released under Apache-2.0. **Binary and
container redistribution is not cleared by this notice.** Before such a release,
prepare a complete component inventory, required notices and a compliant source
availability mechanism. Alternatively, replacing PyMeshLab with a permissively
licensed implementation is separate engineering work requiring equivalent tests.

## Selected dependency inventory

This is a review guide, not an exhaustive SBOM or complete binary notice bundle.
Versions are fixed by `uv.lock` and the two npm lockfiles.

| Component | Reviewed licence / action |
| --- | --- |
| build123d 0.11.1 | Apache-2.0; retain its LICENSE and NOTICE when redistributed |
| cadquery-ocp-novtk 7.9.3.1.1 | Apache-2.0 binding; OCCT native terms above also apply |
| ocp-gordon 0.2.2, ocpsvg 0.6.0 | Apache-2.0 (ocpsvg verified from installed LICENSE) |
| lib3mf 2.5.0 | BSD; preserve upstream notices |
| trimesh 4.6.8 | MIT |
| NetworkX 3.4.2 (mesh-section contour assembly) | BSD-3-Clause |
| FastAPI, Starlette, Uvicorn | BSD/MIT permissive licences; retain package notices |
| Matplotlib | Matplotlib/PSF-style terms plus bundled component/font licences |
| Three.js 0.176.0 | MIT; full notice in `web/public/THREE-LICENSE.txt`, copied into viewer builds |
| Inter Variable | SIL OFL 1.1, unmodified; `web/public/fonts/Inter-OFL.txt` |
| Noto Emoji | SIL OFL 1.1, format-converted; `web/public/fonts/NotoEmoji-OFL.txt` |

Font sources and hashes are in `web/public/fonts/README.txt`. The fonts remain
OFL-licensed, not Apache-licensed. Keep these notices alongside distributed fonts.

The reviewed npm locks contain MIT, Apache-2.0, BSD-3-Clause, ISC, Unlicense,
BlueOak-1.0.0 and 0BSD declarations. Metadata alone does not establish provenance
or account for every bundled native asset. Provider API terms, account access
and model availability are separate from this software licence.
