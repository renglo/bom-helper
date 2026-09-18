#!/usr/bin/env python3
"""Build and publish a peer's zip Lambda and optional ECS image from a wheelhouse.

Does not use extensions-service ``run.py``. Resource names follow
``{env}-peer-{peerId}``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from peers import handlers_unit_name  # noqa: E402
from prepare_handlers_wheelhouse import pin_specs  # noqa: E402


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=cwd, env=env)


def _dockerfile(*, large: bool) -> str:
    entry = (
        'COPY ecs_handler_entrypoint.py /ecs_entrypoint.py\n'
        'WORKDIR /build/output\n'
        'ENTRYPOINT ["python3.12", "/ecs_entrypoint.py"]\n'
        if large
        else "WORKDIR /build/output\n"
    )
    zip_line = "true" if large else "cd /build/output && zip -r /build/lambda_deployment.zip . -q"
    return f"""FROM public.ecr.aws/lambda/python:3.12
RUN microdnf install -y zip && microdnf clean all
WORKDIR /build
COPY wheelhouse/ /build/wheelhouse/
COPY handlers-assets/ /build/assets/
COPY packages.txt /build/packages.txt
RUN python3.12 -m pip install --upgrade pip setuptools wheel -q \\
 && mkdir -p /build/output \\
 && python3.12 -m pip install --no-cache-dir --no-index --find-links /build/wheelhouse --target /build/output -r /build/packages.txt \\
 && cp /build/assets/lambda_router.py /build/output/ \\
 && if [ -f /build/assets/handlers_config.json ]; then cp /build/assets/handlers_config.json /build/output/; fi \\
 && if [ -d /build/assets/extras ]; then cp -a /build/assets/extras /build/output/extras; fi \\
 && cd /build/output \\
 && find . -type d -name '__pycache__' -exec rm -rf {{}} + 2>/dev/null || true \\
 && find . -type f -name '*.pyc' -delete 2>/dev/null || true \\
 && {zip_line}
{entry}
"""


def cmd_build(args: argparse.Namespace) -> int:
    unit = handlers_unit_name(args.env_name, args.peer_id)
    wheelhouse = Path(args.wheelhouse).resolve()
    assets = Path(args.assets).resolve()
    if not wheelhouse.is_dir():
        print(f"wheelhouse not found: {wheelhouse}", file=sys.stderr)
        return 1
    packages = [p.strip() for p in str(args.packages).split(",") if p.strip()]
    if not packages:
        print("ERROR: --packages is required", file=sys.stderr)
        return 1
    install_specs = pin_specs(packages, wheelhouse)
    print(f"pip install specs: {', '.join(install_specs)}")
    platform = "linux/arm64" if args.local else "linux/amd64"
    tag_suffix = "local" if args.local else "latest"
    kind = "ecs-builder" if args.large else "lambda-builder"
    image = f"{unit}-{kind}:{tag_suffix}"
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="peer-packager-") as raw:
        build_dir = Path(raw)
        shutil.copytree(wheelhouse, build_dir / "wheelhouse")
        shutil.copytree(assets, build_dir / "handlers-assets")
        (build_dir / "packages.txt").write_text(
            "\n".join(install_specs) + "\n", encoding="utf-8"
        )
        entry = _SCRIPTS / "ecs_handler_entrypoint.py"
        if args.large:
            if not entry.is_file():
                print(f"missing {entry}", file=sys.stderr)
                return 1
            shutil.copy2(entry, build_dir / "ecs_handler_entrypoint.py")
        (build_dir / "Dockerfile").write_text(_dockerfile(large=args.large), encoding="utf-8")
        _run(
            [
                "docker",
                "build",
                "--platform",
                platform,
                "-f",
                str(build_dir / "Dockerfile"),
                "-t",
                image,
                str(build_dir),
            ]
        )
        if not args.large:
            zip_path = out_dir / "lambda_deployment.zip"
            _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--platform",
                    platform,
                    "--entrypoint",
                    "/bin/sh",
                    "-v",
                    f"{out_dir}:/output",
                    image,
                    "-c",
                    "cp /build/lambda_deployment.zip /output/ && chmod 644 /output/lambda_deployment.zip",
                ]
            )
            if not zip_path.is_file():
                print("ERROR: zip not extracted", file=sys.stderr)
                return 1
            print(f"Wrote {zip_path}")
        print(f"Image {image}")
        (out_dir / "image.txt").write_text(image + "\n", encoding="utf-8")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    unit = handlers_unit_name(args.env_name, args.peer_id)
    zip_path = Path(args.zip).resolve()
    if not zip_path.is_file():
        print(f"zip not found: {zip_path}", file=sys.stderr)
        return 1
    region = args.region or os.environ.get("AWS_REGION") or "us-east-1"
    _run(
        [
            "aws",
            "lambda",
            "update-function-code",
            "--function-name",
            unit,
            "--zip-file",
            f"fileb://{zip_path}",
            "--region",
            region,
        ]
    )
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    unit = handlers_unit_name(args.env_name, args.peer_id)
    region = args.region or os.environ.get("AWS_REGION") or "us-east-1"
    account = args.account.strip()
    if not account:
        account = subprocess.check_output(
            ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
            text=True,
        ).strip()
    repo = f"{unit}-ecs"
    image = args.image.strip() or f"{unit}-ecs-builder:latest"
    ecr = f"{account}.dkr.ecr.{region}.amazonaws.com/{repo}:latest"
    login = subprocess.check_output(
        ["aws", "ecr", "get-login-password", "--region", region],
        text=True,
    )
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", f"{account}.dkr.ecr.{region}.amazonaws.com"],
        input=login,
        text=True,
        check=True,
    )
    _run(["docker", "tag", image, ecr])
    _run(["docker", "push", ecr])
    print(f"Pushed {ecr} (task definition family {unit}-ecs already from peer CDK)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Peer zip / ECS packager (bom-helper)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_identity(p: argparse.ArgumentParser) -> None:
        p.add_argument("--env-name", required=True, help="Tenant AWS prefix")
        p.add_argument("--peer-id", required=True, help="Catalog peer id")

    b = sub.add_parser("build", help="Docker-build zip and/or ECS image from wheelhouse")
    add_identity(b)
    b.add_argument("--wheelhouse", required=True)
    b.add_argument("--assets", required=True)
    b.add_argument("--packages", required=True, help="Comma-separated dist names to pip install")
    b.add_argument("--out", default=".peer-build")
    b.add_argument("--large", action="store_true", help="ECS image with ecs_handler_entrypoint")
    b.add_argument("--local", action="store_true", help="linux/arm64 :local tag")

    p = sub.add_parser("publish", help="Update peer Lambda code from zip")
    add_identity(p)
    p.add_argument("--zip", required=True)
    p.add_argument("--region", default="")

    u = sub.add_parser("push", help="Tag/push ECS image to the peer ECR repo")
    add_identity(u)
    u.add_argument("--image", default="")
    u.add_argument("--region", default="")
    u.add_argument("--account", default="")

    args = parser.parse_args()
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "publish":
        return cmd_publish(args)
    return cmd_push(args)


if __name__ == "__main__":
    raise SystemExit(main())
