# Security policy

Please do not publish credentials, API keys, passwords, private keys, tokens, certificates, or personal data in issues, pull requests, or commits.

If a secret may have been exposed, revoke or rotate it immediately, then report the incident privately to the repository maintainer. Removing a secret from the latest commit does not remove it from Git history.

This repository runs automated secret scanning on pushes and pull requests. Use environment variables, an OS credential store, or a managed secret service for runtime credentials. Paper execution, when explicitly enabled, is forced through Moomoo's `TrdEnv.SIMULATE`; live trading is not supported by this public build.
