# GitHub Actions Setup

This repository now includes two deploy workflows:

1. `.github/workflows/deploy-preview.yml` (push to `preview`)
2. `.github/workflows/deploy-production.yml` (push to `main`)

Each workflow:
- builds/pushes backend + frontend images to GHCR
- deploys to its own VM target via SSH + Docker Compose

## Recommended setup order

1. Finish `documentation/vm_bootstrap.md` first (including manual deploy validation).
2. Then configure all GitHub secrets in this file.
3. Trigger workflow only after VM manual deploy works.

This guide is written for the current workflow and for a typical Oracle Cloud Ubuntu VM such as:

- VM host: `178.105.53.1`
- VM user: `root`
- SSH port: `22`

## Before You Start

Make sure these are already true:

- Your VM is reachable by SSH
- Docker and Docker Compose are installed on the VM
- The VM bootstrap steps in [vm_bootstrap.md](/home/angiod@usi.ch/maviedepoulpe/documentation/vm_bootstrap.md) are already done
- You have a GitHub repository with Actions enabled

The deploy workflow expects these files to already exist on the VM:

- `/opt/maviedepoulpe/.env`
- `/opt/maviedepoulpe/secrets/firebase-admin.prod.json`

And `/opt/maviedepoulpe/.env` should include (at minimum):

- distributed runtime flags (`USE_DISTRIBUTED_MATCH_RUNTIME=true`, `DISTRIBUTED_GATEWAY_RUN_BRIDGE=false`)
- Redis connection settings (`REDIS_URL`, optionally `REDIS_PASSWORD`)
- first admin email (`FIREBASE_PRIMARY_ADMIN_EMAIL=...`)

## 1. Understand Which Credentials Are Used Where

There are three different credential types involved:

1. GitHub Actions SSH key
   Used by GitHub Actions to connect to your VM over SSH
2. GHCR token
   Used by the VM to pull private container images from `ghcr.io`
3. Firebase credentials
   Used by the frontend build and backend runtime for Firebase

These are separate and should not be mixed together.

## 2. Create the SSH Key for GitHub Actions

Run this on your local machine:

```bash
ssh-keygen -t ed25519 -C "github-actions-maviedepoulpe" -f ./maviedepoulpe-actions
```

This creates:

- `maviedepoulpe-actions`
  This is the private key. Keep it private.
- `maviedepoulpe-actions.pub`
  This is the public key. Put this on the VM.

### 2.1 Put the public key on the VM

For an Oracle Ubuntu VM with user `ubuntu`, connect to the VM and append the public key to `authorized_keys`.

If you want to paste it manually:

```bash
ssh ubuntu@158.180.234.11
mkdir -p ~/.ssh
chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
```

Paste the full contents of `maviedepoulpe-actions.pub` as a new line, save, then run:

```bash
chmod 600 ~/.ssh/authorized_keys
```

If you prefer copying from your local machine:

```bash
scp ./maviedepoulpe-actions.pub ubuntu@158.180.234.11:/tmp/maviedepoulpe-actions.pub
ssh ubuntu@158.180.234.11
mkdir -p ~/.ssh
chmod 700 ~/.ssh
cat /tmp/maviedepoulpe-actions.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
rm /tmp/maviedepoulpe-actions.pub
```

### 2.2 Test the SSH key from your local machine

Run:

```bash
ssh -i ./maviedepoulpe-actions ubuntu@158.180.234.11
```

If this works without prompting for a password, the key is installed correctly.

### 2.3 Put the private key into a GitHub Actions secret

Open the private key file locally:

```bash
cat ./maviedepoulpe-actions
```

Copy the entire file contents, including:

- `-----BEGIN OPENSSH PRIVATE KEY-----`
- `-----END OPENSSH PRIVATE KEY-----`

You will store this entire text in the GitHub secret `VM_SSH_PRIVATE_KEY`.

Do not copy the `.pub` file into `VM_SSH_PRIVATE_KEY`.

For the actual preview/production workflows, use the environment-specific
secret names listed later in this guide:

- `PREVIEW_VM_SSH_PRIVATE_KEY`
- `PROD_VM_SSH_PRIVATE_KEY`

Do not put this OpenSSH private key in `.env`, in `firebase-admin.dev.json`, or
on the VM. The VM receives only the matching public key in
`~/.ssh/authorized_keys`.

This SSH private key is unrelated to the Firebase Admin service-account
`private_key`. The Firebase key stays inside
`secrets/firebase-admin.dev.json` locally or
`/opt/maviedepoulpe/secrets/firebase-admin.prod.json` on the VM.

## 3. Collect the VM SSH Host Fingerprint

From your local machine, run:

```bash
ssh-keyscan -t ed25519 158.180.234.11 2>/dev/null | ssh-keygen -lf - -E sha256
```

Example output:

```text
256 SHA256:C+5XsO3AlWTGgcdEN7kK1wbzAUp/Dbgbo1z4p+XaxdM 158.180.234.11 (ED25519)
```

For the GitHub secret, store only the fingerprint value:

```text
SHA256:C+5XsO3AlWTGgcdEN7kK1wbzAUp/Dbgbo1z4p+XaxdM
```

Do not include:

- `256`
- the IP address
- `(ED25519)`

### 3.1 If GitHub Actions still says fingerprint mismatch

Some SSH clients and actions do not always validate against the same host key type.

Your server may expose multiple host keys, for example:

- RSA
- ECDSA
- ED25519

To list all host key fingerprints from your local machine:

```bash
ssh-keyscan 158.180.234.11 2>/dev/null | ssh-keygen -lf - -E sha256
```

Example output:

```text
3072 SHA256:ZGyH9AU7FyK+cusO3N5RKGC6TDUGBxGSa/LFEGDKHtg 158.180.234.11 (RSA)
256 SHA256:c9YRjYXZRgvczawoNU67hOHrke8d6kqNmPHHLbbw1to 158.180.234.11 (ECDSA)
256 SHA256:C+5XsO3AlWTGgcdEN7kK1wbzAUp/Dbgbo1z4p+XaxdM 158.180.234.11 (ED25519)
```

To verify directly on the VM:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub -E sha256
sudo ssh-keygen -lf /etc/ssh/ssh_host_ecdsa_key.pub -E sha256
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

If the GitHub Actions SSH or SCP step still fails with:

```text
ssh: handshake failed: ssh: host key fingerprint mismatch
```

then try this:

1. First use the ED25519 fingerprint in `VM_SSH_FINGERPRINT`
2. If it still fails, try the RSA fingerprint instead
3. If it still fails, try the ECDSA fingerprint

Store only the `SHA256:...` value each time.

This workaround is useful because the `appleboy/scp-action` and `appleboy/ssh-action` steps may validate against a different negotiated host key algorithm than the one you first checked manually.

## 4. Create the GHCR Token Used by the VM

The workflow pushes images to GHCR during the build job using the built-in `GITHUB_TOKEN`.

That token is only for the GitHub Actions runner. Your VM cannot use it directly.

Because your repository is private, the VM needs its own GitHub credentials so it can run:

```bash
docker login ghcr.io
docker pull ghcr.io/<owner>/maviedepoulpe-backend:latest
docker pull ghcr.io/<owner>/maviedepoulpe-frontend:latest
```

### 4.1 Choose the GitHub account that the VM will use

Pick one:

- your own GitHub account
- a dedicated machine account

That account must be able to read the private packages for this repository.

### 4.2 Create the token on GitHub

While logged into GitHub as that account:

1. Open `Settings`
2. Open `Developer settings`
3. Open `Personal access tokens`
4. Open `Tokens (classic)`
5. Click `Generate new token (classic)`
6. Give it a name such as `maviedepoulpe-ghcr-read`
7. Set an expiration
8. Enable this scope:
   - `read:packages`
9. Generate the token
10. Copy it immediately

Important:

- This token is for the VM to pull images, not for GitHub Actions to push images.
- If your repository is in a GitHub organization with SSO enabled, authorize the token for that organization too.

### 4.3 Store the GHCR credentials in GitHub Actions secrets

In your repository, open:

`Settings -> Secrets and variables -> Actions`

Create:

- `PREVIEW_GHCR_USERNAME`
  The GitHub username that owns the token
- `PREVIEW_GHCR_TOKEN`
  The Personal Access Token value

## 5. Add All Repository Secrets

In GitHub, open:

`Settings -> Secrets and variables -> Actions`

Create these secrets for preview deploy:

- `PREVIEW_VM_HOST`
- `PREVIEW_VM_SSH_PORT`
- `PREVIEW_VM_USER`
- `PREVIEW_VM_SSH_PRIVATE_KEY`
- `PREVIEW_VM_SSH_FINGERPRINT`
- `PREVIEW_GHCR_USERNAME`
- `PREVIEW_GHCR_TOKEN`
- `PREVIEW_VITE_API_URL`
- `PREVIEW_VITE_WS_URL`
- `PREVIEW_VITE_FIREBASE_API_KEY`
- `PREVIEW_VITE_FIREBASE_AUTH_DOMAIN`
- `PREVIEW_VITE_FIREBASE_PROJECT_ID`
- `PREVIEW_VITE_FIREBASE_APP_ID`
- `PREVIEW_VITE_FIREBASE_MESSAGING_SENDER_ID`
- `PREVIEW_VITE_FIREBASE_STORAGE_BUCKET`

Create these secrets for production deploy:

- `PROD_VM_HOST`
- `PROD_VM_SSH_PORT`
- `PROD_VM_USER`
- `PROD_VM_SSH_PRIVATE_KEY`
- `PROD_VM_SSH_FINGERPRINT`
- `PROD_GHCR_USERNAME`
- `PROD_GHCR_TOKEN`
- `PROD_VITE_API_URL`
- `PROD_VITE_WS_URL`
- `PROD_VITE_FIREBASE_API_KEY`
- `PROD_VITE_FIREBASE_AUTH_DOMAIN`
- `PROD_VITE_FIREBASE_PROJECT_ID`
- `PROD_VITE_FIREBASE_APP_ID`
- `PROD_VITE_FIREBASE_MESSAGING_SENDER_ID`
- `PROD_VITE_FIREBASE_STORAGE_BUCKET`

Recommended preview values for your current VM:

- `PREVIEW_VM_HOST` = `178.105.53.1`
- `PREVIEW_VM_SSH_PORT` = `22`
- `PREVIEW_VM_USER` = `root`
- `PREVIEW_VM_SSH_PRIVATE_KEY` = full contents of `maviedepoulpe-actions`
- `PREVIEW_VM_SSH_FINGERPRINT` = only the `SHA256:...` part from the fingerprint command

Notes:

- `PROD_VITE_API_URL` can be left blank if production should use same-origin `/api`
- `PROD_VITE_WS_URL` can be left blank if production should use same-origin `/ws`

## 6. Fill the Firebase Frontend Secrets Correctly

These values are not taken from your Firebase Admin service-account JSON.

They are the Firebase Web SDK config used by the frontend build.

Get them from Firebase Console:

1. Open your Firebase project
2. Open `Project settings`
3. Stay on `General`
4. Scroll to `Your apps`
5. Open the Web app, or create one using the `</>` button if you do not have one yet
6. In `SDK setup and configuration`, read the `firebaseConfig`

Map the values like this (for both `PREVIEW_VITE_*` and `PROD_VITE_*`):

- `PROD_VITE_FIREBASE_API_KEY` = `apiKey`
- `PROD_VITE_FIREBASE_AUTH_DOMAIN` = `authDomain`
- `PROD_VITE_FIREBASE_PROJECT_ID` = `projectId`
- `PROD_VITE_FIREBASE_APP_ID` = `appId`
- `PROD_VITE_FIREBASE_MESSAGING_SENDER_ID` = `messagingSenderId`
- `PROD_VITE_FIREBASE_STORAGE_BUCKET` = `storageBucket`

Example:

```js
const firebaseConfig = {
  apiKey: "AIza...",
  authDomain: "your-project.firebaseapp.com",
  projectId: "your-project",
  storageBucket: "your-project.firebasestorage.app",
  messagingSenderId: "123456789",
  appId: "1:123456789:web:abcdef",
};
```

Important:

- Do not copy these values from `firebase-admin.prod.json`
- `projectId` may match the admin JSON `project_id`
- the other frontend values come from the Firebase Web app settings, not the Admin SDK key

## 7. Understand Private GHCR Package Access

The workflow pushes images to:

```text
ghcr.io/<lowercase-github-owner>/maviedepoulpe-backend:latest
ghcr.io/<lowercase-github-owner>/maviedepoulpe-frontend:latest
```

For a private repository, the VM account in `GHCR_USERNAME` must be allowed to read those packages.

### 7.1 First push creates the packages

You may not see anything under GitHub Packages before the first successful workflow push.

That is normal.

### 7.2 Which registry to choose in GitHub Packages

If GitHub asks you which registry you want, choose:

- `Container registry`

That is the correct registry for Docker images stored in `ghcr.io`.

### 7.3 Verify package access after the first push

After the images have been pushed once:

1. Open GitHub
2. Open the package page for `maviedepoulpe-backend`
3. Open the package settings
4. Confirm one of these is true:
   - the package inherits permissions from this repository
   - the user in `GHCR_USERNAME` has explicit read access
5. Repeat for `maviedepoulpe-frontend`

## 8. Test GHCR Access Manually on the VM

Before you trust the workflow, SSH into the VM and test:

```bash
echo "<ghcr-token>" | docker login ghcr.io -u "<github-username>" --password-stdin
docker pull ghcr.io/<lowercase-github-owner>/maviedepoulpe-backend:latest
docker pull ghcr.io/<lowercase-github-owner>/maviedepoulpe-frontend:latest
```

If login fails, the token is wrong.

If login works but pull fails, the token owner probably does not have package access yet.

## 9. Trigger the First Deployment

After:

- the VM is bootstrapped
- the GitHub secrets are present
- the Firebase files are already on the VM
- the GHCR credentials work on the VM

You can trigger workflows in either way:

- Preview: push to `preview` or open `Actions -> Deploy Preview -> Run workflow`
- Production: push to `main` or open `Actions -> Deploy Production -> Run workflow`

## 10. What the Workflow Does with Those Secrets

Runtime behavior:

- Preview workflow:
  - uses `PREVIEW_VITE_*` build args
  - deploys with `PREVIEW_VM_*` + `PREVIEW_GHCR_*` secrets
- Production workflow:
  - uses `PROD_VITE_*` build args
  - deploys with `PROD_VM_*` + `PROD_GHCR_*` secrets

## 11. Common Mistakes

- putting the public key into `*_VM_SSH_PRIVATE_KEY`
- storing the whole fingerprint line instead of only the `SHA256:...` value
- trying to use Firebase Admin JSON values for `PROD_VITE_FIREBASE_*`
- forgetting that the VM needs its own GHCR login for private packages
- expecting GitHub Packages to exist before the first successful push
- using mixed-case GitHub owner names in GHCR image paths instead of lowercase
- trying CI deploy before a successful manual VM deploy
- not checking `backend-worker` logs after deploy when runtime is split

## 12. Workflow Assumptions

The deploy workflow assumes these files already exist on the VM:

- `/opt/maviedepoulpe/.env`
- `/opt/maviedepoulpe/secrets/firebase-admin.prod.json`

The VM-side setup for those files is documented in [vm_bootstrap.md](/home/angiod@usi.ch/AstraliaChronicles/documentation/vm_bootstrap.md).

## 13. CI troubleshooting

### Deploy step `Run Command Timeout`

- Confirm you are using the updated workflow with:
  - `command_timeout: 45m`
  - `docker compose pull backend frontend backend-worker`
- If network is slow, run one pull manually on VM, then re-run workflow.

### Workflow succeeds but app is not reachable

On VM:

```bash
cd /opt/maviedepoulpe
docker compose --env-file .env ps
docker compose --env-file .env logs --tail=200 caddy backend backend-worker frontend
```

Check:

- Caddy up and listening on `80/443`
- backend and backend-worker up (not restarting)
- no repeated runtime errors in worker logs
