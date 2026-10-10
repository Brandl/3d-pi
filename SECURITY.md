# Security

## Supported scope

This is experimental software for one trusted operator, not a multi-tenant
service or a secure execution sandbox. There are no supported stable releases
or promised security-response timelines yet.

- Keep the unauthenticated CAD API bound to loopback/private container networking.
- Use the authenticated gateway with HTTPS for remote access.
- The agent can execute commands and edit its mounted workspace. Project
  separation is not isolation between mutually untrusted users.
- Treat uploaded files, model documents and native CAD parsers as attack surfaces.
- Keep provider credentials outside source, images and logs. Use least-privilege
  mounts, backups and resource limits. Long-lived login sessions require care
  on shared devices; log out to revoke a session.

## Reporting

Do not put credentials, private designs, session tokens or exploit details in a
public issue. Use the repository host's private vulnerability-reporting feature
**if enabled**, or an existing private channel to the maintainer. Do not assume
that a public issue is private.

**Before public launch, the maintainer must enable private vulnerability reports
or publish a monitored security contact here.** No reporting address has been
invented for this repository.

Provide affected versions, a minimal reproduction and the expected/observed
security boundary. Only test deployments and data you are authorized to test.
A clean dependency or secret scan is not a security certification.
