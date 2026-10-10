# Experimental alpha: source-release policy

The release scope is **original source, lockfiles and local build instructions**
under Apache-2.0, with third-party notices retained. Users install dependencies or
build images themselves. Do not distribute prebuilt runtimes, executables,
node_modules, virtualenvs, dependency archives or private runtime data.

This does not relicense dependencies. Redistributing a combined runtime needs a
separate GPL/LGPL/native-library compliance review; see
[third-party notices](../THIRD_PARTY_NOTICES.md).

## Contents and history

Personal `examples/`, historical UI prototypes in `design/`, obsolete milestone/
workspace plans and installation-specific audit inventories are intentionally
untracked/ignored. Local copies and private backups are retained. Do not recreate
excluded personal models under a fixtures directory merely to satisfy tests.
The built-in API demo is a separate generic teaching model.

`.gitattributes` additionally excludes archived design data and the legacy
migration utility from source archives. **Ignore rules and archive exclusions do
not sanitize a Git clone, push or older commit.** The private original repository retains historical designs and records. The
public-source copy removes the approved personal design, prototype, planning/audit
and installation-specific migration paths from its Git history. This path-based
cleanup is not a guarantee that all private content has been removed; inspect the
actual tree and history rather than assuming they are public-safe.

Before publication, choose either explicitly reviewed existing history or an
approved clean initial source snapshot. Preserve the private repository and live
project histories; do not rewrite them as a shortcut. Specialized generators,
reference-library snippets and tests still contain project-derived knowledge and
need intended-disclosure/rights confirmation.

## Release gates

1. Approve the project name, repository destination, source scope and public-history
   approach. Confirm rights to included material and retain required notices.
2. Enable private vulnerability reporting or provide a monitored contact in
   [SECURITY.md](../SECURITY.md). Do not invent an address or response SLA.
3. Review the exact proposed file list and diff. No runtime credentials, sessions,
   uploads, personal models or generated manufacturing artifacts may enter it.
4. Run lint, locked installs, backend/agent tests, viewer build and isolated
   integration/browser tests against that exact source tree. Report skips and
   optional private-fixture coverage honestly.
5. Run dependency audits and secret/privacy scans on the final tree and every
   historical object intended for publication. Scanners do not prove provenance
   or the absence of all personal information.
6. Test the documented authenticated installation on a second clean machine,
   including provider setup, a real modeling turn, saving, downloads and restart
   recovery. A same-host source snapshot is not an independent-machine test.
7. Review the README with a new user. If adding a demo, use real modeling/export
   evidence and disclose acceleration and separately recorded/edited portions.
8. Stage approved files explicitly and commit only with approval. Inspect an
   archive from that commit, scan its extracted contents and test the install.
9. Choose an experimental release tag, state support expectations, and obtain
   explicit approval to publish/push. Preparing docs is not publication approval.

For an approved commit, an archive can be created with:

```sh
git archive --format=tar.gz --output=/private/path/3d-pi-source.tar.gz <approved-commit>
```

Inspect its member list; do not substitute an archive of the whole working
folder or VM. Release checks and operational deployment records belong in private
maintainer records, not an evergreen public document claiming old results are
current. No public release or complete security/compliance clearance is implied
by this checklist.
