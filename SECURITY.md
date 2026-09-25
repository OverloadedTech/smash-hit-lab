# Security reports

This is a research repository rather than a deployed service, so the things
worth reporting are narrower than usual. The desktop editor binds a loopback
socket and also checks the Host header, the setup tooling downloads a pinned
dependency and verifies its SHA-256 before building it, and the input helper
talks to a device over adb. A way around any of those checks is worth a
report, as is anything that would let a prepared APK or project file run code
on the machine doing the analysis.

Report privately through this repository's security advisory page when it is
available. Otherwise contact
[Luca Zani (OverloadedTech)](https://github.com/OverloadedTech) to arrange a
private channel. Please do not open a public issue containing a working
exploit, and do not attach game binaries or assets to a report.

Nothing here is meant to run on a shared or internet-facing machine. Run Smash Hit Lab
on a workstation you control, against a device you own.
