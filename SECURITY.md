# Security reporting

PhotoFlow is an early MVP without built-in authentication. Deploy on loopback or
behind an authenticated reverse proxy. See [privacy](docs/privacy.md) and
[deployment](docs/deployment.md) for the trust boundaries.

If repository private vulnerability reporting is enabled, use it for security
issues. Otherwise open an issue with only a nonsensitive description and request
a private reporting channel from maintainers. Never publish personal photos,
real EXIF/GPS, credentials, database exports, or private NAS paths in an issue.

Use a synthetic reproduction. Include the PhotoFlow revision, Python/ExifTool
versions, operating system, and whether the deployment uses a read-only NAS mount.
