# Peers

A **Peer** is the service unit: own IAM, zip Lambda, optional ECS cluster, pin file, deploy cadence, optional region. An ECS **cluster** is only capacity *inside* a peer whose catalog `compute` is `fargate` or `ec2`. A `lambda_only` peer has no cluster.

The API (Stack A + Stack B) is the hub, not a peer. `renglo-api` maps **handle → peer**, then **light vs heavy** inside that peer (`heavy_handlers` → that peer’s zip vs that peer’s `run_task`).

Catalog and pin files live in the tenant `*-bom` repo. CDK and packager live in **bom-helper**. Peer rows stay in `deploy_targets.yml`; platform identity (`env_name`, BOM git id) is shared with bootstrap via `**launcher/cdk/customer-config.json`** — the same file Stack A/B already use.

### Placeholders in this doc

Example values use angle brackets — substitute your own; they are not literal ids:


| Placeholder     | Meaning                                                         |
| --------------- | --------------------------------------------------------------- |
| `<env_id>`      | AWS env prefix (`customer-config.json` `env_name`; shell `ENV`) |
| `<aws_profile>` | AWS CLI profile                                                 |
| `<tenant>`      | Key under `tenants:` in `deploy_targets.yml`                    |
| `<peer_id>`     | Key under `peers:` in `deploy_targets.yml`                      |
| `<handle>`      | Extension invoke handle (`peers.*.extensions`)                  |
| `<dist>`        | Python wheel name in a pin file (`python:` map)                 |
| `<handler>`     | Handler name in `handlers_config.json`                          |
| `<workspace>`   | Monorepo root containing `ops/`                                 |


## Workspace layout

Laptop workflows assume **bom-helper**, **launcher**, and `***-bom`** are **sibling folders** under the same parent (like bootstrap + launcher today):

```text
ops/
  bootstrap/
  launcher/            # cdk/customer-config.json  ← env_name, github_repo
  bom-helper/          # scripts/, cdk/, setup-venv.sh
  <tenant>-bom/        # deploy_targets.yml, peers_bom/, …
```

Peer CDK reads:


| Source                              | Supplies                                                                |
| ----------------------------------- | ----------------------------------------------------------------------- |
| `launcher/cdk/customer-config.json` | `env_name`, `github_repo` → BOM git id + sibling `<tenant>-bom/` folder |
| `*-bom/deploy_targets.yml`          | `tenants.*`, `peers.*` catalog                                          |


You do **not** put `bom_repo` in `deploy_targets.yml` (that file lives inside the BOM repo). You also do **not** re-type `github_repo` for peers — it is already in `customer-config.json`.

Override only when layout differs: `--context bom_checkout=…`, `targets=…`, or env `LAUNCHER_CUSTOMER_CONFIG=/path/to/customer-config.json`.

## Parameters (laptop)

Set once per shell session (same `ENV` as bootstrap):

```bash
export ENV=<env_id>                      # customer-config.json env_name
export AWS_PROFILE=<aws_profile>
export PEER_ID=<peer_id>                  # omit for all catalog peers
```

`bom_repo`, `tenant`, and `deploy_targets.yml` are read automatically from `launcher/cdk/customer-config.json` + sibling `*-bom/` inside `app.py`. You do not export them.


| Parameter     | Required | Notes                                                       |
| ------------- | -------- | ----------------------------------------------------------- |
| `ENV`         | yes      | AWS env prefix; same variable as bootstrap Stack A/B deploy |
| `AWS_PROFILE` | yes      | Account + region for CDK                                    |
| `PEER_ID`     | no       | One peer stack; omit for `--all`                            |


`deploy_targets.yml` still lists `tenants.<key>.aws_account` and `aws_region` for CI, ARN templates, and validation. Laptop CDK prefers the **profile** when both are present.

### AWS resource names

For tenant id `{env_id}` and peer id `{peer_id}`:


| Resource                 | Pattern                                                |
| ------------------------ | ------------------------------------------------------ |
| Stack / Lambda / cluster | `{env_id}-peer-{peer_id}`                          |
| ECS family / ECR         | `{env_id}-peer-{peer_id}-ecs`                      |
| OIDC role (staging)      | `GitHubActionsHandlersRole-{env_id}-{peer_id}-staging` |


## Where configuration lives

Put each kind of change in exactly one place. If it is not in this table, it is not peer config.


| What you are changing                                     | File (tenant `*-bom` unless noted)                                                       | Field / command                                                                       |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Which peers exist, who they serve, compute shape          | `deploy_targets.yml`                                                                     | `peers.<id>`                                                                          |
| Python/library pins for **one** peer                      | `peers_bom/<id>/vX.Y.Z.json`                                                             | `python`, `repos`                                                                     |
| Overflow zip (dual-run only, all handles in one artifact) | `handlers_bom/vX.Y.Z.json`                                                               | leave until [OVERFLOW_TEARDOWN.md](OVERFLOW_TEARDOWN.md)                              |
| Which handlers are heavy vs light                         | `extensions/<handle>/package/handlers_config.json`                                       | `heavy_handlers` (legacy `ecs_handlers` still read)                                   |
| Membership list `EXTERNAL_HANDLERS`                       | **Do not hand-edit.** Union of `peers.*.extensions` (CI overlay `--targets`)             | `ops/bom-helper/scripts/peers.py`                                                     |
| Dual-run overlay (heavy handler names, FE URL)            | `platform_env.yml` → hub API Lambda env (not peer Lambdas)                               | `EXTERNAL_HANDLERS_HEAVY`, etc.                                                       |
| Handle → Lambda ARN / ECS cluster (runtime)               | SSM `/{env}/bootstrap/peer-routes` (not Lambda env, not platform-vars)                   | `python scripts/write_peer_routes.py …`                                               |
| Peer Lambda runtime env (tables, `WL_NAME`, secrets)      | SSM `/{env}/bootstrap/deploy-input` + packager                                           | `peer_packager.py publish --env-json`; tables are always `{env}_*`                    |
| Laptop routing                                            | `dev/renglo-api/env_config.py`                                                           | `EXTERNAL_HANDLERS_PEER_MAP`, `EXTERNAL_HANDLERS_PEER_ROUTING`                        |
| First-time AWS stack (IAM, Lambda seed, ECS)              | laptop / admin                                                                           | `bash setup-venv.sh`, then `cdk synth` + `cdk deploy` from `bom-helper/cdk` (see §1d) |
| Zip + ECS **image** after the stack exists                | GitHub Actions                                                                           | `.github/workflows/deploy_peers.yml`                                                  |
| Helper CDK/packager version                               | `deploy_targets.yml`                                                                     | `helper.ref`                                                                          |
| Tenant AWS account / region                               | `deploy_targets.yml`                                                                     | `tenants.<name>.aws_account`, `aws_region`                                            |
| Peer region override (optional)                           | `deploy_targets.yml`                                                                     | `peers.<id>.aws_region`                                                               |
| Stack A/B, Cognito, REST, websocket                       | launcher `customer-config.json`                                                          | **not** peers                                                                         |


### Catalog example

```yaml
peers:
  <peer_id_a>:
    compute: fargate
    task_size: medium
    extensions: [<handle_a>, <handle_b>]   # several handles on one peer is OK
    peers_bom: 0.1.0
  <peer_id_b>:
    compute: lambda_only
    extensions: [<handle_c>]
    peers_bom: 0.0.1
```

Default pin path is `peers_bom/<id>/`. Override only if you must: `bom_path: peers_bom/custom`. `handlers_bom:` on a peer row is a deprecated alias for `peers_bom:`.

Catalog `compute` values:

- `lambda_only` — zip Lambda only. No ECS, no handlers ECR, no results bucket.
- `fargate` — zip + Fargate cluster. Optional `task_size: small | medium | large`.
- `ec2` — zip + EC2 capacity. **Required:** `ec2_instance_type`, `ec2_min_instances`, `ec2_desired_instances`, `ec2_max_instances`.

Each extension handle may appear on **one** peer only.

---

## 1. Add a peer

Example: add `<peer_id>` serving handle `<handle>`, zip-only, on the same account/region as the tenant.

### 1a. Catalog — `<tenant>-bom/deploy_targets.yml`

Add a row under `peers:` (do not touch `tenants:` unless this is a new AWS account):

```yaml
peers:
  <peer_id>:
    compute: lambda_only
    extensions: [<handle>]
    peers_bom: 0.0.1
    # optional:
    # aws_region: eu-west-1
    # iam_profile: <peer_id>-restricted
    # bom_path: peers_bom/<peer_id>   # default; omit
```

For a Fargate peer with heavies, use `compute: fargate` and `task_size: medium` (or `small` / `large`). For EC2:

```yaml
  <peer_id>:
    compute: ec2
    extensions: [<handle>]
    peers_bom: 0.0.1
    ec2_instance_type: m5.large
    ec2_min_instances: 0
    ec2_desired_instances: 1
    ec2_max_instances: 2
```

### 1b. Pin file — `<tenant>-bom/peers_bom/<id>/vX.Y.Z.json`

Create `peers_bom/<peer_id>/v0.0.1.json`. Pin only the wheels **this peer serves** (one handle or several on the same peer):

```json
{
  "version": "v0.0.1",
  "description": "Peer <peer_id> (<handle>).",
  "deploy_stage": "staging",
  "python": {
    "renglo-lib": "0.0.4rc1",
    "renglo-gro": "0.0.4rc1",
    "<dist>": "0.0.1"
  },
  "repos": {}
}
```

`deploy_stage` chooses the GitHub Environment / OIDC role (`staging` vs `production`).

### 1c. Heavy vs light — extension package (only if this peer has heavies)

Edit `extensions/<handle>/package/handlers_config.json` in the **extension** repo (not the BOM):

```json
{
  "heavy_handlers": ["<heavy_handler>"],
  "handlers": {
    "<handler>": "<handle>.handlers.<handler>.<Class>",
    "<heavy_handler>": "<handle>.handlers.<heavy_handler>.<Class>"
  }
}
```

`lambda_only` peers cannot run `heavy_handlers`. Put those handles on a `fargate`/`ec2` peer, or keep them light.

### 1d. First provision — laptop / admin role

Peer OIDC does not exist until this stack exists. Uses the same `launcher/cdk/customer-config.json` as bootstrap (`env_name`, `github_repo`).

Async/heavy from the hub also needs Stack A `{env}_tt_policy`: `iam:PassRole` on `{env}-peer-*-ecs-execution` / `-ecs-task`, and S3 get/put on `{env}-peer-*-ecs-{account}`. That is a **launcher Stack A** deploy, not a peer stack update.

```bash
cd <workspace>/bom-helper
bash setup-venv.sh

export ENV=<env_id>
export AWS_PROFILE=<aws_profile>
export PEER_ID=<peer_id>
```

**Shortcut**:

```bash
bash scripts/deploy_peer_cdk.sh synth --peer-id "$PEER_ID"
bash scripts/deploy_peer_cdk.sh deploy --peer-id "$PEER_ID"
```

**Raw CDK** (`app.py` reads launcher + catalog; only pass `peer_id`):

Synth writes CloudFormation templates under `cdk/output/<peer_id>/`. Use the **same** `--output` path for synth and deploy.

```bash
cd <workspace>/bom-helper/cdk

cdk synth "${ENV}-peer-${PEER_ID}" \
  --app "../venv/bin/python app.py" \
  --output "../output/${PEER_ID}" \
  --profile "$AWS_PROFILE" \
  --context "peer_id=${PEER_ID}"

cdk deploy "${ENV}-peer-${PEER_ID}" \
  --app "../venv/bin/python app.py" \
  --output "../output/${PEER_ID}" \
  --require-approval never \
  --profile "$AWS_PROFILE" \
  --context "peer_id=${PEER_ID}"
```

Synth validates the template locally (same flags as deploy, minus `--require-approval`). Fix errors before deploy. Generated files are gitignored under `cdk/output/`.

One-time setup: `setup-venv.sh` creates `bom-helper/venv` with `aws-cdk-lib` (same pattern as bootstrap). Requires the **CDK CLI** on your PATH (`npm install -g aws-cdk`). Do not copy `venv/` from another machine.

Omit `--peer-id` / `peer_id` context to synth/deploy **every** catalog peer (`cdk synth --all` / `cdk deploy --all`, or `deploy_peer_cdk.sh` without `--peer-id`). Those use `cdk/output/_all/`.

### 1e. Package and route — `*-bom` CI

Commit `deploy_targets.yml` + `peers_bom/<peer_id>/` on the BOM repo `main` (or run **Deploy Peers**). Workflow: `.github/workflows/deploy_peers.yml`.

Manual, one peer:

- GitHub → Actions → **Deploy Peers** → `tenant=<tenant>`, `peer=<peer_id>`.

That job builds the zip (and ECS image when `compute` is not `lambda_only`), updates `{env_id}-peer-{peer_id}`, then writes SSM routes. Laptop equivalent after the stack exists:

```bash
cd ../<tenant>-bom
python ../bom-helper/scripts/write_peer_routes.py deploy_targets.yml \
  --env-name "$ENV" \
  --peer-id "$PEER_ID"
```

Region defaults to `us-east-1`; account is read from the active AWS profile when `--account` is omitted.

That writes SSM `/{env_id}/bootstrap/peer-routes`. Unmapped handles still use overflow `{env_id}-handlers`.

Laptop cutover for one handle (optional): `dev/renglo-api/env_config.py`

```python
EXTERNAL_HANDLERS = '<handle_a>,<handle_b>'
EXTERNAL_HANDLERS_PEER_ROUTING = 'on'
# JSON: handle → lambda_arn, ecs_cluster, ecs_task_definition, ecs_results_bucket, region
EXTERNAL_HANDLERS_PEER_MAP = '{"<handle>":{"lambda_arn":"arn:aws:lambda:…:function:<env_id>-peer-<peer_id>","region":"…"}}'
```

`EXTERNAL_HANDLERS_PEER_ROUTING = 'off'` forces overflow for every handle (rollback).

### 1f. Smoke

Call one **light** handler on the new handle. If the peer is `fargate`/`ec2`, also one name listed in `heavy_handlers`. Stack A/B are not redeployed.

Who mints which id on each hop: [GOLDEN_PATHS.md](GOLDEN_PATHS.md) (sync+light vs async+heavy).

Grouping later is the same catalog: several handles on one `extensions:` list, or split to a new peer. No `lambda_router` change.

---

## 2. Update code in a peer

This is a **pin bump** of that peer’s wheels. Do not resynth Stack A/B. Do not edit `customer-config.json`.

### 2a. Pin — `<tenant>-bom/peers_bom/<id>/vX.Y.Z.json`

Publish the extension wheel, then bump the pin in **that peer’s** BOM file. Example — bump only `<dist_a>`, leave `<dist_b>` unchanged:

```json
{
  "version": "v0.1.4",
  "deploy_stage": "staging",
  "python": {
    "renglo-lib": "0.0.4rc1",
    "renglo-gro": "0.0.4rc1",
    "<dist_a>": "0.0.7rc1",
    "<dist_b>": "0.0.6rc2"
  }
}
```

If you cut a new BOM version file, point the catalog at it:

```yaml
# deploy_targets.yml
peers:
  <peer_id>:
    peers_bom: 0.1.4    # → peers_bom/<peer_id>/v0.1.4.json
```

### 2b. Deploy

Push `peers_bom/` (and `deploy_targets.yml` if the version pointer moved) to `*-bom` `main`, or **workflow_dispatch** **Deploy Peers** with `peer=<peer_id>`.

Laptop equivalent (wheelhouse already prepared):

```bash
python ../bom-helper/scripts/peer_packager.py build \
  --env-name "$ENV" --peer-id "$PEER_ID" \
  --wheelhouse .handlers-build/wheelhouse \
  --assets .handlers-build/handlers-assets \
  --packages <dist_a>,<dist_b> \
  --out ".peer-build/${PEER_ID}"

python ../bom-helper/scripts/peer_packager.py publish \
  --env-name "$ENV" --peer-id "$PEER_ID" \
  --zip ".peer-build/${PEER_ID}/lambda_deployment.zip" \
  --env-json lambda_env_merge.json
```

Publish updates zip, sets Handler to `lambda_router.lambda_handler` (CDK seed is `index.handler` because inline ZipFile is always `index.py`), and applies filtered SSM deploy-input env. Table names and `WL_NAME` always come from `--env-name` (`{env}_entities`, `{env}_data`, …). Overflow identity keys (`LAMBDA_FUNCTION_NAME`, ECS cluster, …) are not copied onto the peer.

Add `--large` on `build` and `peer_packager.py push` when `compute` is `fargate` or `ec2`.

Changing **handler source** (`heavy_handlers`, new handler class) is in the extension package + a new wheel version, then this same pin bump. It is not a CDK change.

---

## 3. Modify the configuration of a peer

Infra vs runtime vs pins:


| Change                                                                     | Where                                                             | Then                                                                                                        |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `compute` (`lambda_only` ↔ `fargate`/`ec2`), `task_size`, EC2 instance/ASG | `deploy_targets.yml` `peers.<id>`                                 | CDK deploy **that** peer stack                                                                              |
| `extensions:` (move a handle onto this peer)                               | `deploy_targets.yml`                                              | Move the handle off the other peer first; `write_peer_routes.py`; maybe pin extra dist in `peers_bom/<id>/` |
| `aws_region`                                                               | `deploy_targets.yml` `peers.<id>.aws_region`                      | CDK deploy in that region (new stack); update routes                                                        |
| `iam_profile`                                                              | `deploy_targets.yml`                                              | CDK / IAM on **that** peer only (not overflow roles)                                                        |
| `peers_bom` version                                                        | `deploy_targets.yml` + new JSON under `peers_bom/<id>/`           | `deploy_peers.yml` (path 2)                                                                                 |
| Light vs heavy                                                             | `extensions/<handle>/package/handlers_config.json` `heavy_handlers` | New wheel + path 2. Peer must already have ECS if you add heavies                                           |
| Kill-switch / laptop map                                                   | `env_config.py` or SSM                                            | No stack change                                                                                             |
| `helper.ref`                                                               | `deploy_targets.yml`                                              | Next peer CI/CDK uses new bom-helper                                                                        |


### 3a. Compute or task size (CDK)

`lambda_only` → `fargate` is a **stack update**, not a pin bump:

```yaml
# deploy_targets.yml
peers:
  <peer_id>:
    compute: fargate          # was lambda_only
    task_size: medium
    extensions: [<handle>]
    peers_bom: 0.0.1
```

```bash
bash scripts/deploy_peer_cdk.sh synth --peer-id "$PEER_ID"
bash scripts/deploy_peer_cdk.sh deploy --peer-id "$PEER_ID"
```

CloudFormation adds cluster, ECR, task definition, results bucket, task role. Then `write_peer_routes.py` (so SSM gets `ecs_cluster` / bucket) and **Deploy Peers** with `--large`. Until that finishes, `heavy_handlers` on this peer fail (`run_task` has no cluster).

Going **down** (`fargate` → `lambda_only`) deletes ECS resources. Move or drop heavies in `handlers_config.json` first, ship that wheel, then CDK.

Fargate size only (`task_size: large`) or EC2 instance/ASG: same class — catalog edit + that peer’s CDK deploy, not an API stack deploy.

### 3b. Move a handle between peers

1. Remove the handle from the old peer’s `extensions:` and add it to the new peer’s list in `deploy_targets.yml`.
2. Put the dist pin on the **destination** `peers_bom/<id>/vX.Y.Z.json`; remove it from the source peer’s pin file if it should not stay in that zip.
3. Redeploy **both** peers’ packages (`deploy_peers.yml`, or dispatch twice).
4. `write_peer_routes.py` without `--peer-id` to rewrite the full map.

### 3c. Optional MCP / ALB

`run_task` peers stay invoke-only until **that** peer stack opts into a listener. Do not attach a shared listener to overflow `{env}-handlers`.

---

## 4. Remove a peer

Example: retire `<peer_id>` / `<handle>`.

1. **Stop routing** — remove `<handle>` from `peers.<peer_id>.extensions` (or delete the whole `<peer_id>:` row). Run:
  ```bash
   cd ../<tenant>-bom
   python ../bom-helper/scripts/write_peer_routes.py deploy_targets.yml \
     --env-name "$ENV"
  ```
   Confirm SSM `/{env_id}/bootstrap/peer-routes` has no `<handle>`. If anything still calls that handle, it must not be in `EXTERNAL_HANDLERS` (derived from remaining `extensions:`).
2. **Destroy the stack**:
  ```bash
   bash scripts/deploy_peer_cdk.sh destroy --peer-id "$PEER_ID"
  ```
   Stack `{env_id}-peer-<peer_id>` and its Lambda/ECS/ECR/IAM go away. Do **not** run [OVERFLOW_TEARDOWN.md](OVERFLOW_TEARDOWN.md) for this — that script targets `{env_id}-handlers` without a peer suffix.
3. **Git** — delete `peers.<peer_id>` from `deploy_targets.yml` (if still present) and delete `peers_bom/<peer_id>/`. Push the BOM repo.
4. **Laptop** — drop `<handle>` from `EXTERNAL_HANDLERS` / `EXTERNAL_HANDLERS_PEER_MAP` in `env_config.py` if you set them.

Do not leave an empty catalog row “for later”; a row without a stack makes CI assume `{env_id}-peer-<peer_id>` exists.

---

## Dual-run (overflow)

Until every handle in `EXTERNAL_HANDLERS` has a peer map entry and smoke is green, `{env_id}-handlers` (Stack B + `deploy_handlers.yml` + `handlers_bom/`) stays as fallback. Then execute [OVERFLOW_TEARDOWN.md](OVERFLOW_TEARDOWN.md) in the same cycle.

---

## Annex A — git-convoy and peer deploy

Authority: [`ops/git-convoy/cross-repo-feature-manual.md`](../../git-convoy/cross-repo-feature-manual.md) and [`ops/git-convoy/README.md`](../../git-convoy/README.md). This annex maps that process onto **peers** only.

### What git-convoy does for peers (and what it does not)

| Step | git-convoy? | What actually happens |
| --- | --- | --- |
| Edit extension handler / UI code | **Feature** on product repos (`extensions/<handle>/`, …) | `feature adopt` → `feature commit` → `feature prs` → merge to `develop` |
| Publish extension **wheels** to CodeArtifact | **Train** or **hotfix** (tags → CI) | `train tag-rc` / `train publish`, or `hotfix publish` on extension repos |
| Deploy **API / console / backend** (Stack A/B) | **Adopt** on `*-bom` `main` | `git convoy adopt --bom ops/<tenant>-bom` writes `bom/`, `console_bom/`, and `peers_bom/<id>/` |
| Pin wheels for a **peer** zip/ECS | **Adopt** (same train) | Placement in `deploy_targets.yml`; adopt regenerates `peers_bom/<peer_id>/` |
| Package zip + SSM routes | **BOM push** | Push `*-bom` `main` → **Deploy Peers** (or §1e laptop scripts) |
| First peer **IAM / Lambda / ECS stack** | **No** | Laptop `deploy_peer_cdk.sh` (§1d) — one-time or compute-shape changes |
| Change `bom-helper` / peer CDK | **Aux**, not feature | `git convoy aux …` — separate from product trains |

**Important:** `git convoy adopt` writes **hub** (`bom/`), **console** (`console_bom/`), and **peer** (`peers_bom/<id>/`) BOMs from one placement map (`hub.python`, `peers.<id>.python`). `deploy_targets.yml` `packages:` is slot metadata; placement lists use **python dist names**.

Never put `*-bom` on a feature, train, or hotfix branch. BOM pins land on **`main`**; that push triggers deploy CI.

### Repos involved


| Repo kind | Examples | Peer role |
| --- | --- | --- |
| **Product** | `extensions/<handle>/` | Source code; feature + train/hotfix publish wheels |
| **BOM** | `ops/<tenant>-bom` | `deploy_targets.yml` (placement + catalog), `bom/`, `console_bom/`, `peers_bom/<peer_id>/` |
| **Aux** | `bom-helper`, `launcher`, … | Tooling; bump `helper.ref` in `deploy_targets.yml` when aux ships |

Register the BOM in convoy (`gitconvoy.toml` with `role = "bom"`, then `git convoy init`). Adopt targets that checkout:

```bash
git convoy adopt --bom ops/<tenant>-bom
git convoy adopt --production --bom ops/<tenant>-bom   # cycle 4 only
```

### End-to-end: ship extension code to a peer

Assume the peer **stack already exists** (§1d). Order matters.

```text
1. Product repos     feature → develop → (train or hotfix) → tag → publish CI → wheels in CodeArtifact
2. deploy_targets    placement (`hub.python`, `peers.<id>.python`) + `packages:` slots — edit when membership changes
3. adopt             git convoy adopt --bom ops/<tenant>-bom  →  bom/, console_bom/, peers_bom/<id>/
4. *-bom main        commit + push  →  deploy.yml / deploy_console.yml / deploy_peers.yml
5. Smoke             light + one heavy handler on that peer (§1f)
```

**1 — Extension code (git-convoy feature path)**

Work on `develop`, then after edits:

```bash
git convoy feature adopt
git convoy feature commit --header "feat: …"
git convoy feature prs          # or --no-gh for compare URLs
# merge PRs in GitHub (lib → api → console/extensions order when core is touched)
git convoy feature close --yes
```

Only repos you changed get `feature/<name>`. Extension-only peer work usually touches `extensions/<handle>/` (and sometimes `renglo-lib` if shared).

**2 — Publish wheels**

On a **release train** (staging):

```bash
git convoy train tag-rc
git convoy train verify         # Full mode; optional --wait
```

On **production** after stabilization: `git convoy train publish` (cycle 4).

For an urgent **patch** without a train: `hotfix start` → commit → PRs → `hotfix publish` on the extension repos, then `hotfix adopt --bom ops/<tenant>-bom` (writes hub, console, and peer BOMs).

Confirm extension publish workflows succeeded (tag push → Actions green) before adopting registry versions. Do not invent unpublished versions.

**3 — Adopt (generates all BOM pin files)**

After the train (or hotfix) has published wheels, adopt fills **version pins** from the train into three trees. You do **not** hand-edit `python:` / `npm:` blocks in `bom/`, `console_bom/`, or `peers_bom/` for routine releases.

```bash
git convoy adopt --bom ops/<tenant>-bom
# cycle 4 production:
git convoy adopt --production --bom ops/<tenant>-bom
```

Adopt also updates `deploy_targets.yml` pointers: `bom:`, `console_bom:`, and each `peers.<id>.peers_bom:` (same semver by default).

**What you still edit manually in `deploy_targets.yml` (placement, not pins):**

| Edit | When |
| --- | --- |
| `packages:` | New extension slot (dist/npm/repo metadata for adopt) |
| `hub.python:` | Extension dist goes on/off the **hub** API image |
| `peers.<id>.python:` | Extension dist goes on/off that **peer** zip/ECS (include cross-deps, e.g. `renglo-gro` on `lab`) |
| `peers.<id>.extensions:` | Which **handles** route to that peer (invoke map) |
| `peers.<id>.compute`, `task_size`, … | Infra shape (then §1d CDK, not adopt) |

Adding a dist to `peers.lab.python` without adopt only changes **membership**; run adopt (or `python scripts/generate_bom.py …`) to refresh pin **versions**.

**Optional manual override:** Hub and peer can pin different versions of the same dist (e.g. stable `renglo-gro` on hub, rc on peer). Adopt sets one train version everywhere; edit `peers_bom/<id>/vX.Y.Z.json` after adopt if you need divergence, then push.

**4 — Deploy (BOM push)**

```bash
cd ops/<tenant>-bom
git add deploy_targets.yml bom/ console_bom/ peers_bom/
git commit -m "adopt: bump hub/console/peer pins"
git push origin main
```

Push triggers deploy CI by path:

| Workflow | Paths |
| --- | --- |
| `deploy.yml` | `bom/**` |
| `deploy_console.yml` | `console_bom/**` |
| `deploy_peers.yml` | `peers_bom/**`, `deploy_targets.yml` |

Or dispatch **Deploy Peers** with `peer=<peer_id>` without waiting for a full push.

Regenerate pin files locally (same rules as adopt split) without convoy:

```bash
cd ops/bom-helper/scripts
python generate_bom.py ../<tenant>-bom --version X.Y.Z
python generate_bom.py ../<tenant>-bom --version X.Y.Z --validate
```

### Three BOM surfaces (do not confuse them)


| File tree | Consumed by | Pins from adopt? |
| --- | --- | --- |
| `bom/vX.Y.Z.json` | Hub / API backend (`deploy.yml`) | **Yes** |
| `console_bom/vX.Y.Z.json` | Console / Amplify (`deploy_console.yml`) | **Yes** |
| `peers_bom/<peer_id>/vX.Y.Z.json` | Peer zip/ECS (`deploy_peers.yml`) | **Yes** |
| `handlers_bom/` | Overflow dual-run only | **No** (legacy; see OVERFLOW_TEARDOWN) |

`deploy_targets.yml` **`packages:`** — slot metadata (repo id → dist/npm) for adopt. **`hub.python`** / **`peers.*.python`** — placement (which dists land on which surface). **`peers.*.extensions`** — routing handles only (not BOM membership).

### Infra and catalog outside convoy

These stay in §1–§4 of this doc:

- **New peer row**, `compute`, `extensions:` moves → edit `deploy_targets.yml` on BOM `main` (not a feature branch on `*-bom`).
- **Peer CDK** (stack, ECS shape) → `deploy_peer_cdk.sh` on a laptop; not git-convoy.
- **Overflow teardown** → [OVERFLOW_TEARDOWN.md](OVERFLOW_TEARDOWN.md) after peer smoke.
- **Sync+light / async+heavy call paths** → [GOLDEN_PATHS.md](GOLDEN_PATHS.md).

### Quick reference


| Goal | Command / action |
| --- | --- |
| Commit extension work across repos | `git convoy feature adopt` → `feature commit` → `feature prs` |
| Publish rc wheels for staging train | `git convoy train tag-rc` → verify publish CI |
| Refresh hub + console + peer pins | `git convoy adopt --bom ops/<tenant>-bom` → push BOM |
| Ship adopted pins **to a peer** | Push BOM (or **Deploy Peers**); stack must exist (§1d) |
| Enable production on BOM | `git convoy adopt --production --bom ops/<tenant>-bom` |
| Patch production extension quickly | `hotfix publish` → `hotfix adopt --bom ops/<tenant>-bom` → push |
| Change which dists are on a peer | Edit `peers.<id>.python` in `deploy_targets.yml`, then adopt or `generate_bom.py` |