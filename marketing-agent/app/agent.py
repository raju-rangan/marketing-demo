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

import os
from dotenv import load_dotenv

# Load environment variables from .env file
# The .env file is in the parent directory of 'app'
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(dotenv_path)

# Set critical environment variables for ADK if not already set
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    # If not in environ, try to get from .env (already loaded by load_dotenv above)
    project = os.getenv("PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = project

os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.getenv("GOOGLE_CLOUD_LOCATION", "global"))
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

# Import the assembled app from the modular factory
from app.agent_factory import app, root_agent

__all__ = ["app", "root_agent"]
