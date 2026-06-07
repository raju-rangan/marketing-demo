"""
Proxy for the modularized slidecast tools.
All logic has been moved to the .slidecast/ package.
"""
from .slidecast import (
    generate_slidecast_storyboard,
    update_slidecast_slide,
    update_storyboard_visual_style,
    preview_slidecast_assets,
    finalize_slidecast_video,
    select_slidecast_style,
    generate_slide_animation_plan,
    execute_slide_animation,
)

__all__ = [
    "generate_slidecast_storyboard",
    "update_slidecast_slide",
    "update_storyboard_visual_style",
    "preview_slidecast_assets",
    "finalize_slidecast_video",
    "select_slidecast_style",
    "generate_slide_animation_plan",
    "execute_slide_animation",
]
