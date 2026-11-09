## Ruffster for Mac 0.1.12

Ruffster helps parents and children understand everyday computer use together, including during the school day. This Mac family app keeps its monitoring status visible, encrypts activity reports for the parent, and includes a local dashboard.

### Download and open

Download `Ruffster-Mac-Family-App-Apple-Silicon.dmg`, open it, and drag Ruffster into Applications. This Apple-silicon build is not signed or notarized by Apple. If macOS says it cannot check Ruffster, choose Done, then open System Settings > Privacy & Security and choose Open Anyway for Ruffster under Security. Open Ruffster again and choose Open. This approves Ruffster only and keeps your Mac's general app protections on. If macOS says the app will damage your computer or is damaged, stop and contact the Ruffster project. See [Apple's instructions](https://support.apple.com/en-us/102445). The adjacent `.sha256` file checks that the download arrived unchanged; it is not a publisher signature.

### Set up together

Start with the parent Mac, choose a six-digit PIN your child does not know, and save the recovery copy. Then set up each child's Mac together and read the collection choices. Ruffster starts when that account signs in, shows its status in the menu bar, and restarts after an unexpected stop.

Setup now waits for launchd to start the agent, confirm it is still running, and save a fresh encrypted sample before reporting success. The final message points families to the visible menu-bar status and offers a direct route to settings and removal.

The Mac app has been checked with automated tests and synthetic activity. A real family setup and report exchange are the next validation step. Ruffster records foreground app names and network measurements; network totals do not identify websites. It does not record screenshots, keystrokes, messages, audio, or camera data. Windows setup is not part of this Mac download.

See the [family install guide](https://mikeymckay.github.io/ruffster/install.html), [privacy and children's rights notes](https://github.com/mikeymckay/ruffster/blob/main/PRIVACY-AND-CHILDREN.md), and the release's source commit.
