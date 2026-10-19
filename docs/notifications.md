# Notifications

deskside can tell you when something happens on the network: a device nobody has seen before, a workstation plugged into a different port, a device that went offline, an address outside the naming scheme, or a switch port that suddenly carries many addresses.

Notifications are optional. Each channel is an entry under `notifications:` in the configuration.

## Batching

Events are collected for one minute (`live.notify_batch_seconds`) and sent as one message per channel. A switch that reboots produces one message listing what went offline and came back, not fifty separate ones. A message lists at most 40 events and says how many more there were.

## Channels

### Chat (and other webhooks taking text)

```yaml
notifications:
  - type: webhook
    name: it-chat
    url_file: /run/secrets/chat_webhook_url
    events: [new, moved, scheme, busy_port]
    only_known: false
```

With the default `format: text`, deskside sends `{"text": "..."}`. Slack incoming webhooks, Mattermost, Rocket.Chat and Google Chat accept that as it is. Keep the webhook URL in a secret file: whoever has it can post into your channel.

### Any other HTTP endpoint

```yaml
  - type: webhook
    name: automation
    url: https://automation.example.org/hooks/deskside
    format: json
    headers: { Authorization: "Bearer ${AUTOMATION_TOKEN}" }
    events: [all]
```

`format: json` sends `{"source": "deskside", "summary": "...", "events": [...]}` with every event's kind, time, MAC address, device and details, for tools such as n8n, Node-RED or Home Assistant.

### E-mail

```yaml
  - type: email
    name: it-mail
    host: smtp.example.org
    security: starttls          # starttls (port 587), ssl (port 465) or none (port 25)
    user: deskside@example.org
    password_file: /run/secrets/smtp_password
    from: deskside@example.org
    to: [it@example.org]
    events: [new, offline]
    only_known: true
```

## Settings for every channel

| Key | Default | Meaning |
|---|---|---|
| `type` | required | `webhook` or `email` |
| `name` | `<type>-<n>` | Shown on the status page |
| `events` | `new, moved, offline, scheme, busy_port` | Which events to send, or `all` |
| `only_known` | `false` | Send events about devices in deskside only, not about unknown addresses. Useful against noise from phones and guest devices |
| `verify_tls` | `true` | `false` for an endpoint with a self-signed certificate |

Webhooks additionally take `url`, `format` (`text` or `json`) and `headers`. E-mail takes `host`, `port`, `security`, `user`, `password`, `from`, `to` (one address or a list) and `subject_prefix` (default `[deskside]`).

Set `server.public_url` (for example `https://deskside.example.org`) so messages end with a link to deskside.

## Events

| Event | When |
|---|---|
| `new` | An address appears that deskside has never seen |
| `online` | A known address is seen again after being offline |
| `offline` | Not seen in a switch table or ARP for `live.offline_after` seconds |
| `moved` | A device is seen on a different switch port |
| `ip_changed` | A device uses a different IP address |
| `scheme` | A device moved to an address its naming convention does not expect |
| `busy_port` | A switch port now carries more addresses than `live.uplink_mac_threshold` without a known neighbour, typically a newly added desk switch |
| `discovery` | The very first collection run |

## Checking a channel

Each channel appears on the **Sources** page (under **Admin**) with its last success, how many messages and events it sent, and its last error. Admins can send a test message to all channels from there. A failing channel does not block the others; the next batch is tried normally.
