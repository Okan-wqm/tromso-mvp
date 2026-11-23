# The first admin and the first invitations

After [install.md](install.md), with every service healthy. `dc` is `docker compose --env-file farm.env` in `deploy/`.

## 1. The platform admin

The platform admin is a Django superuser: it opens everything and is the only one who manages roles and users
(README, Roles and users). Make one, for a named person, on the server:

```
dc run --rm manage python manage.py createsuperuser
```

**No second factor and no lockout:** the console's sign-in (and Django's admin at `/admin/`) asks for a password
only. What slows a guesser is the proxy (submitted sign-in forms limited per client address, `PROXY_SIGNIN_PER_MINUTE`;
`/admin/` refused outside `PROXY_ADMIN_ALLOW`) and the network in front: the VPN, or Cloudflare Access with its own
second factor ([access.md](access.md)). Use long generated passwords.

It asks for a username, an e-mail address and a password (at least the validators' length; use the password
manager's generator). It runs as the app role, like the server itself. Make at most two (the owner and a deputy);
everyone else gets a role.

## 2. The company

Signed in as the platform admin (`https://<SITE_HOST>`):

1. Company › Administration › Platform settings: the correction window, second approvals, alarm escalation.
2. The production roles: `dc run --rm manage python manage.py hr_roles` makes the Production manager and
   Production worker roles when they are missing; other roles are made in Company › Administration › Roles.
3. The sites, systems, units and reference data, then Opening balances for the fish already on the farm.
4. `dc run --rm manage python manage.py check --database default`: quiet (core.W003, core.W004).

## 3. Invitations

Company › Administration › Users › New user: the name, the e-mail address, the language and the roles. Saving
sends the **invitation** (README, Email): a one-time link, valid `ACCOUNT_LINK_HOURS` (24 h), that sets the password.
Nobody is ever given a password by hand.

- The user's row shows the invitation as sent, or why it failed; "Send invitation again" makes a new link.
- "Forgot your password?" on the sign-in page sends a reset link the same way (three an hour per account; the proxy
  also limits the page per client).
- A test before go-live: invite yourself at a second address, open the link, set a password, sign in; ask for a reset
  and use it; check both mails arrived from `DEFAULT_FROM_EMAIL` and not in spam.

## 4. Guests and students

Guests (inspectors, students of an experiment) get their own accounts with narrow roles, never a shared account.
With Cloudflare Access, add them to the application's guest policy for the days they need ([access.md](access.md));
remove both when they leave.

## 5. Leaving

When a person leaves: deactivate the account (Users), remove them from the Access policy or VPN, and, if they held
the platform admin, rotate what they could read ([rotate-secrets.md](rotate-secrets.md)).
