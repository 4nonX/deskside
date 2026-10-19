# Using deskside

## Finding a device

There is one search field, and it searches everything: device names, host names, IP addresses, MAC addresses, switch ports, rooms, departments, users, contact details (for roles allowed to see them) and the text of notes. The list narrows as you type.

A few things that help:

- **Several words narrow the result.** `lab printer` finds devices that match both words, for example a printer in a room called "Lab".
- **Partial addresses work.** `.109` finds `10.0.10.109`. MAC addresses match in any notation and from four hex digits on: `00005e`, `00-00-5E` and `00:00:5e` find the same device.
- **Ports match long and short names.** `ge7`, `gi7` and `GigabitEthernet7` all find the device on that port.
- **Keyboard:** `/` jumps to the search field, Enter opens the first result, Escape closes the card.
- The search is part of the address (`?q=...`), so a search can be bookmarked or sent to a colleague.

The filters above the list show all devices, only the ones you have named (**Known**), only addresses nobody has named yet (**Unknown**), or what is **Online** right now.

## The device card

Selecting a row opens the card. It is meant to answer a support call without further clicks:

- **Pinned warnings** at the top, for things the next person must know ("power connector is loose").
- **Users**, with the main user first, their job title and department, and phone, mobile and e-mail as links you can click.
- **Place**: room and department.
- **Network**: for every MAC address of the device, its IP address, host name, vendor, switch and port, whether the address is fixed or from DHCP, whether it is online, and since when it has been on its current port. If a port carries many addresses, the card says so: the device then sits behind another switch or a hypervisor, and the exact port is not known.
- **Notes**, newest first, with author and time. Any note can be pinned as a warning.
- **Recent events** for the device: new, online, offline, moved, readdressed.

If a naming convention is configured, the card warns when the name does not fit or the address differs from the one the convention expects.

## Turning an unknown address into a device

Unknown addresses are in the list too, in italics. Open one and either

- **create a device**: the name field is pre-filled from the host name (in the form of your naming convention, if one matches), and the next free name is offered as an alternative; or
- **assign it to an existing device**, for example a laptop's second network card or a docking station.

From then on everything deskside learns about that address shows up on the device's card.

## The Directory page

- **Rooms**: number, name, building, floor, description. Number or name is enough.
- **Departments**: created by hand or from the directory. Departments from the directory cannot be renamed or deleted here.
- **People**: everyone who can be assigned to a device. People from the directory are read-only here; their details change in the directory and arrive with the next sync. Admins can start a sync with **Sync directory now**.

## Roles

Viewers can search and read. Editors can also change devices, notes, rooms, departments, people and assignments. Admins can also delete devices and manage accounts. Whether viewers see phone numbers and e-mail addresses is a configuration setting. Every change is recorded with user and time.
