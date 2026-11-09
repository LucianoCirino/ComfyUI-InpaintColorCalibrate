"""ComfyUI-InpaintColorCalibrate: undo the colour cast a model paints into an inpainted area."""

from .calibrate import calibrate


class InpaintColorCalibrate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "generated": ("IMAGE", {"tooltip": "The inpaint result (video frames or an image)."}),
                "original": ("IMAGE", {"tooltip": "The source it was made from."}),
                "mask": ("MASK", {"tooltip": "The inpaint mask, white = redrawn."}),
                "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
            },
            "optional": {
                "object_mask": ("MASK", {"tooltip": "Optional: what you removed or replaced (e.g. a SAM mask). Better results."}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "run"
    CATEGORY = "image/inpaint"
    DESCRIPTION = "Fixes the colour cast in an inpainted area by comparing it with the original. Use after the decode."

    def run(self, generated, original, mask, strength, object_mask=None):
        if mask.dim() == 2:
            mask = mask[None]
        if object_mask is not None and object_mask.dim() == 2:
            object_mask = object_mask[None]
        out, info = calibrate(generated, original, mask, object_mask=object_mask, strength=strength)
        print(f"[InpaintColorCalibrate] {info}")
        return (out,)


NODE_CLASS_MAPPINGS = {"InpaintColorCalibrate": InpaintColorCalibrate}
NODE_DISPLAY_NAME_MAPPINGS = {"InpaintColorCalibrate": "Inpaint Color Calibrate"}
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
