# Getting Started Guide

This guide will walk you through the process of bootstrapping your local environment, setting up a new brand, testing it locally in the playground, deploying the agent to Google Cloud, and registering it with Gemini Enterprise.

## 1. Initial Setup & Infrastructure

Before you can create a brand or run the playground, you must authenticate and bootstrap your Google Cloud infrastructure (like creating the artifact storage bucket).

Run the following command:

```bash
make setup
```

**What this does:**
1. Runs Google Cloud authentication (`gcloud auth login` and `application-default login`).
2. Creates your dedicated GCS artifacts bucket with an automatic 7-day lifecycle policy (TTL).
3. Updates your `.env` file with the newly created bucket mapping.

### ⚠️ IMPORTANT: IAM Permissions
For the setup and subsequent steps to work, your authenticated Google Cloud user account **must** have the following roles assigned in the Google Cloud Console (IAM & Admin):
*   **Vertex AI User** (`roles/aiplatform.user`): Required to invoke Gemini models.
*   **Storage Object Admin** (`roles/storage.objectAdmin`): Required to create the bucket, upload brand assets, and save generated artifacts.
*   **Service Usage Consumer** (`roles/serviceusage.serviceUsageConsumer`): Required to use GCP APIs via Application Default Credentials (ADC).

---

## 2. Creating a New Brand

The project includes an automated onboarding script that uses Gemini to research a brand and generate the necessary configuration files and system prompts.

To create a new brand, use the `setup-brand` Make target:

```bash
make setup-brand BRAND="Your Brand Name" URL="https://www.yourbrand.com"
```

**What this does:**
1. Creates a new directory: `app/brands/your_brand_name/`.
2. Generates a `config.json`, `presets.json`, and `prompt.md` based on Gemini's research of the provided URL.
3. Creates an `assets/` subdirectory with placeholder dummy images (`logo.png` and `product_image.png`).
4. Automatically runs `make sync-assets` to upload these initial dummy assets to your Google Cloud Storage (GCS) artifacts bucket.

**Next Steps for the Brand:**
Replace the dummy `logo.png` and `product_image.png` files in `app/brands/your_brand_name/assets/` with your actual high-resolution brand assets. The next time you run `make playground` or `make sync-assets`, they will be uploaded to GCS automatically.

---

## 3. Running `make playground`

The playground is your local interactive testing environment. 

To start the playground with your new brand:

```bash
make playground BRAND="Your Brand Name"
```

*Note: If you receive a 403 error related to GCS when running `make playground`, verify you have the `Storage Object Admin` role and that you've successfully run `make setup`.*

---

## 4. Deploying the Agent

Once you are satisfied with your agent's behavior locally, you can deploy it to Vertex AI Agent Engine.

To deploy the agent for a specific brand:

```bash
make deploy BRAND="Your Brand Name"
```

**What this does:**
1. Runs `make sync-assets` to ensure all local assets are updated in GCS.
2. Exports your dependencies into a `requirements.txt` file using `uv export`.
3. Calls the deployment script (`app/app_utils/deploy.py`), which will:
   - Ensure the GCS artifacts bucket exists and has a 7-day lifecycle policy (TTL).
   - Update your `.env` file with any new bucket mappings.
   - Deploy the agent to Vertex AI Agent Engine.
   - (Optional) Set up a signing service account and Agent Identity if configured.

*Note: You can pass additional flags to `make deploy` such as `AGENT_IDENTITY=true` or `SECRETS="KEY=SECRET_ID"` if needed.*

---

## 5. Register with Gemini Enterprise

After your agent is successfully deployed to Vertex AI Agent Engine, you can register it as an extension in Gemini Enterprise.

Run the following interactive command:

```bash
make register-gemini-enterprise
```

**What this does:**
This command uses the `agent-starter-pack` CLI to register your deployed Agent Engine instance with Gemini Enterprise. 
*   If run interactively, it will prompt you for necessary details like the Agent Display Name and Description.
*   For CI/CD or non-interactive usage, you can pre-set environment variables like `GEMINI_ENTERPRISE_APP_ID`, `GEMINI_DISPLAY_NAME`, and `AGENT_ENGINE_ID` in your `.env` file before running the command.
