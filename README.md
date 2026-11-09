# ComfyUI-InpaintColorCalibrate

One node that fixes the colour cast in an inpainted area. It works on video or
images, with any model (MiniMax H3, Wan, LTX, Flux...).

## Why

Inpainted areas rarely match the original's colour, so you get a seam. MiniMax H3,
for example, made the inpainted area darker in 16 of 17 tests and yellower in 15.

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

Example workflows (video and image) are in [`example_workflows/`](example_workflows).

## Results

A person was pasted into 7 clean clips and removed with MiniMax H3. The clean
original is the right answer. The table shows colour error (ΔE) of the inpainted area,
lower is better:

| | no fix | with object mask | without |
|---|---|---|---|
| total over 7 clips | 27.1 | **16.8** | **17.0** |

That's about 90% of the best possible single correction. On 23 more tests it helped
22 and was negligibly worse on 1. Matching colour to a ring around the mask, the usual
trick, made 6 of 17 clips worse.

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
