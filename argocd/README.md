# Argo CD wiring for offroad-scraper

The `application.yaml` in this directory is a single-source `Application` that
points straight at the Helm chart in this repo (`charts/offroad-scraper`).

## Pointing at a branch during testing

Change `spec.source.targetRevision` to your branch name:

```yaml
spec:
  source:
    targetRevision: feat-ics-calendar   # or any other branch/tag/commit
```

The `path` stays `charts/offroad-scraper`.

## App-of-apps

If you manage everything through an app-of-apps pattern (a root `Application`
that generates child `Application` CRs from a directory), add this file (or a
copy of it) to your app-of-apps directory. The only thing to be careful about is
the `metadata.namespace` — the child `Application` must be created in the
namespace where Argo CD itself runs (usually `argocd`).

## Multi-source `$values` pattern

You use a separate `k8s-at-home` repo with a `helm-vars/` directory holding the
per-environment values (including secrets). To keep chart updates decoupled from
your environment values, switch this `Application` to a multi-source layout:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: offroad-scraper
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  sources:
    # Source 1: the chart (from this repo)
    - repoURL: https://github.com/Kapel/offroad-scraper.git
      targetRevision: main            # or a branch while testing
      path: charts/offroad-scraper
      helm:
        valueFiles:
          - $values/helm-vars/offroad-scraper.yaml
          # - $values/helm-vars/offroad-scraper-secrets.yaml
    # Source 2: your values repo, referenced as "$values"
    - repoURL: https://github.com/<you>/k8s-at-home.git
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: offroad-scraper
  syncPolicy:
    automated:
      selfHeal: true
      prune: false
    syncOptions:
      - CreateNamespace=true
```

Key points:

- The second source is referenced by the `ref: values` field, so the chart
  source can use `$values/helm-vars/...` paths in `helm.valueFiles`.
- Put non-secret config in `helm-vars/offroad-scraper.yaml` (sites, schedule,
  ingress host, resources).
- Put secrets in a separate `helm-vars/offroad-scraper-secrets.yaml` that you can
  encrypt (e.g. SOPS/age) or keep out of git entirely. For secrets, prefer one
  of the chart's `secret.mode` options:
  - `values` — render a Secret directly from the values file (simplest, but the
    values file then contains plaintext secrets), or
  - `external` — render an ExternalSecret backed by your SecretStore
    (Vault/AWS SM/etc.), which keeps plaintext out of git entirely.

## Secret strategies

| `secret.mode` | What it does | When to use |
| --- | --- | --- |
| `values` | Renders a Secret from `secret.values` | Quick home-lab / non-sensitive |
| `existing` | References a pre-created Secret `secret.existing.name` | GitOps-safe: you create the Secret out-of-band (sealed-secrets, manual `kubectl`, etc.) |
| `external` | Renders an ExternalSecret from `secret.external` | Secret managed by the external-secrets operator |

For a GitOps-friendly home setup, `existing` (with SealedSecret) or `external`
(with the external-secrets operator) are recommended.
