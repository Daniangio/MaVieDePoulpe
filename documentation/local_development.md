# Local Development

Run the reusable game services stack locally with Docker and open it from
`localhost`.

## Prerequisites

- Docker Engine with the Compose plugin.
- A Firebase project with email/password auth enabled.
- A Firebase Admin SDK service-account JSON for the backend.

## One-Time Setup

1. Copy the local environment template:

   ```bash
   cp .env.example .env
   ```

2. Fill in the Firebase Web SDK values and backend Firebase values in `.env`.

   The frontend values come from Firebase Console -> Project settings -> General
   -> Your apps -> Web app config:

   ```dotenv
   VITE_FIREBASE_API_KEY=...
   VITE_FIREBASE_AUTH_DOMAIN=...
   VITE_FIREBASE_PROJECT_ID=...
   VITE_FIREBASE_APP_ID=...
   VITE_FIREBASE_MESSAGING_SENDER_ID=...
   VITE_FIREBASE_STORAGE_BUCKET=...
   ```

   These are public Firebase web-app identifiers. They are not the same as the
   Firebase Admin SDK service-account JSON.

3. Create the local secrets directory:

   ```bash
   mkdir -p secrets
   ```

4. Put the Firebase Admin SDK service-account JSON at the path configured by
   `FIREBASE_ADMIN_CREDENTIALS`, for example:

   ```text
   secrets/firebase-admin.dev.json
   ```

   To get this JSON, open Firebase Console -> Project settings -> Service
   accounts -> Firebase Admin SDK -> Generate new private key. Download the JSON
   file and save its full contents as `secrets/firebase-admin.dev.json`.

   Do not split the JSON into separate `.env` variables. The private key belongs
   inside this JSON file in the `private_key` field.

   A valid file has this shape:

   ```json
   {
     "type": "service_account",
     "project_id": "your-firebase-project-id",
     "private_key_id": "abc123...",
     "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
     "client_email": "firebase-adminsdk-xxxxx@your-firebase-project-id.iam.gserviceaccount.com",
     "client_id": "1234567890",
     "auth_uri": "https://accounts.google.com/o/oauth2/auth",
     "token_uri": "https://oauth2.googleapis.com/token",
     "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
     "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-xxxxx%40your-firebase-project-id.iam.gserviceaccount.com",
     "universe_domain": "googleapis.com"
   }
   ```

   If you paste the file manually, keep the `\n` sequences inside
   `private_key`; do not convert them to raw multi-line text inside the JSON
   string.

5. Set `FIREBASE_PROJECT_ID` in `.env` to the same value as the JSON
   `project_id`.

6. Set `FIREBASE_PRIMARY_ADMIN_EMAIL` in `.env` if you want the first admin to
   be auto-promoted after Firebase login.

## Where SSH Keys Go

Do not put SSH private keys in `.env` or in `firebase-admin.dev.json`.

There are two unrelated private-key concepts:

- Firebase Admin private key: this is the `"private_key"` value inside
  `secrets/firebase-admin.dev.json`. It usually starts with
  `-----BEGIN PRIVATE KEY-----`.
- Deployment SSH private key: this is an OpenSSH key used by GitHub Actions to
  connect to your VM. It usually starts with
  `-----BEGIN OPENSSH PRIVATE KEY-----`.

For local development, you normally do not need a deployment SSH key. If you are
setting up deployment, follow `documentation/github_actions_setup.md`:

- Put the public SSH key (`*.pub`) on the VM in `~/.ssh/authorized_keys`.
- Put the private SSH key in GitHub Actions secrets such as
  `PROD_VM_SSH_PRIVATE_KEY` or `PREVIEW_VM_SSH_PRIVATE_KEY`.
- Never commit either private key.

## Start the Stack

From the repository root:

```bash
docker compose up --build
```

That starts services on the published ports configured in `.env`:

- Frontend on `http://localhost:${FRONTEND_PORT}`
- Backend on `http://localhost:${BACKEND_PORT}`
- FastAPI docs on `http://localhost:${BACKEND_PORT}/docs`
- Adminer on `http://localhost:${ADMINER_PORT}`
- PostgreSQL on `localhost:${POSTGRES_PORT}`
- Redis on `localhost:${REDIS_PORT}`

## Optional RedisInsight

Start RedisInsight only when needed:

```bash
docker compose --profile ops up -d redisinsight
```

Then open `http://localhost:5540`.

## Common Commands

Start in the background:

```bash
docker compose up --build -d
```

Stop everything:

```bash
docker compose down
```

Reset local database volumes:

```bash
docker compose down -v
```

Run with Redis authentication enabled:

```bash
REDIS_PASSWORD=dev-redis-password \
REDIS_URL=redis://:dev-redis-password@redis:6379/0 \
docker compose up --build
```

Follow app logs:

```bash
docker compose logs -f backend frontend
```

## Windows Port Conflicts

On Windows, Docker may fail with an error like:

```text
ports are not available: exposing port TCP 127.0.0.1:5432 ... bind: An attempt was made to access a socket in a way forbidden by its access permissions
```

This usually means another local PostgreSQL service is already listening on
host port `5432`, or Windows has reserved that port.

The app containers do not need PostgreSQL to be published on host port `5432`;
the backend talks to the database inside Docker at `postgres:5432`. The
published host port is only for tools on your laptop.

Use a different host port in `.env`:

```dotenv
POSTGRES_PORT=15432
```

Then recreate the stack:

```bash
docker compose down
docker compose up --build
```

If you use a local database client from Windows, connect to:

```text
Host: 127.0.0.1
Port: 15432
Database: maviedepoulpe
Username: maviedepoulpe
Password: maviedepoulpe_dev_password
```

Adminer still connects through Docker using the service name `postgres`, so it
does not need any change.

## Notes

- The root `docker-compose.yml` is the base local stack.
- `docker-compose.override.yml` adds localhost-only database ports and Adminer.
- The frontend uses Vite and connects to the backend through `VITE_API_URL`
  and `VITE_WS_URL`. Leave those values blank in `.env` for Docker Compose to
  derive them from `BACKEND_PORT`; set them only when you need an explicit
  override.
- Game rooms, matchmaking, rules, and game state are intentionally absent from
  this template.
