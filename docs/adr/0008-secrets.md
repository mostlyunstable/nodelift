# 0008 — Credentials in the system keychain, referenced by name, masked everywhere

**Status:** accepted

**Decision.** Secret values live in the OS credential store (macOS Keychain via `keyring`); the database stores names and
metadata only; the API is write-only. Workflows reference a secret as `{{credential:NAME}}` inside HTTP header values.
The value is read when the node runs; every value used in a run (plus its URL-encoded and JSON-escaped forms) is masked
out of the node's output, logs and error text before anything is stored or streamed. Exports contain the reference, never
the value; import previews list the credentials a file needs.

**Limits.** Masking recognises the value, not transformations of it (a node that hashes or base64-encodes it defeats it).
Code nodes run unsandboxed and could read the keychain themselves (ADR 0004). Secrets must be at least 8 characters.
