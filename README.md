# ComfyUI-InpaintColorCalibrate

One node that fixes the colour cast in an inpainted area. It works on video or
images, with any model (MiniMax H3, Wan, LTX, Flux...).

## Why

Inpainted areas rarely match the original's colour, so you get a seam. MiniMax H3,
for example, made the inpainted area slightly darker and yellower in almost every test, with every turbo LoRA and without one.

## How

Most of an inpaint mask is plain background the model painted again, and the
original still shows that background's real colour. The node compares the two,
measures the colour error, and removes it from the whole inpainted area. That's one
correction for the whole clip, so nothing flickers.

## Use

Put it right after the decode:

| input | |
|---|---|
| `generated` | the inpaint result |
| `original` | the source it was made from |
| `mask` | the inpaint mask (white = redrawn) |
| `strength` | 1.0 = full correction |
| `object_mask` | optional: what you removed (e.g. a SAM mask). Better results. |

Ready-made workflows (video and image) are in [`example_workflows/`](example_workflows).

## Results

Tested on MiniMax H3 inpaints where the right answer is known (background redrawn, or
an object removed from a clean clip), on 10 clips. Colour error of the inpainted area
against the truth (ΔE, lower is better): **45.1 without, 30.5 with**. It made none of
them worse.

The correction is usually small (1 to 3 ΔE). It matters when the inpainted area
visibly doesn't match its surroundings, like a yellow or darker patch at the mask edge.
When there is no visible mismatch, it changes very little.

## Install

```
cd ComfyUI/custom_nodes
git clone https://github.com/LucianoCirino/ComfyUI-InpaintColorCalibrate
```

## Limits

- It fixes colour and brightness, not texture or sharpness.
- Leave some margin in the mask around the object.
- If what you removed was lighting or shadowing its surroundings, the measurement includes that.

## License

MIT
