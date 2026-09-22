# Security policy

## Scope

Glitchslate is a local-first personal telemetry tool. It can handle Telegram messages, workout data, writing paths, social-feed URLs, and third-party API credentials. Treat the local SQLite database, `.env`, archive files, and generated logs as private data.

## Safe setup

- Copy `.env.example` to `.env`; never commit `.env` or database files.
- Keep `.env` private: `chmod 600 .env`.
- Leave integrations disabled until their credentials and destinations are configured in `config.yaml`.
- Review `config.yaml` for local paths and account identifiers before publishing screenshots or a fork.
- Use `--dry-run` or `--no-apply` when testing a new checkout.
- Rotate a credential immediately if it appears in Git history, an issue, a log, or a generated archive.

## Reporting a vulnerability

Please do not open a public issue containing credentials, private activity data, or an exploitable proof of concept. Use a private security report if the repository has that feature enabled; otherwise contact the maintainer privately with the affected version, impact, reproduction steps, and a safe remediation suggestion.

## Supported versions

Only the latest version on the default branch is maintained. This project is personal software and does not promise a security response time, but reports will be reviewed as soon as practical.
