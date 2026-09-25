# Overflow teardown (required after peer smoke)

Gate: every handle in `EXTERNAL_HANDLERS` has a peer map entry; light + one heavy smoke passed **on the peers**; kill-switch left **on** (peer routing) for the agreed soak.

Then tear down **all** of the following. Leaving any of it is a failed migration.

Placeholders: `<env_id>` and `<aws_account>` come from `deploy_targets.yml` (the `tenants:` key, `tenants.*.aws_account`). `<aws_profile>` is your **named** tenant CLI profile — same as [PEERS.md](PEERS.md). Do **not** use the default profile.

## 1. AWS overflow node

Preflight (must show the tenant account from `deploy_targets.yml`):

```bash
export AWS_PROFILE=<aws_profile>
aws sts get-caller-identity --profile "$AWS_PROFILE"
```

Dry-run, then execute (does not touch `{env}-peer-{peerId}`):

```bash
export AWS_PROFILE=<aws_profile>

python ops/bom-helper/scripts/teardown_overflow_handlers.py \
  --env-name <env_id> \
  --account <aws_account> \
  --region us-east-1 \
  --profile "$AWS_PROFILE"

CONFIRM_OVERFLOW_TEARDOWN=yes python ops/bom-helper/scripts/teardown_overflow_handlers.py \
  --env-name <env_id> \
  --account <aws_account> \
  --region us-east-1 \
  --profile "$AWS_PROFILE" \
  --execute
```

`--profile` (or `AWS_PROFILE`) is required. The script refuses `default` and, on `--execute`, verifies the active credentials match `--account`.

Deletes Lambda `{env}-handlers`, its log group, ECS cluster/task family `{env}-handlers-ecs`, overflow ECR and S3 bucket, overflow IAM/OIDC roles, and strips singleton overflow keys from platform-vars.

## 2. Stack B peel (git)

Done in launcher / bootstrap / renglo-cli: Stack B no longer instantiates `ComputeStack`. Hub `customer-config.json` is identity-only (`env_name`, `github_repo`, email, staging, optional BOM OIDC ids). `renglo system init` no longer copies `compute_type`, `ec2_*`, or `github_handlers_*`. Bootstrap synth no longer copies `compute_stack.py` into the API tree.

Order is Stack A → Stack B (API) → peer stacks. `ComputeStack` remains in **bom-helper** for `{env}-peer-*` only.

After this peel, synth Stack B so CloudFormation no longer owns overflow resources (they should already be gone from step 1).

## 3. CI / BOM

- Remove overflow handlers workflow if present: `ops/<tenant>-bom/.github/workflows/deploy_handlers.yml` (legacy `run.py` against `{env}-handlers`). Many tenants never had this file — skip if absent.
- Remove singleton overflow keys from `ops/<tenant>-bom/deploy_targets.yml`: `handlers_bom`, `handlers_compute`.
- Delete or archive `ops/<tenant>-bom/handlers_bom/` (overflow pin files; peers use `peers_bom/<peerId>/` only).

## 4. Router fallback

After kill-switch soak: remove singleton ARN fallback in `dev/renglo-lib/renglo/schd/external_handlers_config.py` and drop `EXTERNAL_HANDLERS_PEER_ROUTING`.

## 5. Laptop builds

Laptop builds use `peer_packager.py` + peer id only.

**Do not tear down:** Stack A, Stack B API/websocket, peer stacks, bom-helper, `*-bom` `peers:` catalog.
