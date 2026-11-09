# How family reports are encrypted

Ruffster encrypts activity on the child's Mac before saving it. The parent sets up access on the parent computer; the child's Mac receives only what it needs to protect reports. Choose six numbers your child doesn't know, and keep the recovery copy somewhere you can find it. Ruffster does not use a cloud service to read reports.

The PIN is for simple family access: a parent can open the reports, and the child doesn't need to know the PIN. It is not a long technical password. Keep the PIN and recovery copy somewhere you can find them.

## Setting up and sharing

1. On the parent computer, create parent access with a six-digit PIN and save the recovery copy.
2. Pair one child's Mac at a time. The two-digit number helps the computers find each other on the same Wi-Fi; it is not a secret and does not unlock a report. If nearby-computer sharing is unavailable, the parent can give the child Mac a connection file instead.
3. The child's Ruffster app encrypts each observation before writing it to the local report. When the parent opens or imports that report, Ruffster decrypts it on the parent computer for the dashboard.

Reports stay encrypted when sent over the local network or saved to a file. The connection setup shares only the parent's public encryption key. It never sends the parent's private key or the encrypted parent recovery copy to the child's Mac.

## What the child's Mac saves

App names, exact activity times, network measurements and settings, and any parent-chosen computer name are inside encrypted records. A random ID distinguishes one Ruffster installation from another; it is not a hardware or location identifier. The ID is saved in a private sidecar and included inside encrypted records so a parent can keep reports from multiple computers separate.

A few details remain visible so the child-side app can manage the database:

- The number and order of encrypted records, and how much space they use.
- A rough record-size range. Ruffster pads records to one of several sizes, which hides their exact length but still gives an approximate size.
- The expiration day for each record. It shows roughly which UTC day it belongs to, not the exact activity time.
- A fingerprint identifying the parent's public key, so Ruffster can refuse to mix reports made for a different parent key.

Ruffster removes expired records when monitoring starts and while it is running. Since expiry uses a day marker, a record may be removed up to one day earlier than the selected maximum. If the computer is off, cleanup waits until Ruffster runs again. Copies already exported or saved elsewhere are not changed by these settings.

## Practical limits

- The six-digit PIN is easy to try if someone gets a copy of the parent's key file. The design goal is that the child does not know the PIN; the PIN is not meant to withstand an attacker who has copied that file. There is no master recovery key. If the PIN and every usable recovery copy are lost, the encrypted reports cannot be opened.
- Ruffster checks that a record was encrypted for the right parent key and detects changed ciphertext. It cannot prove which program wrote a record, or detect if someone removes, reorders, repeats, or replaces records. Use reports as a helpful family picture, not as a forensic record.
- A computer has to see activity before it can encrypt it. Someone with full access to the child's computer or its software could inspect activity before encryption or change the app. Ruffster does not claim to detect that.
- The parent dashboard keeps report contents in memory while showing them. The operating system may also use memory, backups, or snapshots; retention settings do not control those copies. The parent key is not yet stored in a platform keychain.
- Older developer prototypes and low-level tools may have created plaintext databases. Ruffster does not silently convert or delete them. A developer-only `encrypt-legacy` command supports one known older format, writes a new encrypted copy, and leaves the old file untouched. Check existing prototype data before sharing or retaining it.
- Optional browser and network indicators have separate collection limits. Website names are not included in the standard Mac setup; network totals do not identify websites. See the [collection details and children's-rights notes](PRIVACY-AND-CHILDREN.md).

## Implementation notes

The agent uses libsodium sealed-box encryption through PyNaCl. New parent key vaults use Argon2id and SecretBox; the six-digit PIN protects the local vault file. The Mac agent database contains a row ID, expiration day, key fingerprint, and ciphertext rather than event fields. Existing reports encrypted with earlier 4 KiB padding remain readable. The parent dashboard reconstructs reports in a temporary in-memory SQLite database.

This page describes Ruffster's current implementation and limits; it is not an independent security review. See [libsodium sealed boxes](https://doc.libsodium.org/public-key_cryptography/sealed_boxes) and [PyNaCl public-key encryption](https://pynacl.readthedocs.io/en/latest/public/).
