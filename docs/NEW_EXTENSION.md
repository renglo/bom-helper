# Add a new extension (three golden paths)

Prefer the CLI: [EXTENSIONS.md](EXTENSIONS.md). From `ops/bom-helper`, run `bash setup-venv.sh && source bom-venv/bin/activate`, then `extensions install place … --profile <profile>` (profile is stored on the incubation sheet for `publish` and `deploy`). This page is the same paths as files + the four operator actions.

This is the operator document for installing extension **xyz** into an existing tenant. It assumes Stack A, Stack B, and (for paths 2–3) at least one peer stack already exist.

Example tenant used below:

| Thing | Example |
| --- | --- |
| Env prefix | `arbitium0813` (`ops/launcher/cdk/customer-config.json` → `env_name`) |
| BOM repo | `ops/arbitium-bom/` |
| Catalog | `ops/arbitium-bom/deploy_targets.yml` |
| Existing peer | `lab` (`{env}-peer-lab`) |
| New peer (path 3) | `audio` (`{env}-peer-audio`) |
| Handle / folder | `xyz` → `extensions/xyz/` |
| Python wheel | `xyz` (must already be in CodeArtifact) |

Do **not** set `extension_path` in `ops/launcher/cdk/customer-config.json`. Placement is the catalog.

Do **not** deploy Stack A for a new extension. Stack A already allows hub → `{env}-peer-*-ecs-*`.

---

## The four operator actions

For **manual** steps below, set these once per shell. Run every command from `ops/` unless a `cd` says otherwise. If you use the CLI for incubation, pass `--profile` on `install place` instead — later CLI steps read it from the sheet.

```bash
export ENV=arbitium0813
export AWS_PROFILE=<your-aws-profile>
export AWS_REGION=us-east-1
```

### Deploy Stack A

Not used on these paths.

### Deploy Stack B

Creates hub-placed buckets / indexes / policies and uploads catalog blueprints.

```bash
cd ops
python3.12 bootstrap/install.py synth

cd bootstrap/output/${ENV}/cdk
cdk deploy "${ENV}-stack-b" \
  --app "../../../venv/bin/python app.py" \
  --output . \
  --exclusively \
  --require-approval never \
  --profile "$AWS_PROFILE"

cd ../../..
python3.12 bootstrap/install.py write-state \
  --env-name "$ENV" \
  --aws-profile "$AWS_PROFILE" \
  --aws-region "$AWS_REGION"
```

### Deploy `{env}-peer-{name}`

Creates that peer’s Lambda/ECS/IAM **and** every extension listed on `peers.<name>.extensions` (buckets, indexes, policy).

First time on this laptop only:

```bash
cd ops/bom-helper
bash setup-venv.sh
```

Then (example: lab):

```bash
cd ops/bom-helper
export PEER_ID=lab
bash scripts/deploy_peer_cdk.sh synth --peer-id "$PEER_ID"
bash scripts/deploy_peer_cdk.sh deploy --peer-id "$PEER_ID"

cd ..
python3.12 bootstrap/install.py write-state \
  --env-name "$ENV" \
  --aws-profile "$AWS_PROFILE" \
  --aws-region "$AWS_REGION"
```

For path 3, use `PEER_ID=audio` (stack name `arbitium0813-peer-audio`).

### Push the BOM

Puts wheels on the running hub image and/or peer zip/image, and writes handle → peer routes. That is GitHub Actions on `ops/arbitium-bom` `main` (`Deploy Backend` and/or `Deploy Peers`). You do not run packager or `write_peer_routes.py` by hand.

```bash
cd ops/arbitium-bom
git add deploy_targets.yml bom/ peers_bom/ console_bom/
git status
git commit -m "Install extension xyz on <hub|lab|audio>."
git push origin main
```

Add only the files you actually changed. The xyz wheel must already be published to CodeArtifact at the version you pin.

---

## Shared: installer files (all three paths)

Create these before any stack deploy. Declaring a bucket in the manifest does **not** grant IAM — the policy JSON must include the S3 actions.

`extensions/xyz/installer/infra/cdk_extension.json`:

```json
{
  "policy_file": "actions_tt_policy.json",
  "policy_name": "{env}-xyz-actions",
  "policy_description": "xyz audio bucket",
  "s3_buckets": [
    {
      "id": "XyzAudio",
      "name_prefix": "{env}-xyz-audio",
      "output_var": "XYZ_AUDIO_BUCKET"
    }
  ]
}
```

`extensions/xyz/installer/infra/actions_tt_policy.json` (trim to what xyz actually needs):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "XyzAudioBucket",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::*-xyz-audio-*",
        "arn:aws:s3:::*-xyz-audio-*/*"
      ]
    }
  ]
}
```

Optional: `extensions/xyz/installer/infra/extension_config.json` for extra runtime env. Optional: `extensions/xyz/blueprints/` (or `installer/blueprints/`) — those upload on **Deploy Stack B**, even if xyz runs on a peer.

Catalog **placement** decides which stack creates the bucket and which role gets the policy. One extension → one owner. Do not list xyz on both `hub.python` and `peers.*.extensions`.

---

## 1) xyz on the hub

Meaning: xyz runs inside the API (backend Lambda). No peer, no peer routes.

### a) Config

`ops/arbitium-bom/deploy_targets.yml` — add a `packages:` slot and put the **python dist name** on `hub.python`. Keep xyz off every `peers.*.extensions` list.

```yaml
hub:
  python:
    - renglo-data
    - renglo-schd
    - renglo-gro
    - xyz

packages:
  xyz:
    python: xyz
    # npm: "@arbitium/xyz"   # only if xyz has a console package
```

Pin the wheel in the hub BOM that `bom:` already points at. If the file header says `bom: 0.1.8`, edit `ops/arbitium-bom/bom/v0.1.8.json`:

```json
"python": {
  "renglo-lib": "0.0.5rc4",
  "renglo-api": "0.0.7rc1",
  "xyz": "0.0.1"
}
```

If xyz has console npm, also pin it in `ops/arbitium-bom/console_bom/v0.1.8.json` (same version as `console_bom:`).

Do not edit `ops/launcher/cdk/customer-config.json`.

### b) Execute

1. **Deploy Stack B** (commands above). Stack B creates `{env}-xyz-audio-{account}` and attaches xyz’s policy to `{env}_tt_role`.
2. **Push the BOM.** `Deploy Backend` puts the xyz wheel on the API image.

Skip **Deploy `{env}-peer-*`**. Skip Stack A.

After that: API code can use `XYZ_AUDIO_BUCKET`. There is no `{env}-peer-*` for xyz.

---

## 2) xyz on an existing peer (lab)

Meaning: same machine as lab/triage; one more handle on that zip/image.

### a) Config

`ops/arbitium-bom/deploy_targets.yml`:

- Add `packages.xyz` (same as path 1).
- Add `xyz` to `peers.lab.extensions`.
- Add dist `xyz` to `peers.lab.python`.
- Do **not** add xyz to `hub.python`.

```yaml
packages:
  xyz:
    python: xyz

peers:
  lab:
    compute: fargate
    task_size: medium
    extensions: [arbitiumlab, arbitiumtriage, xyz]
    python:
      - arbitium-lab
      - arbitium-triage
      - renglo-gro
      - xyz
    peers_bom: 0.1.8
```

Pin the wheel in the lab peer BOM that `peers.lab.peers_bom` points at: `ops/arbitium-bom/peers_bom/lab/v0.1.8.json`:

```json
"python": {
  "renglo-lib": "0.0.5rc4",
  "arbitium-lab": "0.0.7rc3",
  "arbitium-triage": "0.0.7rc2",
  "xyz": "0.0.1"
}
```

If the console will call `/start` for xyz handlers, lab must stay `fargate` or `ec2` (it already is). A `lambda_only` peer has no ECS for `/start`.

### b) Execute

1. **Deploy `{env}-peer-lab`** with `PEER_ID=lab`. That stack creates the audio bucket and attaches xyz’s policy to `arbitium0813-peer-lab-role` and `arbitium0813-peer-lab-ecs-task`.
2. **Push the BOM.** `Deploy Peers` rebuilds the lab zip/image (xyz wheel on the machine) and writes SSM `/{env}/bootstrap/peer-routes` so handle `xyz` → lab.
3. **Deploy Stack B** only if xyz ships blueprints (platform DynamoDB table). Not required for the bucket or IAM.

Skip Stack A. The hub API role does **not** get xyz’s S3 rights. Other peers are unchanged.

---

## 3) xyz on its own peer (audio)

Meaning: separate Lambda/ECS/IAM from lab. Isolation is a new peer, not a new policy per handler.

### a) Config

`ops/arbitium-bom/deploy_targets.yml` — add `packages.xyz` and a new `peers.audio` row. Do not put xyz on `hub.python` or `peers.lab.extensions`.

```yaml
packages:
  xyz:
    python: xyz

peers:
  lab:
    compute: fargate
    extensions: [arbitiumlab, arbitiumtriage]
    python:
      - arbitium-lab
      - arbitium-triage
      - renglo-gro
    peers_bom: 0.1.8
  audio:
    compute: fargate
    task_size: medium
    extensions: [xyz]
    python:
      - xyz
    peers_bom: 0.1.8
```

Use `compute: lambda_only` instead of `fargate` if xyz only needs sync handlers (no `/start`).

Create `ops/arbitium-bom/peers_bom/audio/v0.1.8.json` (version must match `peers.audio.peers_bom`):

```json
{
  "version": "v0.1.8",
  "python": {
    "renglo-lib": "0.0.5rc4",
    "arbitium-wl": "0.0.3",
    "xyz": "0.0.1"
  },
  "repos": {}
}
```

Copy `renglo-lib` / `arbitium-wl` versions from `ops/arbitium-bom/peers_bom/lab/v0.1.8.json` unless you know you want different pins. Peer images always need `renglo-lib` (and the tenant `*-wl` wheel).

### b) Execute

1. **Deploy `{env}-peer-audio`** with `PEER_ID=audio`. First time this creates stack `arbitium0813-peer-audio`, the audio bucket, audio’s roles, and xyz’s policy on those roles only.
2. **Push the BOM.** `Deploy Peers` publishes the audio zip/image and writes routes so `xyz` → audio (not lab).
3. **Deploy Stack B** only if xyz ships blueprints.

Skip Stack A. lab does not get xyz’s bucket rights. Hub does not either.

---

## Which path did I pick?

| | Hub API runs xyz? | Bucket + policy created by | Zip/image that contains xyz | Handle `xyz` routes to |
| --- | --- | --- | --- | --- |
| 1 Hub | Yes | Stack B | Hub backend image | (no peer map) |
| 2 Existing lab | No | `{env}-peer-lab` | Lab peer zip/image | lab |
| 3 New audio | No | `{env}-peer-audio` | Audio peer zip/image | audio |

---

## Moving xyz from hub to a peer

Two stacks must not own the same bucket or index.

1. Remove xyz from `hub.python`; add it to `peers.<id>.extensions` / `python` (and pin `peers_bom/<id>/`).
2. **Deploy Stack B** first (drops the Stack B Extension resources).
3. **Deploy `{env}-peer-<id>`** (creates them on the peer).
4. **Push the BOM.**
