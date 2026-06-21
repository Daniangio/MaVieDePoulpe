# Adminer local backoffice

This project now includes a local `Adminer` service in `docker-compose.yml`.

## Access model

- URL: `http://127.0.0.1:8081`
- Binding: localhost only
- Scope: local development / local operations only

This is intentionally **not** integrated with maviedepoulpe app authentication. Adminer is a database tool, not an in-app admin page.

The practical security model is:

- only someone with local machine access can open it
- only someone with database credentials can log in

That is acceptable for local/dev operations. It is **not** the production admin solution.

## Login

Use these values in the Adminer login page:

- System: `PostgreSQL`
- Server: `postgres`
- Username: `maviedepoulpe`
- Password: `maviedepoulpe_dev_password`
- Database: `maviedepoulpe`

## Start it

Run:

- `docker compose up --build`

Then open:

- `http://127.0.0.1:8081`

## What it is for

Use Adminer for:

- inspecting tables
- running SQL queries
- searching users, sessions, decks, collections, rooms
- fixing local corrupted state during development

## What it is not for

Do **not** treat Adminer as the final production backoffice.

Avoid direct SQL edits for:

- active live matches
- Redis-backed presence/routing state
- anything that should go through backend service logic

For operational actions with invariants, the correct long-term solution remains an internal admin app backed by explicit backend admin endpoints.

## Useful tables

Current high-value tables include:

- `users`
- `sessions`
- `player_profiles`
- `player_decks`
- `player_card_collections`
- `rooms`
- `room_seats`
- `room_invites`

## Notes

- App-level seeded admin users such as `admin` / `operator` are **not** the same thing as database users.
- Adminer login uses PostgreSQL credentials, not maviedepoulpe account credentials.
- Keep this service localhost-bound. Do not expose it publicly.
