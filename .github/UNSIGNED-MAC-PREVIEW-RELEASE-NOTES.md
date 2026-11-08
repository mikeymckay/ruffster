## Unsigned development preview — not a family release

This Apple silicon app is **not signed or notarized by Apple**. macOS may block it and show a security warning. Ruffster cannot verify that Apple has checked this app. Read the included `READ BEFORE OPENING.txt` and [Apple's guidance about opening apps safely](https://support.apple.com/en-us/102445) before deciding whether to test it. Never disable Gatekeeper or remove the download quarantine to force it open.

This is early software, has not received an independent security review, and is **not for ongoing monitoring of a child**. Windows has not yet been validated on a Windows computer. The app does not install monitoring just because it is copied into Applications; read the privacy information and review setup together with the computer user.

The release tag identifies the source. The adjacent `.sha256` file lets you check whether the DMG changed in transit; it is not a signature and does not prove who built the file. Build workflow and test results are linked under this release's GitHub Actions run. Review the source and use only a release you intentionally chose to download.

If macOS blocks the app, stop unless you have independently reviewed the source and understand Apple's warning. Manual Gatekeeper override is optional and entirely at the tester's discretion. Do not use Terminal workarounds.
