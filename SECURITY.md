# Security

## API keys and local data

PublicMind is designed as a local, single-user application. Never commit or
share real Brave Search or DeepSeek API keys.

Local credentials, databases, fetched documents and exports live under
`data/` and are excluded from Git. Each user should configure their own API
keys through the local settings dialog or environment variables.

Before publishing a fork, verify that these files remain untracked:

```bash
git check-ignore data/settings.json data/publicmind.db data/exports/
git ls-files data/
```

The second command should not list credentials, databases or exported
dossiers. If a secret was ever committed, deleting the working-tree file is
not enough: revoke the key immediately and remove it from Git history before
publishing.

## Deployment boundary

The default server binds to `127.0.0.1` and has no multi-user authentication.
Do not expose it directly to the public internet. A public deployment needs
authentication, per-user data isolation, rate limits, server-side secret
management and outbound-request protections.

## Reporting a vulnerability

Please open a GitHub issue without including API keys, private documents,
personal data or other secrets. For a sensitive report, contact the repository
owner privately through their GitHub profile.
