# offroad-scraper

Scrapes event/calendar pages for offroad events, uses DeepSeek to extract
structured trip data, and publishes the results as a private ICS calendar feed.

## What it does

- **`scrape`** — a one-shot batch job that reads the sites list from
  `/config/sites.yaml`, fetches each site, extracts events via the DeepSeek API,
  and writes state (`trips.json` + `trips.ics`) to `/data`.
- **`serve`** — an HTTP server that serves the generated calendar (`/trips.ics`)
  and related endpoints (`/ics`, `/healthz`) from `/data`, protected by Basic
  Auth and an allow-list of emails.

## Architecture

The Helm chart deploys two workloads that share the same data:

```
                 ┌───────────────────────────────────────────┐
                 │                   PVC (/data)             │
                 │            trips.json + trips.ics         │
                 └────────────────┬──────────────────────────┘
                                  │
   ┌──────────────────┐           │          ┌───────────────────┐
   │ CronJob "scrape" │───────────┴──────────│ Deployment "serve" │
   │  python -m       │  writes              │  python -m         │
   │  offroad_scraper │  state               │  offroad_scraper   │
   │  scrape          │                      │  serve (HTTP 8080) │
   └──────────────────┘                      └─────────┬─────────┘
                                                       │
                                                 Ingress (nginx)
                                                 /trips.ics /ics
```

- The `scrape` CronJob runs on a schedule (default every 6 hours) and refreshes
  the state.
- The `serve` Deployment (replicaCount 1) serves the calendar over HTTP. It is a
  single replica because both workloads share a `ReadWriteOnce` PVC.
- Both workloads mount the same PVC at `/data`. Only the `scrape` workload mounts
  the sites ConfigMap (`/config/sites.yaml`) and receives the `DEEPSEEK_API_KEY`
  secret; only the `serve` workload receives the auth secrets
  (`ICS_AUTH_PASSWORD`, `SUBSCRIPTION_TOKEN`) and `ALLOWED_EMAILS` — least
  privilege per process.

## Configuring sites

Sites are configured via `values.sites` (rendered into a ConfigMap as a `sites:`
YAML mapping):

```yaml
sites:
  - name: My Offroad Park
    url: https://example.com/events
    note: optional note
  - name: Some Club
    url: https://example.org/calendar
```

See `config/sites.example.yaml` for the file format. The scraper reads
`SITES_FILE` (default `/config/sites.yaml`).

## Setting secrets

The chart supports three secret modes via `secret.mode`:

### 1. `values` (render a Secret from values)

```yaml
secret:
  mode: values
  values:
    deepseekApiKey: sk-...
    icsAuthPassword: "super-secret"
    subscriptionToken: "optional-random-token"
```

Renders a Secret `<fullname>-secret` with keys `DEEPSEEK_API_KEY`,
`ICS_AUTH_PASSWORD`, and `SUBSCRIPTION_TOKEN`. Simplest, but the plaintext lives
in your values file.

### 2. `existing` (reference a pre-created Secret)

```yaml
secret:
  mode: existing
  existing:
    name: my-offroad-secret
```

Create the Secret out-of-band (e.g. a SealedSecret or manual `kubectl create
secret`) with keys `DEEPSEEK_API_KEY`, `ICS_AUTH_PASSWORD` (and optionally
`SUBSCRIPTION_TOKEN`), and point the chart at it.

### 3. `external` (ExternalSecret via external-secrets operator)

```yaml
secret:
  mode: external
  external:
    enabled: true
    secretStoreRef:
      name: vault-backend
      kind: ClusterSecretStore
    refreshInterval: 1h
    remoteRefs:
      DEEPSEEK_API_KEY:
        key: kv/offroad-scraper
        property: deepseek_api_key
      ICS_AUTH_PASSWORD:
        key: kv/offroad-scraper
        property: ics_auth_password
      SUBSCRIPTION_TOKEN:
        key: kv/offroad-scraper
        property: subscription_token
```

Renders an ExternalSecret targeting `<fullname>-secret`. Keep plaintext in your
SecretStore and out of git.

## Deploying

### With Helm

```bash
helm upgrade --install offroad-scraper charts/offroad-scraper \
  --namespace offroad-scraper --create-namespace \
  --set secret.mode=values \
  --set secret.values.deepseekApiKey=sk-... \
  --set ingress.host=cal.example.com \
  --set-file 'sites[0]'=... # or pass -f values.yaml
```

### With Argo CD

See `argocd/application.yaml` and `argocd/README.md`. Point it at this repo
(path `charts/offroad-scraper`) or wire it into your app-of-apps / `$values`
values-repo pattern.

## Subscribing

- **Apple Calendar** — add a "Subscription calendar" pointing at
  `https://<ingress.host>/trips.ics`. Apple honors Basic Auth on subscription
  URLs if you embed credentials (`https://user:pass@host/trips.ics`), though the
  chart uses the shared password for all subscribers.
- **Google Calendar** — add `https://<ingress.host>/trips.ics` via
  *Settings → Add calendar → From URL*. Caveat: Google cannot refresh a URL
  that requires authentication, so an authenticated URL (Basic Auth or token)
  will not auto-update. For Google, use the `SUBSCRIPTION_TOKEN` route: the app
  exposes a token-based URL (`/ics/<SUBSCRIPTION_TOKEN>`) that Google can fetch
  without auth, and you can rotate the token to revoke access.

## Security posture (OWASP mitigations)

- **Non-root container**: runs as uid/gid 1000 (`runAsNonRoot: true`).
- **Read-only root filesystem** with writable `/data` (PVC) and `/tmp`
  (emptyDir) — `readOnlyRootFilesystem: true`.
- **Drop all capabilities** (`capabilities.drop: [ALL]`), `allowPrivilegeEscalation: false`.
- **Seccomp** `RuntimeDefault` at the pod level.
- **Least-privilege networking**: optional `NetworkPolicy` (default-deny) that
  allows only ingress from the ingress controller and egress DNS (53) + HTTPS
  (443). Enable via `networkPolicy.enabled: true`.
- **Secrets out of the image**: `DEEPSEEK_API_KEY`, `ICS_AUTH_PASSWORD`, and
  `SUBSCRIPTION_TOKEN` come from a Secret / ExternalSecret, never baked into the
  image.
- **SSRF / scraping hardening**: `SCRAPE_TIMEOUT_SECONDS` and `SCRAPE_MAX_BYTES`
  bound outbound requests; `SCRAPE_USER_AGENT` identifies the scraper.
- **AuthN/AuthZ on the feed**: Basic Auth (`ICS_AUTH_PASSWORD`) plus an email
  allow-list (`ALLOWED_EMAILS`, comma-joined).
- **Pinned image tag** (semver, not `latest`) and pinned GitHub Action versions.
- **CI scans**: `bandit`, `pip-audit`, and `trivy` (CRITICAL/HIGH gate) run on
  every PR.
