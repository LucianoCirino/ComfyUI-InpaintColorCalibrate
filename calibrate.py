"""Inpaint colour calibration: measure the colour error a model made on the
redrawn area against the original footage, and undo it.

Why it works: an inpaint mask covers more than the thing being replaced. Most
of the redrawn area is background the model repainted, and the original still
shows its true colour there. The median Lab difference (original - generated)
over those pixels is this render's own colour error. One shift for the whole
clip undoes it, so nothing pumps or blotches.

Which pixels are trusted:
  - with an object mask (what is being removed / replaced), the redrawn area
    minus that object, grown a little;
  - without one, every redrawn pixel, with the ones that look nothing like the
    original (the object) rejected as outliers, iteratively.

Pure torch, no extra dependencies.
"""

import torch
import torch.nn.functional as F

# ---------------------------------------------------------------- colour

_M = torch.tensor([[0.4124564, 0.3575761, 0.1804375],
                   [0.2126729, 0.7151522, 0.0721750],
                   [0.0193339, 0.1191920, 0.9503041]])
_WHITE = torch.tensor([0.95047, 1.0, 1.08883])


def _to_linear(c):
    return torch.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055).clamp(min=0) ** 2.4)


def _to_srgb(c):
    return torch.where(c <= 0.0031308, c * 12.92, 1.055 * c.clamp(min=0) ** (1 / 2.4) - 0.055)


def rgb_to_lab(rgb):
    """[..., 3] sRGB 0..1 -> Lab (L 0..100)."""
    xyz = _to_linear(rgb) @ _M.to(rgb).T / _WHITE.to(rgb)
    e = 216 / 24389
    k = 24389 / 27
    f = torch.where(xyz > e, xyz.clamp(min=1e-12) ** (1 / 3), (k * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return torch.stack([L, a, b], -1)


def lab_to_rgb(lab):
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = torch.stack([fx, fy, fz], -1)
    e = 6 / 29
    xyz = torch.where(f > e, f ** 3, 3 * e * e * (f - 4 / 29)) * _WHITE.to(lab)
    rgb = xyz @ torch.linalg.inv(_M).to(lab).T
    return _to_srgb(rgb).clamp(0, 1)


# ---------------------------------------------------------------- helpers

def _gauss1d(sigma, device):
    r = max(1, int(3 * sigma))
    x = torch.arange(-r, r + 1, device=device, dtype=torch.float32)
    k = torch.exp(-x * x / (2 * sigma * sigma))
    return k / k.sum()


def blur_mask(m, sigma):
    """m [T,H,W] float -> gaussian blurred (separable)."""
    if sigma <= 0:
        return m
    k = _gauss1d(sigma, m.device)
    x = m[:, None]
    x = F.conv2d(F.pad(x, (len(k) // 2, len(k) // 2, 0, 0), mode="replicate"), k.view(1, 1, 1, -1))
    x = F.conv2d(F.pad(x, (0, 0, len(k) // 2, len(k) // 2), mode="replicate"), k.view(1, 1, -1, 1))
    return x[:, 0]


def grow(m, px):
    """m [T,H,W] bool -> dilated by px (square)."""
    if px <= 0:
        return m
    return F.max_pool2d(m.float()[:, None], 2 * px + 1, stride=1, padding=px)[:, 0] > 0.5


def shrink(m, px):
    return ~grow(~m, px)


def _fit(x, h, w, mode):
    """[T,H,W] or [T,H,W,C] to h,w."""
    if x.shape[1] == h and x.shape[2] == w:
        return x
    if x.dim() == 3:
        return F.interpolate(x[:, None].float(), size=(h, w), mode=mode)[:, 0]
    return F.interpolate(x.movedim(-1, 1).float(), size=(h, w), mode=mode).movedim(1, -1)


def _match_len(x, n):
    if x.shape[0] == n:
        return x
    if x.shape[0] == 1:
        return x.expand(n, *x.shape[1:])
    if x.shape[0] > n:
        return x[:n]
    return torch.cat([x, x[-1:].expand(n - x.shape[0], *x.shape[1:])], 0)


# ---------------------------------------------------------------- estimate

def estimate_shift(gen_lab, src_lab, trust, robust=True, max_px=150_000, frame_step=1):
    """Median over frames of the per-frame median (src - gen) on trusted pixels.
    Returns (shift [3], frames_used, mean trusted share)."""
    per = []
    shares = []
    T = gen_lab.shape[0]
    for t in range(0, T, max(1, frame_step)):
        sel = trust[t]
        n = int(sel.sum())
        if n < 64:
            continue
        d = (src_lab[t] - gen_lab[t])[sel]
        if n > max_px:
            d = d[torch.randperm(n, device=d.device)[:max_px]]
        g = d.median(0).values
        if robust:
            for _ in range(5):
                r = (d - g).norm(dim=1)
                k = max(3.0 * float(r.median()), 3.0)
                keep = r < k
                if int(keep.sum()) < 32:
                    break
                g = d[keep].median(0).values
        per.append(g)
        shares.append(n / sel.numel())
    if not per:
        return torch.zeros(3, device=gen_lab.device), 0, 0.0
    return torch.stack(per).median(0).values, len(per), float(sum(shares) / len(shares))


def calibrate(generated, original, mask, object_mask=None, strength=1.0, feather=None,
              edge_skip=None, object_grow=None, robust=True, max_shift=12.0, chunk=24):
    """generated / original: IMAGE [T,H,W,3] 0..1. mask / object_mask: MASK [T,H,W], 1 = redrawn / object.
    Returns (corrected IMAGE, info dict)."""
    T, H, W, _ = generated.shape
    dev = generated.device
    side = min(H, W)
    feather = max(1.0, 0.008 * side) if feather is None else float(feather)
    edge_skip = max(1, int(0.004 * side)) if edge_skip is None else int(edge_skip)
    object_grow = max(4, int(0.015 * side)) if object_grow is None else int(object_grow)

    original = _match_len(_fit(original[..., :3].to(dev), H, W, "bilinear"), T)
    m = _match_len(_fit(mask.to(dev), H, W, "nearest"), T) > 0.5
    om = None
    if object_mask is not None:
        om = _match_len(_fit(object_mask.to(dev), H, W, "nearest"), T) > 0.5

    # trusted pixels: inside the mask, away from its very edge (blend / VAE bleed), minus the object
    trust = shrink(m, edge_skip)
    if om is not None:
        trust = trust & ~grow(om, object_grow)

    # estimate on a half-size copy (fast, and the shift is low frequency)
    s = 2 if side >= 512 else 1
    def small(x):
        return x if s == 1 else F.avg_pool2d(x.movedim(-1, 1), s).movedim(1, -1)
    tr_small = trust if s == 1 else (F.avg_pool2d(trust.float()[:, None], s)[:, 0] > 0.99)
    gl = torch.cat([rgb_to_lab(small(generated[i:i + chunk, ..., :3].float())) for i in range(0, T, chunk)])
    sl = torch.cat([rgb_to_lab(small(original[i:i + chunk].float())) for i in range(0, T, chunk)])
    use_robust = robust or om is None
    shift, used, share = estimate_shift(gl, sl, tr_small, robust=use_robust, frame_step=1 if T <= 96 else 2)
    del gl, sl
    shift = shift.clamp(-max_shift, max_shift) * float(strength)

    # apply inside the mask, feathered just past its edge
    out = torch.empty_like(generated)
    for i in range(0, T, chunk):
        mm = m[i:i + chunk].float()
        w = torch.maximum(blur_mask(mm, feather), mm)[..., None]
        g = generated[i:i + chunk]
        lab = rgb_to_lab(g[..., :3].float())
        rgb = lab_to_rgb(lab + shift.view(1, 1, 1, 3) * w)
        o = g.clone()
        o[..., :3] = (g[..., :3].float() * (1 - w) + rgb * w).to(g.dtype)
        out[i:i + chunk] = o
    info = {"shift_L": round(float(shift[0]), 3), "shift_a": round(float(shift[1]), 3),
            "shift_b": round(float(shift[2]), 3), "frames_used": used,
            "trusted_share_of_frame": round(share, 4),
            "method": "object-masked" if om is not None else ("robust" if use_robust else "plain")}
    return out, info
