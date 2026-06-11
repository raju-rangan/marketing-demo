# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import datetime
import importlib
import inspect
import json
import logging
import warnings
from typing import Any

import click
import dotenv
import google.auth
import vertexai
from google.cloud import resourcemanager_v3
from google.iam.v1 import iam_policy_pb2, policy_pb2
from vertexai._genai import _agent_engines_utils
from vertexai._genai.types import AgentEngine, AgentEngineConfig, IdentityType

import os
import shutil
from google.cloud import storage

# Suppress google-cloud-storage version compatibility warning
warnings.filterwarnings(
    "ignore", category=FutureWarning, module="google.cloud.aiplatform"
)

def bootstrap_infrastructure(project_id: str, location: str) -> str:
    """Creates the artifacts bucket and updates the .env file for the new project."""
    bucket_name = f"{project_id}-artifacts"
    client = storage.Client(project=project_id)
    
    lifecycle_rules = [
        {
            "action": {"type": "Delete"},
            "condition": {"age": 7}
        }
    ]

    try:
        bucket = client.get_bucket(bucket_name)
        click.echo(f"  ✅ Artifacts bucket already exists: gs://{bucket_name}")
        # Ensure lifecycle rules are up to date
        bucket.lifecycle_rules = lifecycle_rules
        bucket.patch()
        click.echo("  ✅ Updated lifecycle rules (7-day TTL).")
    except Exception:
        click.echo(f"  🔧 Creating artifacts bucket: gs://{bucket_name}")
        bucket = client.create_bucket(bucket_name, location=location)
        bucket.lifecycle_rules = lifecycle_rules
        bucket.patch()
        click.echo(f"  ✅ Created bucket with 7-day lifecycle policy: gs://{bucket_name}")

    # Update .env file with new project details
    dotenv_path = ".env"
    example_path = ".env.example"
    
    # Load from .env if it exists, otherwise from .env.example
    if os.path.exists(dotenv_path):
        env_config = dotenv.dotenv_values(dotenv_path)
    elif os.path.exists(example_path):
        env_config = dotenv.dotenv_values(example_path)
    else:
        env_config = {}

    # Update critical keys
    env_config["GOOGLE_CLOUD_PROJECT"] = project_id
    env_config["PROJECT_ID"] = project_id
    env_config["GOOGLE_CLOUD_BUCKET_ARTIFACTS"] = bucket_name
    env_config["MARKETING_ANALYST_DATASTORE_CLOUD_BUCKET"] = bucket_name
    env_config["LOGS_BUCKET_NAME"] = bucket_name
    
    # Replace old project bucket URIs with the new one
    old_bucket_suffix = "-artifacts"
    for k, v in env_config.items():
        if v and ("gs://" in v or "storage.googleapis.com" in v) and old_bucket_suffix in v:
            if "gs://" in v:
                parts = v.split("/", 3)
                if len(parts) >= 3:
                    new_v = f"gs://{bucket_name}/" + (parts[3] if len(parts) > 3 else "")
                    env_config[k] = new_v.rstrip("/")
            elif "storage.googleapis.com" in v:
                parts = v.split("/", 4)
                if len(parts) >= 4:
                    new_v = f"https://storage.googleapis.com/{bucket_name}/" + (parts[4] if len(parts) > 4 else "")
                    env_config[k] = new_v.rstrip("/")

    # Write back to .env
    with open(dotenv_path, "w") as f:
        for k, v in env_config.items():
            f.write(f"{k}={v}\n")
    
    click.echo(f"  ✅ Updated {dotenv_path} with new project configuration.")
    return bucket_name

def sync_assets(project_id: str, bucket_name: str, assets_dir: str = "app/assets/samples"):
    """Uploads the local assets directory to the GCS bucket."""
    if not os.path.exists(assets_dir):
        click.echo(f"  ⚠️ Warning: Assets directory not found at {assets_dir}. Skipping sync.")
        return

    client = storage.Client(project=project_id)
    bucket = client.get_bucket(bucket_name)

    click.echo(f"  🚀 Synchronizing assets from {assets_dir} to gs://{bucket_name}/samples/...")
    for root, _, files in os.walk(assets_dir):
        for file in files:
            local_path = os.path.join(root, file)
            # We want to upload to the 'samples/' prefix in the bucket
            blob_path = f"samples/{file}"
            blob = bucket.blob(blob_path)
            blob.upload_from_filename(local_path)
            click.echo(f"    - Uploaded {blob_path}")
    click.echo("  ✅ Asset synchronization complete.")

def setup_signing_service_account(project_id: str, sa_email: str, agent_principal: str = None) -> None:
    """Creates the signing service account and assigns necessary roles."""
    import subprocess
    
    if not sa_email:
        return

    sa_name = sa_email.split('@')[0]
    click.echo(f"\n🔧 Setting up Signing Service Account: {sa_email}")
    
    # 1. Create the Service Account (only on initial setup)
    if not agent_principal:
        click.echo(f"  - Creating service account: {sa_name}")
        try:
            res = subprocess.run([
                "gcloud", "iam", "service-accounts", "create", sa_name,
                "--display-name=Asset Signer for GCS",
                f"--project={project_id}"
            ], capture_output=True, text=True)
            if res.returncode == 0:
                click.echo("    ✅ Created successfully.")
            elif "already exists" in res.stderr:
                click.echo("    ✅ Already exists.")
            else:
                click.echo(f"    ⚠️ Failed to create: {res.stderr.strip()}")
        except Exception as e:
            click.echo(f"    ⚠️ Error executing gcloud: {e}")

        # 2. Grant it storage access
        click.echo(f"  - Granting roles/storage.objectViewer to {sa_email}")
        try:
            subprocess.run([
                "gcloud", "projects", "add-iam-policy-binding", project_id,
                f"--member=serviceAccount:{sa_email}",
                "--role=roles/storage.objectViewer"
            ], capture_output=True)
            click.echo("    ✅ Role granted.")
        except Exception:
            pass
    
    # 3. Grant Impersonation Access
    # If agent_principal is provided, grant it to the agent. Otherwise, grant it to the current user.
    target_member = f"principal://{agent_principal}" if agent_principal and "principal://" not in agent_principal else agent_principal
    
    if not target_member:
        try:
            user_account_res = subprocess.run(["gcloud", "config", "get-value", "account"], check=True, capture_output=True, text=True)
            user_account = user_account_res.stdout.strip()
            if user_account:
                target_member = f"user:{user_account}"
        except Exception:
            pass

    if target_member:
        click.echo(f"  - Granting impersonation access to: {target_member}")
        try:
            subprocess.run([
                "gcloud", "iam", "service-accounts", "add-iam-policy-binding", sa_email,
                f"--member={target_member}",
                "--role=roles/iam.serviceAccountTokenCreator",
                f"--project={project_id}"
            ], capture_output=True)
            click.echo(f"    ✅ Granted roles/iam.serviceAccountTokenCreator.")
        except Exception as e:
            click.echo(f"    ⚠️ Failed to setup impersonation: {e}")

def generate_class_methods_from_agent(agent_instance: Any) -> list[dict[str, Any]]:
    """Generate method specifications with schemas from agent's register_operations().

    See: https://docs.cloud.google.com/agent-builder/agent-engine/use/custom#supported-operations
    """
    registered_operations = _agent_engines_utils._get_registered_operations(
        agent=agent_instance
    )
    class_methods_spec = _agent_engines_utils._generate_class_methods_spec_or_raise(
        agent=agent_instance,
        operations=registered_operations,
    )
    class_methods_list = [
        _agent_engines_utils._to_dict(method_spec) for method_spec in class_methods_spec
    ]
    return class_methods_list


def parse_key_value_pairs(kv_string: str | None) -> dict[str, str]:
    """Parse key-value pairs from a comma-separated KEY=VALUE string."""
    result = {}
    if kv_string:
        for pair in kv_string.split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                result[key.strip()] = value.strip()
            else:
                logging.warning(f"Skipping malformed key-value pair: {pair}")
    return result


def parse_secrets(secrets_string: str | None) -> dict[str, dict[str, str]]:
    """Parse secrets from ENV_VAR=SECRET_ID or ENV_VAR=SECRET_ID:VERSION format."""
    raw = parse_key_value_pairs(secrets_string)
    result: dict[str, dict[str, str]] = {}
    for key, spec in raw.items():
        if ":" not in spec:
            secret_id, version = spec, "latest"
        else:
            secret_id, _, version = spec.rpartition(":")
        result[key] = {"secret": secret_id, "version": version}
    return result


def format_env_value(value: Any) -> str:
    """Format an env var value for display, masking secrets."""
    if isinstance(value, dict) and "secret" in value and "version" in value:
        return f"[secret:{value['secret']}:{value['version']}]"
    return str(value)


def write_deployment_metadata(
    remote_agent: Any,
    metadata_file: str = "deployment_metadata.json",
) -> None:
    """Write deployment metadata to file."""
    metadata = {
        "remote_agent_engine_id": remote_agent.api_resource.name,
        "deployment_target": "agent_engine",
        "is_a2a": False,
        "deployment_timestamp": datetime.datetime.now().isoformat(),
    }

    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logging.info(f"Agent Engine ID written to {metadata_file}")


def print_deployment_success(
    remote_agent: Any,
    location: str,
    project: str,
) -> None:
    """Print deployment success message with console URL."""
    # Extract agent engine ID and project number for console URL
    resource_name_parts = remote_agent.api_resource.name.split("/")
    agent_engine_id = resource_name_parts[-1]
    project_number = resource_name_parts[1]
    print("\n✅ Deployment successful!")
    service_account = remote_agent.api_resource.spec.service_account
    if service_account:
        print(f"Service Account: {service_account}")
    else:
        default_sa = (
            f"service-{project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
        )
        print(f"Service Account: {default_sa}")
    playground_url = f"https://console.cloud.google.com/vertex-ai/agents/agent-engines/locations/{location}/agent-engines/{agent_engine_id}/playground?project={project}"
    print(f"\n📊 Open Console Playground: {playground_url}\n")


def setup_agent_identity(client: Any, project: str, display_name: str) -> Any:
    """Create agent with identity and grant required IAM roles."""
    click.echo(f"\n🔧 Creating agent identity for: {display_name}")
    agent = client.agent_engines.create(
        config={
            "identity_type": IdentityType.AGENT_IDENTITY,
            "display_name": display_name,
        }
    )

    roles = [
        "roles/aiplatform.user",
        "roles/serviceusage.serviceUsageConsumer",
        "roles/browser",
        "roles/cloudapiregistry.viewer",
        "roles/logging.logWriter",
        "roles/monitoring.metricWriter",
        "roles/storage.objectAdmin",
    ]
    principal = f"principal://{agent.api_resource.spec.effective_identity}"
    click.echo(f"🔐 Granting IAM roles to: {principal}")
    proj_client = resourcemanager_v3.ProjectsClient()
    policy = proj_client.get_iam_policy(
        request=iam_policy_pb2.GetIamPolicyRequest(resource=f"projects/{project}")
    )
    for role in roles:
        policy.bindings.append(policy_pb2.Binding(role=role, members=[principal]))
    proj_client.set_iam_policy(
        request=iam_policy_pb2.SetIamPolicyRequest(
            resource=f"projects/{project}", policy=policy
        )
    )
    click.echo("  ✅ Agent identity ready")
    return agent


@click.command()
@click.option(
    "--project",
    default=None,
    help="GCP project ID (defaults to application default credentials)",
)
@click.option(
    "--location",
    default="us-east1",
    help="GCP region (defaults to us-east1)",
)
@click.option(
    "--display-name",
    default="marketing-agent",
    help="Display name for the agent engine",
)
@click.option(
    "--description",
    default="Simple ReAct agent",
    help="Description of the agent",
)
@click.option(
    "--source-packages",
    multiple=True,
    default=["./app"],
    help="Source packages to deploy. Can be specified multiple times (e.g., --source-packages=./app --source-packages=./lib)",
)
@click.option(
    "--entrypoint-module",
    default="app.agent_engine_app",
    help="Python module path for the agent entrypoint (required)",
)
@click.option(
    "--entrypoint-object",
    default="agent_engine",
    help="Name of the agent instance at module level (required)",
)
@click.option(
    "--requirements-file",
    default="app/app_utils/.requirements.txt",
    help="Path to requirements.txt file",
)
@click.option(
    "--set-env-vars",
    default=None,
    help="Comma-separated list of environment variables in KEY=VALUE format",
)
@click.option(
    "--set-secrets",
    default=None,
    help="Comma-separated secrets: ENV_VAR=SECRET_ID or ENV_VAR=SECRET_ID:VERSION",
)
@click.option(
    "--labels",
    default=None,
    help="Comma-separated list of labels in KEY=VALUE format",
)
@click.option(
    "--service-account",
    default=None,
    help="Service account email to use for the agent engine",
)
@click.option(
    "--min-instances",
    type=int,
    default=1,
    help="Minimum number of instances (default: 1)",
)
@click.option(
    "--max-instances",
    type=int,
    default=10,
    help="Maximum number of instances (default: 10)",
)
@click.option(
    "--cpu",
    default="4",
    help="CPU limit (default: 4)",
)
@click.option(
    "--memory",
    default="8Gi",
    help="Memory limit (default: 8Gi)",
)
@click.option(
    "--container-concurrency",
    type=int,
    default=9,
    help="Container concurrency (default: 9)",
)
@click.option(
    "--num-workers",
    type=int,
    default=1,
    help="Number of worker processes (default: 1)",
)
@click.option(
    "--agent-identity",
    is_flag=True,
    default=False,
    help="Enable agent identity for per-agent IAM access control (Preview feature)",
)
def deploy_agent_engine_app(
    project: str | None,
    location: str,
    display_name: str,
    description: str,
    source_packages: tuple[str, ...],
    entrypoint_module: str,
    entrypoint_object: str,
    requirements_file: str,
    set_env_vars: str | None,
    set_secrets: str | None,
    labels: str | None,
    service_account: str | None,
    min_instances: int,
    max_instances: int,
    cpu: str,
    memory: str,
    container_concurrency: int,
    num_workers: int,
    agent_identity: bool,
) -> AgentEngine:
    """Deploy the agent engine app to Vertex AI."""

    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Parse CLI environment variables, secrets, and labels
    env_vars: dict[str, Any] = parse_key_value_pairs(set_env_vars)
    secrets = parse_secrets(set_secrets)
    labels_dict = parse_key_value_pairs(labels)

    if not project:
        _, project = google.auth.default()

    # Bootstrap infrastructure and sync assets if project is provided
    if project:
        bucket_name = bootstrap_infrastructure(project, location)
        sync_assets(project, bucket_name)

    # Load local .env file values if present
    dotenv_vars = dotenv.dotenv_values(".env")
    for k, v in dotenv_vars.items():
        if v and k not in env_vars and k != "GOOGLE_CLOUD_PROJECT":
            env_vars[k] = v

    # Setup the signing service account if configured
    if project and env_vars.get("SIGNING_SERVICE_ACCOUNT"):
        setup_signing_service_account(project, env_vars["SIGNING_SERVICE_ACCOUNT"])

    # Merge secrets into env_vars (secrets override plain env vars)
    env_vars.update(secrets)  # type: ignore

    # Set deployment-specific environment variables
    env_vars["PROJECT_ID"] = project
    env_vars["GOOGLE_CLOUD_REGION"] = location
    env_vars["AGENT_VERSION"] = "5.20260410.1" # Manually setting version for deployment
    env_vars["NUM_WORKERS"] = str(num_workers)

    # Enable telemetry by default for Agent Engine
    env_vars.setdefault("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "true")
    env_vars.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🤖 DEPLOYING AGENT TO VERTEX AI AGENT ENGINE 🤖         ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # Log deployment parameters
    click.echo("\n📋 Deployment Parameters:")
    params = [
        ("Project", project),
        ("Location", location),
        ("Display Name", display_name),
        ("Min Instances", min_instances),
        ("Max Instances", max_instances),
        ("CPU", cpu),
        ("Memory", memory),
        ("Container Concurrency", container_concurrency),
    ]
    if service_account:
        params.append(("Service Account", service_account))
    if agent_identity:
        params.append(("Agent Identity", "Enabled (Preview)"))
    for name, value in params:
        click.echo(f"  {name}: {value}")
    if env_vars:
        click.echo("\n🌍 Environment Variables:")
        for key, value in sorted(env_vars.items()):
            click.echo(f"  {key}: {format_env_value(value)}")

    source_packages_list = list(source_packages)

    # Initialize vertexai client
    # Use v1beta1 API when agent identity is enabled (required for identity_type)
    http_options = {"api_version": "v1beta1"} if agent_identity else None
    client = vertexai.Client(
        project=project,
        location=location,
        http_options=http_options,
    )
    vertexai.init(project=project, location=location)

    # Dynamically import the agent instance to generate class_methods
    logging.info(f"Importing {entrypoint_module}.{entrypoint_object}")
    module = importlib.import_module(entrypoint_module)
    agent_instance = getattr(module, entrypoint_object)

    # If the agent_instance is a coroutine, await it to get the actual instance
    if inspect.iscoroutine(agent_instance):
        logging.info(f"Detected coroutine, awaiting {entrypoint_object}...")
        agent_instance = asyncio.run(agent_instance)
    # Generate class methods spec from register_operations
    class_methods_list = generate_class_methods_from_agent(agent_instance)

    config = AgentEngineConfig(
        display_name=display_name,
        description=description,
        source_packages=source_packages_list,
        entrypoint_module=entrypoint_module,
        entrypoint_object=entrypoint_object,
        class_methods=class_methods_list,
        env_vars=env_vars,
        service_account=service_account,
        requirements_file=requirements_file,
        labels=labels_dict,
        min_instances=min_instances,
        max_instances=max_instances,
        resource_limits={"cpu": cpu, "memory": memory},
        container_concurrency=container_concurrency,
        agent_framework="google-adk",
        identity_type=IdentityType.AGENT_IDENTITY if agent_identity else None,
    )

    # Check if an agent with this name already exists
    existing_agents = list(client.agent_engines.list())
    matching_agents = [
        agent
        for agent in existing_agents
        if agent.api_resource.display_name == display_name
    ]

    # Setup agent identity on first deployment
    if agent_identity and not matching_agents:
        matching_agents = [setup_agent_identity(client, project, display_name)]

    # Deploy the agent (create or update)
    action = "Updating" if matching_agents else "Creating"
    click.echo(f"\n🚀 {action} agent: {display_name} (this can take 3-5 minutes)...")

    if matching_agents:
        remote_agent = client.agent_engines.update(
            name=matching_agents[0].api_resource.name, config=config
        )
    else:
        remote_agent = client.agent_engines.create(config=config)

    # SDK omits secret_env from the update mask when empty, so clear it explicitly.
    if set_secrets is not None and not secrets and matching_agents:
        clear_op = client.agent_engines._update(
            name=remote_agent.api_resource.name,
            config={
                "spec": {"deployment_spec": {"secret_env": []}},
                "update_mask": "spec.deployment_spec.secret_env",
            },
        )
        _agent_engines_utils._await_operation(
            operation_name=clear_op.name,
            get_operation_fn=client.agent_engines._get_agent_operation,
        )

    write_deployment_metadata(remote_agent)
    print_deployment_success(remote_agent, location, project)

    # CRITICAL: Grant the deployed agent identity permission to use the signing account
    # This fixes the 'iam.serviceAccounts.signBlob' permission denied error in Gemini Enterprise.
    if project and env_vars.get("SIGNING_SERVICE_ACCOUNT"):
        agent_identity_val = remote_agent.api_resource.spec.effective_identity
        if agent_identity_val:
            setup_signing_service_account(project, env_vars["SIGNING_SERVICE_ACCOUNT"], agent_principal=agent_identity_val)

    return remote_agent


if __name__ == "__main__":
    deploy_agent_engine_app()
