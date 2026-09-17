# Overflow teardown (required after peer smoke)

Gate: every handle in `EXTERNAL_HANDLERS` has a peer map entry; light + one heavy smoke passed **on the peers**; kill-switch left **on** (peer routing) for the agreed soak.

Then tear down **all** of the following. Leaving any of it is a failed migration.

## 1. AWS overflow node

Dry-run, then execute (does not touch `{env}-peer-{peerId}`):

```bash
python ops/bom-helper/scripts/teardown_overflow_handlers.py \
  --env-name <env_id> \
  --account <aws_account> \
  --region us-east-1

CONFIRM_OVERFLOW_TEARDOWN=yes python ops/bom-helper/scripts/teardown_overflow_handlers.py \
  --env-name <env_id> \
  --account <aws_account> \
  --region us-east-1 \
  --execute
```

Deletes Lambda `{env}-handlers`, its log group, ECS cluster/task family `{env}-handlers-ecs`, overflow ECR and S3 bucket, overflow IAM/OIDC roles, and strips singleton overflow keys from platform-vars.

## 2. Stack B peel (git)

In `ops/launcher/cdk/stacks/stack_b.py`: stop instantiating `ComputeStack`; stop importing `compute_stack.py` from extensions-service. Remove `compute_type`, `ec2_*`, `github_handlers_repo` from `customer-config.json`. Synth Stack B so CloudFormation no longer owns overflow resources (they should already be gone from step 1).

`ops/bootstrap`: stop cloning extensions-service for API synth. Order is Stack A → Stack B (API) → peer stacks.

## 3. CI / BOM

- Remove overflow job from `ops/<tenant>-bom/.github/workflows/deploy_handlers.yml` (`run.py` against `{env}-handlers`).
- Drop git pin `renglo/extensions-service` from overflow `handlers_bom/*.json`.
- Drop singleton `handlers_bom` / `handlers_compute` once `peers:` is the only catalog.

## 4. Router fallback

After kill-switch soak: remove singleton ARN fallback in `dev/renglo-lib/renglo/schd/external_handlers_config.py` and drop `EXTERNAL_HANDLERS_PEER_ROUTING`.

## 5. Archive extensions-service

See `ops/extensions-service/DEPRECATED.md`. Laptop builds use `peer_packager.py` + peer id only.

**Do not tear down:** Stack A, Stack B API/websocket, peer stacks, bom-helper, `*-bom` `peers:` catalog.
