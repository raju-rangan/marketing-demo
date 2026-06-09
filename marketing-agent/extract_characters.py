import os
import glob
from google import genai
from google.genai import types
from PIL import Image
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

# Define brand and paths
brand = os.environ.get("ACTIVE_BRAND", "default")
output_dir = f"marketing-agent/app/brands/{brand}/assets"
output_file = os.path.join(output_dir, "reference_image.png")
text_output_file = os.path.join(output_dir, "style_prompt.txt")

print(f"Current working directory: {os.getcwd()}")
print(f"Target Brand: {brand}")

# 1. Initialize the client for Vertex AI
client = genai.Client(
    vertexai=True,
    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    location="global"
)

# 2. Load multiple reference images
reference_images = []
# Look for reference_image.png, reference_image_2.png, characters.png, etc.
patterns = ["marketing-agent/reference_image*.png", "marketing-agent/characters*.png"]
image_paths = []
for pattern in patterns:
    image_paths.extend(glob.glob(pattern))

# Remove duplicates if any
image_paths = sorted(list(set(image_paths)))

for path in image_paths:
    try:
        img = Image.open(path)
        reference_images.append(img)
        print(f"Loaded reference image: {path}")
    except Exception as e:
        print(f"Warning: Could not load '{path}': {e}")

if not reference_images:
    print("Error: No reference images found in 'marketing-agent/'. Please check the paths.")
    exit()

# 3. Create a character reference sheet prompt
image_prompt = (
    f"I have provided {len(reference_images)} reference images. "
    "Extract all main characters from these images and create one comprehensive, consolidated character reference sheet. "
    "Each character must be shown as a crisp, full-body representation to serve as a definitive guide for animators. "
    "CRITICAL: Maintain the EXACT artistic style, animation style, color palette, lighting, and rendering techniques found in the provided source images. "
    "The final generated image MUST look exactly like a frame from the same animation as the source images. "
    "Arrange them in a unified composition. On the far right side of the canvas, "
    "include a clean, vertical color palette showing the 5-7 primary hex-consistent colors used across all characters. "
    "This single image will serve as the definitive style, animation, and character reference for future video frames."
)

style_prompt = (
    f"I have provided {len(reference_images)} reference images. "
    "Analyze the animation style, lighting, rendering technique, and color palette of these images. "
    "Provide a detailed 1-paragraph text prompt describing these elements that an image generator can use to replicate this exact aesthetic."
)

print(f"Sending requests to Gemini (Project: {os.environ.get('GOOGLE_CLOUD_PROJECT')})...")

# 4. Generate the image
image_contents = reference_images + [image_prompt]
image_config = types.GenerateContentConfig(response_modalities=["IMAGE"])

image_response = client.models.generate_content(
    model=os.environ.get("IMAGE_GENERATION_MODEL", "gemini-3.1-flash-image-preview"),
    contents=image_contents,
    config=image_config
)

# 5. Generate the style text
style_response = client.models.generate_content(
    model=os.environ.get("MODEL_NAME", "gemini-3.1-flash-image-preview"),
    contents=reference_images + [style_prompt]
)

# 6. Extract and save the results
image_saved = False
text_saved = False

if not os.path.exists(output_dir):
    os.makedirs(output_dir, exist_ok=True)

# Save image
if hasattr(image_response, 'candidates') and image_response.candidates:
    for part in image_response.candidates[0].content.parts:
        if part.inline_data is not None:
            generated_image = part.as_image()
            generated_image.save(output_file)
            print(f"Success! Image saved as '{output_file}'")
            image_saved = True

# Save text
if hasattr(style_response, 'candidates') and style_response.candidates:
    text_content = style_response.candidates[0].content.parts[0].text
    with open(text_output_file, "w") as f:
        f.write(text_content.strip())
    print(f"Success! Style prompt text saved as '{text_output_file}'")
    text_saved = True

if not image_saved:
    print("No image data was returned by the model.")
if not text_saved:
    print("No text data was returned by the model.")