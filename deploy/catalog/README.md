# Streambase catalog on Cloud Run

This deployment is intentionally separate from the Streambase CRM. Its build
context contains only:

- the read-only catalog API and repository modules;
- a minimal SQLite snapshot with the exact catalog columns they read;
- the MP3/WAV files referenced by those catalog rows; and
- the catalog-only Python dependencies and Dockerfile.

It does not contain the CRM database, contacts, email tools, environment files,
or unrelated application source.

## Prepare a private source-deploy context

From the repository root, choose a new ignored output directory:

```bash
.venv/bin/python scripts/export_catalog_snapshot.py \
  --source-db local_data/streambase.sqlite \
  --audio-root data/audio_uploads \
  --output-dir catalog_build/streambase-catalog \
  --cloud-run-context
```

The command fails closed if a referenced file is missing, is a symlink, has an
unsafe name, or shares a case-insensitive filename with another song. It never
overwrites an existing output directory. Original audio filenames are not
deployed: the snapshot rewrites them to deterministic `song-<id>.<ext>` names.
Delete the generated context after a successful deployment; it is private even
though Git ignores it.

## Deploy

Create a long random bearer token outside the repository. Store only its
lowercase SHA-256 digest in the Cloud Run environment as
`STREAMBASE_CATALOG_TOKEN_SHA256`; store the raw token only in Showforge's
server-side secret store. Never pass the raw token in a command-line argument.

Create a dedicated runtime service account with no project roles. The catalog
container does not call Google Cloud APIs and must not run as the default
Compute Engine service account:

```bash
gcloud iam service-accounts create streambase-catalog-runtime \
  --project "<project-id>" \
  --display-name "Streambase catalog runtime"
```

Do not grant this service account any IAM roles. The identity running the
deployment only needs permission to act as it.

Create a separate build service account and grant only the predefined Cloud Run
builder role. This prevents the private build context from being handled by the
project's default Compute Engine service account:

```bash
gcloud iam service-accounts create streambase-catalog-builder \
  --project "<project-id>" \
  --display-name "Streambase catalog builder"

gcloud projects add-iam-policy-binding "<project-id>" \
  --member "serviceAccount:streambase-catalog-builder@<project-id>.iam.gserviceaccount.com" \
  --role "roles/run.builder"
```

The generated directory is a standard Cloud Run source context:

```bash
gcloud run deploy streambase-catalog \
  --project "<project-id>" \
  --source catalog_build/streambase-catalog \
  --region us-west1 \
  --service-account "streambase-catalog-runtime@<project-id>.iam.gserviceaccount.com" \
  --build-service-account "projects/<project-id>/serviceAccounts/streambase-catalog-builder@<project-id>.iam.gserviceaccount.com" \
  --allow-unauthenticated \
  --ingress all \
  --min-instances 0 \
  --max-instances 1 \
  --concurrency 4 \
  --timeout 300 \
  --set-env-vars STREAMBASE_CATALOG_TOKEN_SHA256="<lowercase-sha256-digest>"
```

Public invocation is required for Showforge to reach the service, but only
`GET /healthz` is unauthenticated. All catalog metadata and audio routes require
the bearer token and return private, non-cacheable responses.

After deployment, verify:

1. `/healthz` returns `{"ok":true}` without authentication. This is liveness
   only; it does not validate the database or bearer-token configuration.
2. `/v1/tracks` returns `401` without the token.
3. Authenticated `/v1/tracks?limit=1` succeeds, then authenticated pagination
   returns the expected track count.
4. Every advertised audio file passes authenticated `HEAD` and a small range
   request.
5. Showforge receives the Cloud Run HTTPS origin and raw token only through its
   server-side secrets.
