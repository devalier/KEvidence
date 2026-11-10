# Security policy

KEvidence is a public prototype. Reports of vulnerabilities are welcome and are handled before anything else.

## Reporting a vulnerability

Do not open a public issue. Use either:

- GitHub private reporting: *Security* tab of the repository, *Report a vulnerability*; or
- email to <kevidence@devalier.com>.

Say what you found, how to reproduce it and what an attacker gains. You will get an answer within five working days.
Please give us a reasonable time to fix the problem before publishing it. Good-faith research that respects other
users' data and the availability of the service will not be pursued.

## Scope

The code in this repository and the public instance. Out of scope: volumetric denial of service, social engineering,
and findings that need a compromised server or a compromised user device.

## Supported versions

Only the `main` branch is maintained. Fixes are not back-ported.

## What is in place

See *Deployment security* in the [README](README.md#deployment-security) for the controls and their limits, and
`tests/test_server_security.py` and `tests/test_hardening.py` for the tests that keep them in place.
