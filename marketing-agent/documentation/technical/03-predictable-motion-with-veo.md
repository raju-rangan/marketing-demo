# Predictable Motion: How to Put a Leash on Generative Video 

**By Raju Rangan, Google AI Specialist**

In my last post, we talked about how hard it is to get a Generative AI image model to follow the rules, and how we solved it using a VLM-as-a-Judge. We successfully built a bulletproof, brand-compliant static storyboard. 

But a storyboard is just a bunch of pictures. We are here to make videos.

Here is where the real nightmare usually begins. If you hand those beautiful, compliant storyboard frames over to a standard Text-to-Video AI model and say, "Animate this," you are going to want to pull your hair out.

Generative video models (like Veo) are incredibly powerful, but they have a mind of their own. They might start the clip beautifully using your image, but by second 3, the presenter's face has morphed, the background has changed from a corporate office to a beach, and the video ends with the subject walking off-screen in the middle of a sentence.

When you are building the **GenAI Content Engine** for a financial institution, "the AI wandered off-topic" is not an acceptable excuse. We need absolute, predictable motion. Here is how we put a leash on the `veo-3.1-generate-001` model.

### The Predictability Problem

The fundamental issue with AI video generation is drift. 

If your storyboard dictates that Scene 1 must end with a close-up of a specific bar chart so that it can transition perfectly into Scene 2, the video model *cannot* be allowed to hallucinate a different ending. 

If we use a standard "Image-to-Video" approach, we only give the model a starting frame. Veo will animate it flawlessly, but because it doesn't know where it's supposed to end up, it just keeps inventing new pixels until the timer runs out. It might end the clip mid-motion, making it impossible to stitch seamlessly into the next scene.

### The Hack: First and Last Frame Conditioning

To solve this, we stopped letting the model guess the ending. Instead of just giving Veo a starting frame, we give it the start frame *and* the end frame, and tell it to figure out the math in between.

This is called **First and Last Frame Conditioning**. 

Because we already generated all the static keyframes in the Storyboard phase (and verified them using our VLM Judge), we possess the perfect puzzle pieces. 

When the orchestrator calls the Veo generation tool (`app/tools/tools_media.py`), it doesn't just pass a text prompt. It passes three things:
1. **Start Frame:** The verified image that the clip MUST start with.
2. **End Frame:** The verified image that the clip MUST end on.
3. **Text Prompt:** The description of the motion connecting them (e.g., "The camera slowly pans out").

### Looking at the Code

Under the hood, this requires passing a very specific array of `InputMedia` objects to the Veo configuration. Here is a simplified look at how we force the model's hand:

```python
# Inside _generate_single_veo_clip()
async def generate_predictable_clip(start_image_uri: str, end_image_uri: str, prompt: str):
    
    # 1. Lock in the beginning
    input_frames = [
        types.InputMedia(gcs_uri=start_image_uri, type=types.InputMediaType.IMAGE)
    ]
    
    # 2. Lock in the ending. This prevents the model from wandering.
    if end_image_uri:
        input_frames.append(
            types.InputMedia(gcs_uri=end_image_uri, type=types.InputMediaType.IMAGE)
        )

    # 3. Force Veo to respect the boundaries
    veo_config = types.GenerateVideosConfig(
        number_of_videos=1,
        fps=24,
        input_media=input_frames # The leash is applied here
    )
    
    # Trigger the veo-3.1-generate-001 model...
```

### Why Developers Should Care

This isn't just a neat trick for making smoother videos; it is a fundamental architectural shift in how we control AI.

By using the `end_frame_gcs_uri`, we are mathematically forcing the model to interpolate between two known, brand-compliant states. The resulting video *has* to be predictable. It literally cannot end in the middle of an awkward rendering, because the final frame is forced to match the static End Frame.

By constraining the model at both ends, every generated clip acts as a perfect, predictable puzzle piece. 

In the final post of this series, I'll show you exactly what we do with those puzzle pieces, and how we use FFmpeg and "End Padding" to stitch them together into a final cinematic commercial that feels like it was edited by a human.