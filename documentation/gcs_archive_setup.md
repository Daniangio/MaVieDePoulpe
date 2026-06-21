# GCS Replay Archive and Redis Chat

This document describes the current implementation for replay artifacts in Google Cloud Storage and global player chat over Redis Streams.

## Replay Storage Modes

- `local`: replay JSON files stay under `backend/data/replays`. This is the default for local development and simple test deployments.
- `gcs`: replay JSON files are gzip-compressed and uploaded to Google Cloud Storage. PostgreSQL stores only the replay artifact descriptor (`storage_kind`, `storage_key`, `frame_count`, `size_bytes`).

Enable GCS only when all required environment variables are configured:

```env
USE_OBJECT_STORAGE_REPLAYS=true
REPLAY_STORAGE_KIND=gcs
REPLAY_BUCKET=maviedepoulpe-replays-dev
REPLAY_EPHEMERAL_PREFIX=replays/ephemeral
REPLAY_PERMANENT_PREFIX=replays/permanent
GOOGLE_APPLICATION_CREDENTIALS=/opt/maviedepoulpe/secrets/gcp-service-account.dev.json
```

For local Docker development, the same credential path defaults to:

```env
GOOGLE_APPLICATION_CREDENTIALS=/workspaces/maviedepoulpe/secrets/gcp-service-account.dev.json
```

The repository expects local credentials in `secrets/gcp-service-account.dev.json`. Do not commit that file.

## GCS Provisioning

1. Create a Google Cloud project for the environment.
2. Create a Cloud Storage bucket:
   - Location type: `Region`
   - Storage class: `Standard`
   - Access: uniform bucket-level access
   - Public access: disabled
3. Create a service account for replay archiving.
4. Grant the service account `Storage Object Admin` for the replay bucket.
   - Object admin is needed because the backend uploads, reads, copies, and deletes replay objects.
5. Generate a JSON service account key and place it on the VM at:
   - `/opt/maviedepoulpe/secrets/gcp-service-account.dev.json`

## Prefix Convention

Replay objects use two storage prefixes:

- Ephemeral: `gs://<bucket>/replays/ephemeral/<game_id>.json.gz`
- Persistent: `gs://<bucket>/replays/permanent/<game_id>.json.gz`

Completed matches are stored in the ephemeral prefix by default. Persistent replays are created by server-side copying the object to the permanent prefix.

## Lifecycle Rule

Use Cloud Storage lifecycle management to delete only ephemeral replays. Example rule:

```json
{
  "lifecycle": {
    "rule": [
      {
        "action": { "type": "Delete" },
        "condition": {
          "age": 7,
          "matchesPrefix": ["replays/ephemeral/"]
        }
      }
    ]
  }
}
```

Do not delete the Redis replay stream until GCS upload and PostgreSQL artifact commit both succeed. The current archiver follows this order:

1. Read source replay artifact.
2. Upload or describe the replay artifact.
3. Commit the artifact row in PostgreSQL.
4. Delete Redis runtime state and, when configured, purge the source stream.

## Docker Configuration

`docker-compose.yml` and `deploy/docker-compose.yml` pass these replay variables to both `backend` and `backend-worker`. Production mounts `/opt/maviedepoulpe/secrets` read-only into the containers.

For VM deployment:

```bash
sudo mkdir -p /opt/maviedepoulpe/secrets
sudo cp gcp-service-account.dev.json /opt/maviedepoulpe/secrets/gcp-service-account.dev.json
sudo chmod 600 /opt/maviedepoulpe/secrets/gcp-service-account.dev.json
```

Then set the replay variables in `/opt/maviedepoulpe/.env`.

## Redis Chat

Chat uses the authenticated application WebSocket (`/ws`) and Redis Streams.

Environment:

```env
CHAT_STREAM_PREFIX=chat
CHAT_RETENTION_SECONDS=86400
CHAT_HISTORY_LIMIT=80
```

Key conventions:

- Channel registry: `chat:channels`
- Channel metadata: `chat:channel:<channel_id>`
- Group membership: `chat:members:<channel_id>`
- Per-user muted state: `chat:muted:<channel_id>`
- Message stream: `chat:stream:<channel_id>`

Channel IDs use:

- `global:global` for the default public channel.
- `global:<slug>` for admin-created public channels.
- `group:<uuid>` for player-created groups.
- `direct:<user_a>:<user_b>` for deterministic friend direct chats, with user ids sorted lexicographically.

On each message:

1. The gateway writes to `XADD chat:<chat_id> MINID ~ <now-minus-retention-ms> * ...`.
2. The gateway refreshes `EXPIRE chat:<chat_id> <CHAT_RETENTION_SECONDS>`.
3. Online users receive a `chat_message` WebSocket event through the existing Redis-backed connection manager.

When the chat panel opens, the client requests recent history with `request_chat_history`.

Supported WebSocket actions:

- `request_chat_channels`
- `request_chat_history`
- `send_chat_message`
- `create_chat_channel`
- `remove_chat_channel`
- `leave_chat_channel`
- `set_chat_muted`
- `add_chat_members`
- `kick_chat_member`
- `start_direct_chat`

Admins can create and remove additional global channels and can set their retention window. Everyone belongs to global channels unless an admin explicitly excludes them; non-admin users can only mute/unmute global channels. Admins can kick or reintegrate users in global channels.

Players can create custom groups, invite friends, mute/unmute groups, leave groups, and disband groups they created. User-created groups always use the default retention window. Direct chats are friend-only and are created with `start_direct_chat`.

## Current Limitations

- Chat is ephemeral and stored in Redis, not PostgreSQL.
- Group membership is stored in Redis. If Redis data is cleared, custom groups disappear.
- Group creation and direct chat use friend suggestions from the existing friends API.
- Replay sharing currently uses existing match/replay URLs. Public redacted replay artifacts and share-token routing are not implemented yet.
- GCS replay promotion is implemented in storage code, but user-facing "save replay permanently" flows still need endpoint/UI integration if desired.
