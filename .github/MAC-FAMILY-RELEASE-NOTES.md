## Ruffster for Mac 0.1.20

Ruffster helps parents and children understand everyday computer use together, including during the school day. This Mac family app keeps its monitoring status visible, encrypts activity reports for the parent, and includes a local dashboard. Setup now explains before monitoring starts that it applies only to the signed-in Mac account.

### Download and open

Download `Ruffster-Mac-Family-App-Apple-Silicon.dmg`, open it, and drag Ruffster into Applications. The app bundle has a local ad-hoc signature so macOS can verify its bundled files are consistent; it is not signed or notarized by Apple. If macOS says it cannot check Ruffster, choose Done, then open System Settings > Privacy & Security and choose Open Anyway for Ruffster under Security. Open Ruffster again and choose Open. This approves Ruffster only and keeps your Mac's general app protections on. If macOS says the app will damage your computer or is damaged, stop and contact the Ruffster project. See [Apple's instructions](https://support.apple.com/en-us/102445). The adjacent `.sha256` file checks that the download arrived unchanged; it is not a publisher signature.

During child setup, Ruffster explains the small amount of day-level metadata it keeps so older records can be removed automatically while activity details stay encrypted for the parent.

The child setup disclosure has been shortened to remove repeated technical wording while still explaining what Ruffster records, what stays private, optional app network totals, and monitoring interruptions.

The parent report now keeps optional website estimates out of the way when there are no website observations. It still clearly says when no website details were recorded and keeps the explanation available.

### Set up together

Start with the parent Mac, choose a six-digit PIN your child does not know, and save the recovery copy. Then set up each child's Mac together and read the collection choices. Ruffster starts when that account signs in, shows its status in the menu bar, and restarts after an unexpected stop. The parent report summarizes recorded monitoring time, gaps, and sessions that follow an unclosed session. It cannot tell why the earlier session ended.

While parent access is unlocked, you can change the PIN saved on that parent computer. The existing reports and child computers keep using the same parent key. Other parent computers and earlier recovery copies keep their current PIN; save and confirm a fresh recovery copy before setting up another child.

Setup now waits for launchd to start the agent, confirm it is still running, and save a fresh encrypted sample before reporting success. The final message points families to the visible menu-bar status and offers a direct route to settings and removal.

If the two-digit nearby-computer connection does not work, the Mac setup screen now offers a direct retry or the connection-file option. It explains the same-Wi-Fi requirement and where to allow Ruffster on the Mac's Local Network settings.

Nearby-computer sharing now reopens cleanly after a one-time connection is used. Its Windows discovery port is outside Windows' default dynamic port range, avoiding a reserved-port bind failure seen in hosted Windows checks.

The Mac app has been checked with automated tests and synthetic activity. A real family setup and report exchange are the next validation step. Ruffster records foreground app names and network measurements; network totals do not identify websites. It does not record screenshots, keystrokes, messages, audio, or camera data. Windows setup is not part of this Mac download.

See the [family install guide](https://mikeymckay.github.io/ruffster/install.html), [privacy and children's rights notes](https://github.com/mikeymckay/ruffster/blob/main/PRIVACY-AND-CHILDREN.md), and the release's source commit.
