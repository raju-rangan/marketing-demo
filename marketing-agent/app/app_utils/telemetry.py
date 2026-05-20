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

import logging
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor


def setup_telemetry() -> str | None:
    """Configure OpenTelemetry and GenAI telemetry with Cloud Trace and GCS upload."""
    os.environ.setdefault("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "true")

    # 1. OpenTelemetry Tracing Setup (Cloud Trace)
    try:
        # Use a project ID from environment or default
        project_id = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            project_id = None
        
        provider = TracerProvider()
        exporter = CloudTraceSpanExporter(project_id=project_id)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        
        # Instrument the Google GenAI SDK
        GoogleGenAiSdkInstrumentor().instrument()
        logging.info("OpenTelemetry Tracing initialized with Cloud Trace exporter.")
    except Exception as e:
        logging.warning(f"Could not initialize OpenTelemetry/CloudTrace: {e}")

    # 2. GCS Upload Telemetry (Legacy / Sidecar logging)
    bucket = os.environ.get("LOGS_BUCKET_NAME") or os.environ.get("GOOGLE_CLOUD_BUCKET_ARTIFACTS")
    capture_content = os.environ.get(
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true"
    )
    
    if bucket and capture_content != "false":
        logging.info(
            f"Prompt-response GCS logging enabled via bucket: {bucket}"
        )
        # If the user explicitly wants full content, we honor it, otherwise default to NO_CONTENT
        if capture_content == "true":
            os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"
        else:
            os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "NO_CONTENT"
            
        os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT", "jsonl")
        os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK", "upload")
        os.environ.setdefault(
            "OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental"
        )
        commit_sha = os.environ.get("COMMIT_SHA", "dev")
        os.environ.setdefault(
            "OTEL_RESOURCE_ATTRIBUTES",
            f"service.namespace=marketing-agent,service.version={commit_sha}",
        )
        path = os.environ.get("GENAI_TELEMETRY_PATH", "completions")
        os.environ.setdefault(
            "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH",
            f"gs://{bucket}/{path}",
        )
    else:
        logging.info(
            "Prompt-response GCS logging disabled (set LOGS_BUCKET_NAME or GOOGLE_CLOUD_BUCKET_ARTIFACTS to enable)"
        )

    return bucket
