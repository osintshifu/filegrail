# Security Policy

## Reporting a vulnerability

Please do not open a public issue for anything that could expose investigation
data, a user's browsing history, or a secret.

Until a dedicated private channel is configured, use GitHub's private
vulnerability reporting for this repository.

Please include the affected version or commit, reproduction steps, the impact,
and a suggested mitigation if you have one.

## Supported versions

Security fixes go into the latest release.

## What is in scope

`filegrail` reads local records that are, by design, sensitive. The output can
contain every URL a file came from and every command that touched it. Issues
worth reporting:

- **A secret surviving `--redact`.** The redaction is biased towards precision,
  so a false negative is a real finding. Include the shape of the credential.
- **Reading or writing outside the scanned directory**, or outside the browser
  profiles the tool declares it reads. A crafted file must not be able to make
  the scan touch an arbitrary path.
- **Modification of anything inspected.** The tool copies a browser profile
  before opening it and never writes to a scanned file. A path that breaks that
  is a bug of the first order.
- **A crafted file causing unbounded memory use or a hang.** Every parser here
  reads untrusted input and carries explicit bounds; a way past them counts.
- **A metadata claim rendered as more certain than it is** — most importantly a
  C2PA manifest presented without its "signature not verified" note, since the
  tool does not validate the certificate chain.

## Security-sensitive areas

Changes to these need extra review:

- `redact.py`, and every path that renders a URL or a command;
- the parsers under `sources/embedded/`, `sources/c2pa.py` and `cbor.py`, all of
  which read untrusted bytes;
- `sources/browser.py`, which copies and opens the user's browser profiles;
- archive handling in `sources/archives.py`;
- path handling in `scan.py`.
