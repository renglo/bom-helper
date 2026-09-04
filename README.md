# bom-helper

Shared deploy runtime for every tenant `*-bom` repository (stanley-bom, apollo-bom, …).

Tenant BOM repos keep **pins only** (`bom/`, `handlers_bom/`, `deploy_targets.yml`).
This repo owns the scripts, Dockerfile, and the GitHub Action that wires them into CI.

## What stays where

| Repo | Contents |
|------|----------|
| **`*-bom`** | `bom/*.json`, `handlers_bom/*.json`, `deploy_targets.yml`, thin workflows |
| **`bom-helper`** | `scripts/`, `tests/`, `Dockerfile`, `.github/actions/use-helper` |

`git convoy adopt --bom ops/<system>-bom` is unchanged: it still only edits pins and
`deploy_targets.yml`. You commit and push the `*-bom` repo; CI deploys.

## Pin from a tenant BOM

In `deploy_targets.yml`:

```yaml
helper:
  repository: renglo/bom-helper
  ref: main          # pin a tag (e.g. v0.1.0) once you cut releases

# Optional: foreign CodeArtifact publishers (omit for same-account only)
# registries:
#   - domain: contoso
#     domain_owner: "111122223333"
#     npm_scopes: ["@contoso"]
```

Each tenant `*-bom` vendors a thin local action
(`.github/actions/setup-bom-helper`) that **checkouts** this repo (private
repos cannot be loaded with `uses: renglo/bom-helper/...` — GitHub reports
“repository not found”).

```yaml
- uses: actions/checkout@v4
- uses: ./.github/actions/setup-bom-helper
```

That action reads `helper.*`, clones this repo into `.bom-helper/`, and
**copies** `scripts/` + `Dockerfile` into the workspace (not symlinks — Docker
BuildKit cannot reliably `COPY` through directory symlinks).

If the clone step fails on a private org repo, grant the `*-bom` workflow
access to `bom-helper` (org **Actions** settings → access to repositories),
or pass a PAT via `token: ${{ secrets.BOM_HELPER_TOKEN }}`.

Bump `helper.ref` (and push the `*-bom`) to pick up script changes. Editing
this repo alone does not redeploy tenants.

## Local use

From a Stanley-style workspace where this checkout sits next to the tenant BOM:

```bash
cd ops/stanley-bom
python3 ../bom-helper/scripts/bom_manifest.py --plan --pipeline backend bom/v0.1.10.json
```

Or symlink once:

```bash
ln -sfn ../bom-helper/scripts scripts
ln -sfn ../bom-helper/Dockerfile Dockerfile
```

## Tests

```bash
python3 -m pip install pyyaml
python3 -m pytest tests/
```

## New tenant BOM

Copy [`ops/example-bom`](../example-bom) (or the `example-bom` GitHub template) and
fill in `deploy_targets.yml` + the first `bom/v0.1.0.json`.
