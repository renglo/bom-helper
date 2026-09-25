# arbitiumtriage — installer/infra

Extension-owned install configuration. Platform CDK / bootstrap do **not** hardcode
ArbitiumTriage resource names; everything domain-specific lives in this folder.

| File | Role |
|------|------|
| `arbitiumtriage_actions_tt_policy.json` | Optional extension-specific IAM (platform AI policy covers vectors/Bedrock/docs) |
| `cdk_extension.json` | Host-stack `ExtensionStack` manifest — **indexes only** on the platform vector bucket |
| `extension_config.json` | Runtime defaults / env exports for this extension (index names) |

## How provisioning works

**Stack A** always creates platform AI amenities: one S3 Vectors bucket, `rag-kb`
index, RAG docs bucket, and the default Bedrock Knowledge Base (`KB_ID`).

**ExtensionStack** (the stack chosen by catalog placement) reads
`cdk_extension.json` and creates only the declared `s3_vector_indexes[]` on that
platform bucket. It does **not** create a private vector bucket or the default KB.

Optional extra KBs may be declared under `bedrock_knowledge_bases[]` with distinct
output vars (never `KB_ID`).

## Runtime env

Platform (Stack A / SSM / `write-local-config`):

| Variable | Purpose |
|----------|---------|
| `S3_VECTORS_BUCKET` | Platform vector bucket |
| `S3_VECTORS_INDEX_RAG_KB` | Index owned by Bedrock KB ingest (`rag-kb`) |
| `RAG_DOCS_BUCKET` / `RAG_DOCS_PREFIX` | Classic S3 for KB source docs |
| `KB_ID` / `RAG_DATA_SOURCE_ID` | Default platform Knowledge Base |
| `EMBEDDING_MODEL_ID` | Bedrock embedding model (default Titan Text v2) |
| `RAG_MODEL_ARN` | Optional model ARN for retrieve_and_generate |

Extension-declared (this folder):

| Variable | Purpose |
|----------|---------|
| `S3_VECTORS_INDEX_THREAT_EVENTS` | Index for threat_event / action embeddings |
| `S3_VECTORS_INDEX_CATALOG` | Index for threat_catalog embeddings |
| `S3_VECTORS_INDEX_CAMPAIGNS` | Index for open campaign embeddings |

Handlers use `renglo.vector.VectorController` / `renglo.rag.RagController`
— never boto3 `s3vectors` directly.

## RAG document upload

Use Data → Explorer → Knowledge base (`/_rag`), or see
[../../docs/RAG_KB_UPLOAD.md](../../docs/RAG_KB_UPLOAD.md).
