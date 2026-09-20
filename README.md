# bom-helper

Shared deploy runtime for every tenant `*-bom` repository (example-bom, apollo-bom, …).

Tenant BOM repos keep **pins + placement** (`bom/` hub, `console_bom/`, `peers_bom/` per peer, `deploy_targets.yml` `hub:` / `peers:`).
This repo owns the scripts, Dockerfile, **peer CDK/packager**, and the GitHub Action that wires them into CI.

Peer vocabulary, add-peer, grouping, and MCP: [docs/PEERS.md](docs/PEERS.md).
Extensions CLI: [docs/EXTENSIONS.md](docs/EXTENSIONS.md) (`bash setup-venv.sh && source bom-venv/bin/activate && extensions help`).
Overflow teardown after smoke: [docs/OVERFLOW_TEARDOWN.md](docs/OVERFLOW_TEARDOWN.md).

## What stays where

| Repo | Contents |
|------|----------|
| **`*-bom`** | `bom/` (hub), `console_bom/`, `peers_bom/<peerId>/`, `handlers_bom/` (overflow), `deploy_targets.yml` |
| **`bom-helper`** | `scripts/` (`generate_bom.py`, `bom_layout.py`), `cdk/`, `tests/`, `Dockerfile` |

`git convoy adopt --bom ops/<system>-bom` fills pins from the train and writes **three BOM trees** (hub, console, peers) from `deploy_targets.yml` placement. Regenerate manually with `python scripts/generate_bom.py ../<tenant>-bom --version X.Y.Z`.

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
**copies** `scripts/` + `cdk/` + `Dockerfile` into the workspace (not symlinks — Docker
BuildKit cannot reliably `COPY` through directory symlinks).

If the clone step fails on a private org repo, grant the `*-bom` workflow
access to `bom-helper` (org **Actions** settings → access to repositories),
or pass a PAT via `token: ${{ secrets.BOM_HELPER_TOKEN }}`.

Bump `helper.ref` (and push the `*-bom`) to pick up script changes. Editing
this repo alone does not redeploy tenants.

## Local use

From a workspace where this checkout sits next to the tenant BOM:

```bash
cd ops/example-bom
python3 ../bom-helper/scripts/bom_manifest.py --plan --pipeline backend bom/v0.1.10.json
```

### Peer CDK (first-time stack provision)

Peer stacks are **not** deployed by `deploy_peers.yml` CI — that workflow publishes zip/ECS
artifacts into stacks that already exist. One-time (or compute-shape) CDK uses a local venv,
same pattern as bootstrap and publisher:

```bash
cd ops/bom-helper
bash setup-venv.sh

export ENV=<env_id>
export AWS_PROFILE=<aws_profile>
export PEER_ID=<peer_id>

bash scripts/deploy_peer_cdk.sh synth --peer-id "$PEER_ID"
bash scripts/deploy_peer_cdk.sh deploy --peer-id "$PEER_ID"
```

Requires the **CDK CLI** on your PATH (`npm install -g aws-cdk`). See [docs/PEERS.md](docs/PEERS.md).

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
