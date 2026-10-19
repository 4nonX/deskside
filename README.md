# deskside

deskside is a self-hosted overview of the devices in a network, built for support work. Type anything you know about a machine, such as part of its name, IP or MAC address, its room, its user or a phone extension, and you get one card with everything a support call needs:

- what the device is and what it is called, following your own naming convention if you have one
- where it is plugged in right now (switch, port, patch panel) and whether it is online
- which room and department it belongs to
- who uses it and how to reach them
- pinned warnings and notes ("power connector is loose, handle with care")
- one button per remote access tool (RDP, VNC, SSH, AnyDesk, RustDesk and others)

The network part of each card keeps itself current. deskside reads switch MAC tables over SNMP (or from Netdisco), ARP tables, DHCP leases and your directory, and matches what it sees to the devices you know about. New, moved and vanished devices show up on their own.

## Status

Early development. The design is settled, the code is not written yet, and there is nothing to install. The plan and the reasoning behind it are in [docs/design.md](docs/design.md).

## Principles

- **Fits your network, not ours.** Every data source is optional and every convention lives in configuration. Standard MIBs, standard protocols, no vendor lock-in.
- **Read-only towards your infrastructure.** deskside never writes to switches, DHCP servers or the directory.
- **Careful with your inventory.** If you connect NetBox, low-risk fields (such as "last seen") are updated automatically. Anything structural, like a new cable or device, is offered as a proposal that someone confirms.
- **No stored remote credentials.** deskside opens your remote tool; the tool does the authentication.
- **Personal data handled deliberately.** Only the directory attributes you list are imported, history has a retention limit, and contact details can be hidden from read-only users.

## Licence

Apache License 2.0, see [LICENSE](LICENSE).
