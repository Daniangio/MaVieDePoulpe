# Complete Deployment Guide: Windows & Oracle Linux 9

## Step 1: Collect the VM SSH Host Fingerprint on Windows

Because you are using PowerShell, you must drop the Linux syntax. Run this exact command in your Windows PowerShell terminal:

```powershell
ssh-keyscan 80.225.87.140 | ssh-keygen -lf - -E sha256

```

**Expected Output:**

```text
256 SHA256:C+5XsO3AlWTGgcdEN7kK1wbzAUp/Dbgbo1z4p+XaxdM 80.225.87.140 (ED25519)

```

*Note down only the middle value starting with `SHA256:...` (e.g., `SHA256:C+5XsO3AlWTGgcdEN7kK1wbzAUp/Dbgbo1z4p+XaxdM`). You will need this for your GitHub secrets.*

---

## Step 2: Generate the GitHub Actions Deployment Key Pair

Run this in your local Windows terminal to generate a secure dedicated key pair for GitHub Actions to access your VM:

```powershell
ssh-keygen -t ed25519 -C "github-actions-maviedepoulpe" -f .\maviedepoulpe-actions

```

This generates two files in your current directory:

* `maviedepoulpe-actions` (The private key text block)
* `maviedepoulpe-actions.pub` (The public key text block)

### 2.1 Append the Public Key to the VM

Open your local `maviedepoulpe-actions.pub` file using Notepad, and copy its single line of text.

Now, SSH into your Oracle Linux VM using your *original* private key:

```bash
ssh -i /path/to/your/original_key opc@80.225.87.140

```

Once inside the VM, open your authorized keys file:

```bash
nano ~/.ssh/authorized_keys

```

Move your cursor to a brand new line at the bottom, paste the copied text from `maviedepoulpe-actions.pub`, save (`Ctrl+O`, `Enter`), and exit (`Ctrl+X`).

---

## Step 3: Configure Your OCI Host Environment

While still logged into your VM via SSH, let's create the environment directories and apply the swap file so that your containers don't crash when running on the 1 GB physical memory limits.

### 3.1 Setup Directories

```bash
sudo mkdir -p /opt/maviedepoulpe/secrets
sudo mkdir -p /opt/maviedepoulpe/data/maps /opt/maviedepoulpe/data/replays
sudo chown -R opc:opc /opt/maviedepoulpe

```

### 3.2 Create the Production `.env` File

Create a new configuration file on the VM:

```bash
nano /opt/maviedepoulpe/.env

```

Paste your runtime environment schema, matching your exact `daniangio` package routes:

```dotenv
APP_DOMAIN=yourdomain.com
POSTGRES_DB=maviedepoulpe
POSTGRES_USER=maviedepoulpe
POSTGRES_PASSWORD=UseALongSecurePasswordHere

BACKEND_IMAGE=ghcr.io/daniangio/maviedepoulpe-backend:latest
FRONTEND_IMAGE=ghcr.io/daniangio/maviedepoulpe-frontend:latest

FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_PRIMARY_ADMIN_EMAIL=admin@example.com
USE_DISTRIBUTED_MATCH_RUNTIME=true
DISTRIBUTED_GATEWAY_RUN_BRIDGE=false

USE_OBJECT_STORAGE_REPLAYS=false
REDIS_PASSWORD=UseALongSecurePasswordHere
REDIS_URL=redis://:UseALongSecurePasswordHere@redis:6379/0

```

Save and exit.

### 3.3 Add Firebase Secrets

Place your Firebase Admin SDK service account key configuration onto the VM:

```bash
nano /opt/maviedepoulpe/secrets/firebase-admin.prod.json

```

Paste your entire downloaded service account JSON block here, save, and exit. Then secure its permissions:

```bash
chmod 700 /opt/maviedepoulpe/secrets
chmod 600 /opt/maviedepoulpe/secrets/firebase-admin.prod.json

```

---

## Step 4: Generate your GitHub Personal Access Token (PAT)

Because your repository is private, your VM needs structural authorization parameters to talk to GHCR.

1. Go to your personal account settings on GitHub -> **Developer Settings** -> **Personal Access Tokens** -> **Tokens (classic)**.
2. Click **Generate new token (classic)**.
3. Select the `read:packages` scope checkbox.
4. Generate and save the token value securely.

Log back into your VM shell and authenticate your local Docker engine instance to the cloud package register manually once:

```bash
echo "YOUR_GENERATED_PAT_TOKEN" | docker login ghcr.io -u "daniangio" --password-stdin

```

---

## Step 5: Define Your GitHub Actions Secrets

Go to your repository on GitHub, then open **Settings** -> **Secrets and variables** -> **Actions** -> **Repository Secrets**. Click **New repository secret** for each of the keys listed below.

To prevent errors caused by the chicken-and-egg paradox where your VM pulls blank images, you must define **both** environment layers.

### Infrastructure Deployment Secrets

| Secret Key Name | Absolute Value to Enter |
| --- | --- |
| `PREVIEW_VM_HOST` | `80.225.87.140` |
| `PROD_VM_HOST` | `80.225.87.140` |
| `PREVIEW_VM_SSH_PORT` | `22` |
| `PROD_VM_SSH_PORT` | `22` |
| `PREVIEW_VM_USER` | `opc` |
| `PROD_VM_USER` | `opc` |
| `PREVIEW_VM_SSH_PRIVATE_KEY` | *Open your local `maviedepoulpe-actions` file and copy the entire text block.* |
| `PROD_VM_SSH_PRIVATE_KEY` | *Same private key text block as above.* |
| `PREVIEW_VM_SSH_FINGERPRINT` | `SHA256:...` *(The key string extracted in Step 1)* |
| `PROD_VM_SSH_FINGERPRINT` | `SHA256:...` *(The key string extracted in Step 1)* |
| `PREVIEW_GHCR_USERNAME` | `daniangio` |
| `PROD_GHCR_USERNAME` | `daniangio` |
| `PREVIEW_GHCR_TOKEN` | *The GitHub PAT Token created in Step 4.* |
| `PROD_GHCR_TOKEN` | *The GitHub PAT Token created in Step 4.* |

### Application Compilation Secrets (Firebase Config Setup)

These secrets are processed on GitHub's runners during compilation to build your static client bundle. Fetch these values directly from your Firebase Console -> Project Settings (Web App Config block):

* `PREVIEW_VITE_API_URL` / `PROD_VITE_API_URL` (Your API URL target or blank if same-origin)
* `PREVIEW_VITE_WS_URL` / `PROD_VITE_WS_URL` (Your WebSocket URL target or blank if same-origin)
* `PREVIEW_VITE_FIREBASE_API_KEY` & `PROD_VITE_FIREBASE_API_KEY`
* `PREVIEW_VITE_FIREBASE_AUTH_DOMAIN` & `PROD_VITE_FIREBASE_AUTH_DOMAIN`
* `PREVIEW_VITE_FIREBASE_PROJECT_ID` & `PROD_VITE_FIREBASE_PROJECT_ID`
* `PREVIEW_VITE_FIREBASE_APP_ID` & `PROD_VITE_FIREBASE_APP_ID`
* `PREVIEW_VITE_FIREBASE_MESSAGING_SENDER_ID` & `PROD_VITE_FIREBASE_MESSAGING_SENDER_ID`
* `PREVIEW_VITE_FIREBASE_STORAGE_BUCKET` & `PROD_VITE_FIREBASE_STORAGE_BUCKET`

---

## Step 6: First-Time Deployment Execution

Now that your environment configuration variables are ready:

1. Push your code infrastructure changes to your `preview` or `main` branch.
2. Go to your GitHub repository -> **Actions** tab.
3. Select the **Deploy Preview** or **Deploy Production** pipeline from the left list.
4. Click **Run workflow**.

GitHub will spin up its cloud runners, compile your Docker containers safely without using your VM's RAM, push the finished compilation layers to GHCR, connect to your VM via SSH, and execute your remote orchestration update cleanly!
