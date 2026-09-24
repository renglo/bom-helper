# arbitiumlab — installer/infra



Example extension module repo. Catalog placement (`peers.<id>.extensions` or `hub.python` in `*-bom/deploy_targets.yml`) decides which stack creates this infra. That handle is **not** the platform env.



Use `<env_name>` = the platform environment (`customer-config.json` → `env_name`).



## CDK delivery (recommended)



Extension AWS resources are **not** provisioned with a post-deploy bash script. They are declared in `cdk_extension.json` and synthesized into the stack that hosts the extension (Stack B for hub, `{env}-peer-{id}` for a peer):



| Resource | Name |

|----------|------|

| S3 bucket | `{env}-threat-events-{account_id}` |

| IAM policy | Hub: manifest `policy_name`. Peer: `{env}-peer-{id}-{handle}-actions` |

| Attachments | Hub: `{env}_tt_role`. Peer: `{env}-peer-{id}-role` and `{env}-peer-{id}-ecs-task` |



Deploy order (after `<env>-stack-a` and seed image):



```bash

cdk deploy <env>-stack-b --app "python app.py" --require-approval never --profile "$AWS_PROFILE"

```



`write-state` reads **`<env>-stack-b`** outputs and uploads blueprints from `../blueprints/`.



### Files



| File | Purpose |

|------|---------|

| `cdk_extension.json` | CDK manifest (policy, S3, role attachments) + `state` block for write-state |

| `extension_config.json` | Vars/secrets merged into deploy state |

| `actions_tt_policy.json` | IAM policy document |

| `provision_extension.sh` | Standalone/legacy manual provision (same resources as CDK stack) |



## DevOps policy (standalone install)



For manual provisioning outside CDK:



```bash

./render_devops_provision_policy.sh <env_name> --aws-profile <profile> --aws-region us-east-1 \

  -o <env_name>_devops_extension_provision_policy.json



./provision_extension.sh <env_name> --aws-profile <profile> --aws-region us-east-1

```



## With bootstrap (full CDK flow)



See `bootstrap/README.md`. `write-state` reads `extension-state.json` from `bootstrap/output/<env>/` (generated at synth). Runtime vars go to `deploy_input` / `platform_vars`; inventory outputs (e.g. `ActionsPolicyArn`) only appear in `platform_resources.json`.



After both CDK stacks (`<env>-stack-a` and `<env>-stack-b`):



```bash

python bootstrap/install.py write-state \

  --env-name <env_name> \

  --aws-profile <profile> \

  --aws-region us-east-1

```



## Stack deletion



`cdk destroy <env>-stack-b` removes extension-owned resources:



- S3 bucket (emptied via CDK auto-delete, then deleted)

- IAM managed policy `{env}_actions_tt_policy` (detached from platform roles, then deleted)



Delete **`<env>-stack-b`** before **`<env>-stack-a`**. Platform roles in `<env>-stack-a` are not removed by `<env>-stack-b`.



If S3 delete fails, empty `{env}-threat-events-{account_id}` manually and retry stack delete.



## Standalone teardown (legacy bash)



```bash

./teardown_extension.sh <env_name> --aws-profile <profile> --aws-region us-east-1

```

