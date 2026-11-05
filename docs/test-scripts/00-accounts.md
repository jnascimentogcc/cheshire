# Test accounts

The scripts need four accounts. There is **no user-management screen** in v1: the admin is created
on the command line and everyone else is invited through the API. The invitation token is shown
once and is handed over by the admin (no e-mail in v1, `docs/api.md`).

| Account | Role | Used for |
|---|---|---|
| Admin | admin | everything, plus reassigning discussions |
| Bea | architect | a second architect: concurrent edits, positions, being mentioned |
| Carl | architect | a third architect (discussions with three people) |
| Una | user | the plain user: read-only catalog, own consultations |

## 1. Admin

```bash
docker compose run --rm cli create-admin
```

Choose the e-mail and a password of at least 12 characters yourself.

## 2. Invite the others

Run in Git Bash from the repository folder. Replace the placeholders. The ports are the ones the
app was started with (web `8090` here).

```bash
BASE=http://127.0.0.1:8090
read -p "Admin e-mail: " EMAIL; read -s -p "Admin password: " PW; echo
curl -s -c jar.txt -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\"}" $BASE/api/auth/login > login.json
CSRF=$(sed -n 's/.*"csrf_token":"\([^"]*\)".*/\1/p' login.json)

invite() {  # invite <email> <role>
  curl -s -b jar.txt -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"role\":\"$2\"}" $BASE/api/users/invitations
  echo
}
invite bea@example.org architect
invite carl@example.org architect
invite una@example.org user
```

Each call prints `{"token": "...", "expires_at": ...}`. Open
`http://127.0.0.1:8090/accept-invitation?token=<token>` in a **separate browser profile or a
private window** for each person, give a name (Bea, Carl, Una) and a password. Delete `jar.txt`
and `login.json` afterwards.

## 3. Deactivate someone (for the "orphaned discussion" step)

```bash
curl -s -b jar.txt -H "X-CSRF-Token: $CSRF" $BASE/api/users            # find the id
curl -s -b jar.txt -X PATCH -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"active":false}' $BASE/api/users/<id>                           # deactivate
```

Use `{"active":true}` to bring the account back.

## 4. Working with several people at once

Use one browser profile per account, or one normal window plus private windows. Cookies are shared
inside a profile, so two accounts in the same profile will sign each other out.
