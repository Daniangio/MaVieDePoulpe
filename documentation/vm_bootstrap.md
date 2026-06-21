# Ubuntu VM Bootstrap

This guide assumes:

- You have SSH access to a fresh Ubuntu VM
- You want the app to live under `/opt/maviedepoulpe`
- GitHub Actions will later upload `deploy/docker-compose.yml` and `deploy/Caddyfile`
- You will run the split runtime (`backend` gateway + `backend-worker`)

## Read this first: execution order

Use this exact order for a fresh VM:

1. Complete this file from Section 1 to Section 8.
2. Verify the stack locally on the VM (Section 8 checks + Section 9 optional RedisInsight).
3. Configure GitHub Actions secrets using `documentation/github_actions_setup.md`.
4. Trigger the deploy workflow.

If you skip Section 8 verification, CI failures are harder to diagnose because both infra and workflow variables are unknown.

## 1. Prepare DNS

Point your domain or subdomain to the VM public IP before the first production deploy.

Example:

- `play.example.com` -> VM public IPv4

The production Caddy config expects `APP_DOMAIN` to be a real hostname so it can provision HTTPS automatically.

## 2. Install Docker and Compose

SSH into the VM and run:

```bash
# 1. Purge any conflicting unofficial packages shipped by the OS
sudo apt-get remove -y docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc

# 2. Update package index and install prerequisite transport tools
sudo apt-get update
sudo apt-get install -y ca-certificates curl

# 3. Create the keyring directory securely
sudo install -m 0755 -d /etc/apt/keyrings

# 4. Download the modern ASCII-armored key (.asc) directly (Idempotent operation)
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc

# 5. Ensure correct read permissions for the apt process
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 6. Add the official Docker repository to Apt sources
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 7. Update the index with the new repository and install the official binaries
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 8. Grant the current user permission to communicate with the Docker daemon
sudo usermod -aG docker $USER
```

Log out and back in once so the `docker` group membership is applied.

## 3. Open the Firewall

This step depends on where the VM is hosted.

### Oracle Cloud Infrastructure

On Oracle Cloud Ubuntu images, it is common to manage public exposure in two layers:

- OCI ingress rules in the Oracle Cloud console
- The VM's local `iptables` rules

For this case, do not rely on UFW as the primary path. Instead:

1. In the OCI console, add ingress rules for:
   - TCP `80`
   - TCP `443`
2. On the VM, insert local `iptables` rules so they are evaluated before Oracle's default reject rule:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
```

The `6` index is commonly appropriate on Oracle Ubuntu images because the early positions are usually reserved for SSH and system rules, and these entries need to be placed before the final `REJECT`.

To make the rules persistent across reboots:

```bash
sudo apt-get update
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
sudo netfilter-persistent reload
```

To verify:

```bash
sudo iptables -L INPUT -n --line-numbers
```

You should see `ACCEPT` rules for ports `80` and `443`.

### Other Ubuntu Hosts

If your provider does not already manage a restrictive `iptables` policy, UFW is still a simple option:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 4. Create the Deployment Directory

```bash
sudo mkdir -p /opt/maviedepoulpe/secrets
sudo mkdir -p /opt/maviedepoulpe/data/maps
sudo chown -R $USER:$USER /opt/maviedepoulpe
```

## 5. Create the Production Env File

Use `deploy/.env.example` from this repository as your template on your local machine, then create `/opt/maviedepoulpe/.env` on the VM with real values:

```dotenv
APP_DOMAIN=play.example.com

POSTGRES_DB=maviedepoulpe
POSTGRES_USER=maviedepoulpe
POSTGRES_PASSWORD=replace-with-a-long-random-password

BACKEND_IMAGE=ghcr.io/your-github-owner/maviedepoulpe-backend:latest
FRONTEND_IMAGE=ghcr.io/your-github-owner/maviedepoulpe-frontend:latest

FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_PRIMARY_ADMIN_EMAIL=admin@example.com
USE_DISTRIBUTED_MATCH_RUNTIME=true
DISTRIBUTED_GATEWAY_RUN_BRIDGE=false

# Replay artifact storage.
# Keep local for simple test deployments. Set to gcs + true after creating the bucket
# and placing the service account JSON in /opt/maviedepoulpe/secrets.
USE_OBJECT_STORAGE_REPLAYS=true
REPLAY_STORAGE_KIND=gcs
REPLAY_BUCKET=maviedepoulpe-replays-dev
REPLAY_EPHEMERAL_PREFIX=replays/ephemeral
REPLAY_PERMANENT_PREFIX=replays/permanent
GOOGLE_APPLICATION_CREDENTIALS=/opt/maviedepoulpe/secrets/gcp-service-account.dev.json

# Global chat over Redis Streams.
CHAT_STREAM_PREFIX=chat
CHAT_RETENTION_SECONDS=86400
CHAT_HISTORY_LIMIT=80

# Redis auth (recommended)
REDIS_PASSWORD=replace-with-a-long-random-redis-password
REDIS_URL=redis://:replace-with-a-long-random-redis-password@redis:6379/0

# Optional RedisInsight (ops profile)
REDIS_INSIGHT_PORT=5540
REDIS_INSIGHT_ENCRYPTION_KEY=replace-with-a-long-random-redisinsight-key
```

Important:

- Use the lowercase GitHub owner in the GHCR image names.
- Keep `.env` only on the VM. Do not commit it.
- If `REDIS_PASSWORD` is set, `REDIS_URL` must include that password.
- If `REDIS_URL` has no password but `REDIS_PASSWORD` is set, backend/worker auto-apply it.

## 6. Add the Secret Files

Create these files on the VM:

```text
/opt/maviedepoulpe/secrets/firebase-admin.prod.json
```

- `firebase-admin.prod.json` is your production Firebase service-account JSON.
  Get it from Firebase Console -> Project settings -> Service accounts ->
  Firebase Admin SDK -> Generate new private key.
- Save the full downloaded JSON file at
  `/opt/maviedepoulpe/secrets/firebase-admin.prod.json`.
- Do not put the Firebase Admin JSON into `/opt/maviedepoulpe/.env`. The `.env`
  file should only point to it through:

  ```dotenv
  FIREBASE_ADMIN_CREDENTIALS=/opt/maviedepoulpe/secrets/firebase-admin.prod.json
  FIREBASE_PROJECT_ID=your-firebase-project-id
  ```

- The JSON contains a `private_key` field that usually starts with
  `-----BEGIN PRIVATE KEY-----`. Keep it inside the JSON.
- This Firebase private key is not an SSH key. Do not add it to
  `~/.ssh/authorized_keys`, and do not store it as `*_VM_SSH_PRIVATE_KEY`.
- The first admin is now configured via `.env` using `FIREBASE_PRIMARY_ADMIN_EMAIL`.
- After first login, this user can promote other admins from in-game admin tools.

Set restrictive permissions after creating the file:

```bash
chmod 700 /opt/maviedepoulpe/secrets
chmod 600 /opt/maviedepoulpe/secrets/firebase-admin.prod.json
```

## 7. Copy the Production Bundle Once

Before GitHub Actions runs for the first time, copy these files to the VM:

```bash
scp deploy/docker-compose.yml deploy/Caddyfile your-user@your-vm:/opt/maviedepoulpe/
```

If your SSH port is not `22`, add `-P <port>`.

## 8. Manual First Deploy

### 8.1 Create a GHCR token (once)

Use a GitHub account that can read your private GHCR images (usually your main owner account or a machine user).

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens**
2. Create a **classic** token with at least:
   - `read:packages`
   - (`repo` is typically needed too when images are private and tied to a private repo)
3. Copy the token value immediately (it will not be shown again)

### 8.2 Log into GHCR on the VM

Log into GHCR on the VM using that token:

```bash
echo "<ghcr-token>" | docker login ghcr.io -u "<github-username>" --password-stdin
```

Notes:
- `github-username` is the account that owns the token.
- This login is for the VM host, not for GitHub Actions runners.

Then start the stack:

```bash
cd /opt/maviedepoulpe
docker compose --env-file .env pull
docker compose --env-file .env up -d
```

Check status:

```bash
docker compose ps
docker compose logs -f caddy backend frontend
```

Also verify worker and Redis before enabling CI deploys:

```bash
docker compose --env-file .env ps
docker compose --env-file .env logs -f backend-worker redis
```

Expected:

- `backend-worker` stays `Up` (not restarting in loop)
- Redis healthcheck is `healthy`
- No repeated `missing_runtime_state` errors in worker logs right after first mulligan/action

Once this works, the GitHub Actions workflow can take over future deploys.

## 9. Optional RedisInsight on Production VM (localhost only)

Run only when needed:

```bash
cd /opt/maviedepoulpe
docker compose --env-file .env --profile ops up -d redisinsight
```

RedisInsight binds to `127.0.0.1:${REDIS_INSIGHT_PORT}` on the VM, so it is not publicly exposed.

Access from your laptop via SSH tunnel:

```bash
ssh -L 5540:127.0.0.1:${REDIS_INSIGHT_PORT:-5540} ubuntu@your-vm-host
```

Then open `http://localhost:5540`.

## 10. Current production limitations (important)

- The distributed runtime is currently transitional (worker bridge over existing room manager flow).
- Full object-storage-first replay lifecycle is still incremental.
- Timer orchestration is partially migrated; full distributed timer actor is still in progress.

## 11. Troubleshooting quick map

### Deploy job times out during `docker compose pull`

- Symptom: GitHub Actions deploy step fails with `Run Command Timeout`.
- Fix:
  - Use the updated workflow (longer SSH command timeout + pull only app images).
  - On very slow links, run once manually on VM:

```bash
cd /opt/maviedepoulpe
docker compose --env-file .env pull backend frontend backend-worker
docker compose --env-file .env up -d --remove-orphans
```

### Frontend not reachable after `.env` update

- Confirm `APP_DOMAIN` matches the real host you open in browser.
- Prefer DNS hostname (example: `preview.example.com`) over raw IP.
- Check Caddy:

```bash
docker compose --env-file .env logs -f caddy
```

### `Distributed command commit failed: missing_runtime_state`

- Cause: gateway and worker are split; worker needs the initial runtime snapshot in Redis.
- Fix status: addressed in backend startup flow; ensure updated backend image is deployed.
- Validate:

```bash
docker compose --env-file .env logs -f backend-worker
```

There should be no repeated `missing_runtime_state` errors on first mulligan/action.
