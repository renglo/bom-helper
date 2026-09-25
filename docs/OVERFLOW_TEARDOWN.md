# Overflow teardown (required after peer smoke)

Gate: every handle in `EXTERNAL_HANDLERS` has a peer map entry; light + one heavy smoke passed **on the peers**; kill-switch left **on** (peer routing) for the agreed soak.

Then tear down **all** of the following. Leaving any of it is a failed migration.

Placeholders: `<env_id>` and `<aws_account>` come from `deploy_targets.yml` (`tenants.*.id`, `tenants.*.aws_account`). `<aws_profile>` is your **named** tenant CLI profile — same as [PEERS.md](PEERS.md). Do **not** use the default profile.

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

In `ops/launcher/cdk/stacks/stack_b.py`: stop instantiating overflow `ComputeStack`. Remove `compute_type`, `ec2_*`, `github_handlers_repo` from `customer-config.json`. Synth Stack B so CloudFormation no longer owns overflow resources (they should already be gone from step 1).

`ops/bootstrap` copies `compute_stack.py` / `github_oidc.py` from `bom-helper` for API synth. Order is Stack A → Stack B (API) → peer stacks.

## 3. CI / BOM

- Remove overflow handlers workflow if present: `ops/<tenant>-bom/.github/workflows/deploy_handlers.yml` (legacy `run.py` against `{env}-handlers`). Many tenants never had this file — skip if absent.
- Remove singleton overflow keys from `ops/<tenant>-bom/deploy_targets.yml`: `handlers_bom`, `handlers_compute`.
- Delete or archive `ops/<tenant>-bom/handlers_bom/` (overflow pin files; peers use `peers_bom/<peerId>/` only).

## 4. Router fallback

After kill-switch soak: remove singleton ARN fallback in `dev/renglo-lib/renglo/schd/external_handlers_config.py` and drop `EXTERNAL_HANDLERS_PEER_ROUTING`.

## 5. Laptop builds

Laptop builds use `peer_packager.py` + peer id only.

**Do not tear down:** Stack A, Stack B API/websocket, peer stacks, bom-helper, `*-bom` `peers:` catalog.
