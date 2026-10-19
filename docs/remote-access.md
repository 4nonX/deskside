# Remote access

Each device card can show one button per remote access tool. A button either opens a link (which the operating system hands to the matching program), downloads a small connection file, or, where neither is reliable, copies the ID or address to the clipboard. Every button also has a copy icon next to it, so you can always fall back to pasting.

deskside never stores passwords for remote sessions and never talks to the remote tools itself. Authentication stays with the tool.

## Built-in tools

| Key | Opens | Needs | How the link was verified |
|---|---|---|---|
| `rdp` | Downloads `<device>.rdp`, which opens the Remote Desktop client | the device's address | Microsoft's documented `.rdp` file format. Works with `mstsc` on Windows and the Windows App on macOS |
| `rustdesk` | `rustdesk://connect/<id>` | RustDesk ID | Read from RustDesk's own source (`flutter/lib/common.dart`, `urlLinkToCmdArgs`), which also accepts the shorter `rustdesk://<id>`. Self-built RustDesk clients with a different app name may use a different scheme |
| `teamviewer` | `tvcontrol1://control?device=<id>` | TeamViewer ID | **Not officially documented by TeamViewer.** The scheme is registered by the TeamViewer client and used by several management tools; test it with your client version |
| `anydesk` | copies the ID | AnyDesk ID | AnyDesk documents a command line (`anydesk.exe <ID>`) but no URL scheme, so deskside does not assume one. See below to add a link if your clients have a handler |
| `vnc` | `vnc://<address>` | the device's address | Registered URI scheme (RFC 7869). Opens on macOS (Screen Sharing) and with VNC viewers that register the scheme; many Windows viewers do not |
| `ssh` | `ssh://[user@]<address>` | the device's address | Common URI scheme. Opens on macOS and most Linux desktops; Windows needs a client that registers it |
| `web` | `https://<address>/` | the device's address | Plain web link, for devices with a web interface (printers, switches, appliances) |

`<address>` is the value stored on the device entry if there is one, otherwise the device's current host name, otherwise its current IP address. Every value is URL-encoded before it goes into a link, so an ID or address cannot add parameters or change the link.

## Adding remote access to a device

On the device card, editors use **Add remote access**: pick the tool and enter the ID (for ID-based tools) or, optionally, an address and user name (for address-based tools). An optional label tells several entries of the same tool apart.

Tools that need only an address can also appear automatically for whole device types, see `auto_kinds` below. That way every workstation gets a Remote Desktop button without adding it device by device.

## Configuration

The `remote_tools` section changes built-in tools, removes them or adds new ones. Only the keys you set are changed.

```yaml
remote_tools:
  rdp:
    auto_kinds: [workstation]          # every workstation gets a Remote Desktop button
    rdp_options:                       # any setting from Microsoft's .rdp format
      "screen mode id:i": 1            # 1 = window, 2 = full screen
      "redirectprinters:i": 0
  web:
    auto_kinds: [printer, switch]
  vnc: false                           # remove a tool you do not use
  anydesk:
    link: "anydesk:{value}"            # only if your clients have a URL handler for anydesk:
  console:                             # a new tool: any link template works
    label: Web console
    needs: id
    link: "https://console.example.org/connect?id={value}"
```

| Key | Meaning |
|---|---|
| `label` | Button text |
| `needs` | `id` (the device entry must carry a value) or `address` (uses the device's address) |
| `link` | Link template. Placeholders: `{value}`, `{address}`, `{ip}`, `{hostname}`, `{user}`. Must start with a URL scheme; `javascript:`, `data:`, `vbscript:` and `file:` are refused |
| `file` | `rdp` to generate a Remote Desktop file instead of a link |
| `auto_kinds` | Device types that get this tool automatically (address-based tools only) |
| `user` | Default user name, used when the entry has none |
| `rdp_options` | Extra `.rdp` settings, written as `"name:type": value`. Values may not contain line breaks |

A web console such as Apache Guacamole or MeshCentral works the same way: give it a link template with the identifier it expects. Check the console's documentation for the exact URL format; deskside does not ship templates for them because they depend on how each installation is set up.

## Security notes

- The `.rdp` file contains the address and, if set, a user name. Never a password.
- Values entered on a card may not contain spaces or line breaks, and are encoded before use. A crafted value cannot add `.rdp` settings (such as a different program to start) or link parameters.
- Opening a custom URL scheme asks the browser's permission the first time. That prompt comes from the browser, not from deskside.
