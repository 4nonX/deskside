# Signing in

deskside has two ways to sign in, which can be combined:

- **Single sign-on with OpenID Connect**, against Authentik, Keycloak, Microsoft Entra ID, Zitadel or any other provider that speaks OpenID Connect. The role in deskside follows the groups in the provider.
- **Local accounts** with a password, managed under **Users**. Useful for a first test or a small setup without a provider.

## Single sign-on

### At the identity provider

Create an OAuth2 / OpenID Connect application:

| Setting | Value |
|---|---|
| Client type | Confidential (with a client secret) |
| Redirect URI | `https://<your deskside address>/api/auth/callback`, exactly like that |
| Scopes | `openid`, `profile`, `email`, and whatever makes the provider include group membership in the ID token |
| Grant | Authorization Code. deskside always uses PKCE (S256) |

Then make sure the ID token carries the user's groups. In Authentik that is the default `groups` claim; in Keycloak add a "Group Membership" mapper; in Entra ID enable group claims (and note that Entra sends group IDs, not names, unless configured otherwise).

### In deskside

```yaml
server:
  public_url: https://deskside.example.org     # the callback is built from this

auth:
  local_login: false                           # only single sign-on
  oidc:
    issuer: https://sso.example.org/application/o/deskside/
    client_id_file: /run/secrets/oidc_client_id
    client_secret_file: /run/secrets/oidc_client_secret
    label: Example SSO                         # text on the sign-in button
    roles:
      admin: [it-admins]
      editor: [helpdesk]
      viewer: [staff]
```

| Key | Default | Meaning |
|---|---|---|
| `issuer` | required | The provider's issuer URL. deskside reads `<issuer>/.well-known/openid-configuration` and checks that the provider reports the same issuer |
| `client_id`, `client_secret` | required | Better as `client_id_file` / `client_secret_file`, see [configuration.md](configuration.md) |
| `roles` | required | Groups per role. The highest role with a matching group wins. Someone in none of these groups is refused. Group names are compared without regard to case |
| `scopes` | `openid profile email` | Must contain `openid` |
| `username_claim` | `preferred_username` | Claim used as the account name in deskside; falls back to `sub` |
| `groups_claim` | `groups` | Claim that lists the groups |
| `label` | `Single sign-on` | Text on the sign-in button: "Sign in with …" |
| `redirect_url` | `<public_url>/api/auth/callback` | Only needed if deskside cannot know its public address |
| `verify_tls`, `ca_file` | | For a provider with a certificate from your own CA, see below |

### What happens on sign-in

1. deskside sends the browser to the provider with a random state, a nonce and a PKCE challenge. The state and the PKCE secret are kept in a short-lived signed cookie (ten minutes).
2. The provider sends the browser back with a code. deskside exchanges it for the tokens itself, server to server, never in the browser.
3. The ID token is checked against the provider's published keys: signature, issuer, audience (your client ID), expiry and the nonce of this very sign-in. Anything that does not match ends the sign-in with a message.
4. The groups decide the role. The account is created on first sign-in and its role is updated on every sign-in, so removing someone from a group takes effect the next time they sign in. Role changes are recorded in the audit log.
5. deskside sets its own session cookie (12 hours, `HttpOnly`, `SameSite=Strict`, `Secure` over HTTPS). Signing out ends the deskside session; the session at the provider stays.

Accounts created by single sign-on cannot sign in with a password, even if local sign-in is enabled.

### Certificates from your own CA

If the provider (or NetBox, or a webhook target) uses a certificate from an internal CA, give deskside that CA's certificate in PEM format, either for all connections:

```yaml
services:
  deskside:
    environment:
      DESKSIDE_CA_FILE: /certs/internal-ca.crt
    volumes:
      - /path/to/internal-ca.crt:/certs/internal-ca.crt:ro
```

or per block with `ca_file:`. The CA is added to the usual public ones, so connections to public services keep working. `verify_tls: false` switches checking off for one connection; do not use it for the identity provider.

## Local accounts

With `auth.local_login: true` (the default), deskside creates an account `admin` on first start from `server.admin_password`, and admins manage further accounts under **Users**. Passwords need at least 12 characters and are stored as scrypt hashes. After ten failed attempts from one address, sign-in is paused for five minutes.

With `auth.local_login: false`, the password form is gone, `POST /api/login` is refused, and no `admin` account is created. At least one group must then lead to the admin role, otherwise nobody can manage deskside.
