#!/usr/bin/env python3
"""Render SignalCraft brand assets into README-friendly PNG variants.

Preferred backend: PyMuPDF (fitz) + Pillow.
If those packages are unavailable, the script falls back to a macOS-only path
using `sips` + `swift`.

To enable the preferred backend:
  ./.venv/bin/python -m pip install PyMuPDF Pillow
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import fitz
except Exception:  # pragma: no cover - optional backend
    fitz = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional backend
    Image = None


TARGET_WIDTH = 1024
REPO_ROOT = Path(__file__).resolve().parents[2]
BRAND_DIR = REPO_ROOT / "assets" / "brand"


@dataclass(frozen=True)
class AssetSpec:
    pdf_name: str
    output_prefix: str


ASSETS: tuple[AssetSpec, ...] = (
    AssetSpec("signalcraft-logo.pdf", "signalcraft-logo"),
    AssetSpec("signalcraft-wordmark.pdf", "signalcraft-wordmark"),
)


SWIFT_FALLBACK = r"""
import Foundation
import CoreGraphics
import ImageIO

func median(_ values: [Double]) -> Double {
    if values.isEmpty { return 0.0 }
    let sortedValues = values.sorted()
    let mid = sortedValues.count / 2
    if sortedValues.count % 2 == 0 {
        return (sortedValues[mid - 1] + sortedValues[mid]) / 2.0
    }
    return sortedValues[mid]
}

func loadRGBA(url: URL) -> ([UInt8], Int, Int)? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        return nil
    }

    let width = image.width
    let height = image.height
    let bytesPerPixel = 4
    let bytesPerRow = width * bytesPerPixel

    var pixels = [UInt8](repeating: 0, count: height * bytesPerRow)
    guard let ctx = CGContext(
        data: &pixels,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: bytesPerRow,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        return nil
    }

    ctx.clear(CGRect(x: 0, y: 0, width: width, height: height))
    ctx.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    return (pixels, width, height)
}

func alphaMask(_ pixels: [UInt8], _ width: Int, _ height: Int) -> [UInt8] {
    let bytesPerRow = width * 4
    var hasTransparency = false
    for y in 0..<height {
        for x in 0..<width {
            let a = pixels[y * bytesPerRow + x * 4 + 3]
            if a < 255 {
                hasTransparency = true
                break
            }
        }
        if hasTransparency { break }
    }

    var mask = [UInt8](repeating: 0, count: width * height)
    if hasTransparency {
        for y in 0..<height {
            for x in 0..<width {
                mask[y * width + x] = pixels[y * bytesPerRow + x * 4 + 3]
            }
        }
        return mask
    }

    var border: [Double] = []
    border.reserveCapacity(width * 2 + height * 2)
    for x in 0..<width {
        for y in [0, max(height - 1, 0)] {
            let i = y * bytesPerRow + x * 4
            let r = Double(pixels[i])
            let g = Double(pixels[i + 1])
            let b = Double(pixels[i + 2])
            border.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        }
    }
    for y in 0..<height {
        for x in [0, max(width - 1, 0)] {
            let i = y * bytesPerRow + x * 4
            let r = Double(pixels[i])
            let g = Double(pixels[i + 1])
            let b = Double(pixels[i + 2])
            border.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        }
    }

    let bg = median(border)
    for y in 0..<height {
        for x in 0..<width {
            let i = y * bytesPerRow + x * 4
            let r = Double(pixels[i])
            let g = Double(pixels[i + 1])
            let b = Double(pixels[i + 2])
            let luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            let diff = abs(luma - bg)
            if diff >= 4.0 {
                mask[y * width + x] = UInt8(min(255.0, diff * 6.0))
            }
        }
    }
    return mask
}

func boundingBox(_ mask: [UInt8], _ width: Int, _ height: Int) -> (Int, Int, Int, Int) {
    var minX = width
    var minY = height
    var maxX = -1
    var maxY = -1
    for y in 0..<height {
        for x in 0..<width {
            if mask[y * width + x] > 0 {
                minX = min(minX, x)
                minY = min(minY, y)
                maxX = max(maxX, x)
                maxY = max(maxY, y)
            }
        }
    }

    if maxX < 0 || maxY < 0 {
        return (0, 0, width, height)
    }

    let pad = max(8, Int(Double(min(width, height)) * 0.03))
    let x0 = max(0, minX - pad)
    let y0 = max(0, minY - pad)
    let x1 = min(width, maxX + pad + 1)
    let y1 = min(height, maxY + pad + 1)
    return (x0, y0, x1, y1)
}

func writeVariant(
    mask: [UInt8],
    width: Int,
    height: Int,
    bbox: (Int, Int, Int, Int),
    isDark: Bool,
    outputURL: URL
) -> Bool {
    let (x0, y0, x1, y1) = bbox
    let outW = x1 - x0
    let outH = y1 - y0
    let bytesPerRow = outW * 4

    var outPixels = [UInt8](repeating: 0, count: outW * outH * 4)
    let fill: UInt8 = isDark ? 255 : 0

    for y in 0..<outH {
        for x in 0..<outW {
            let srcX = x + x0
            let srcY = y + y0
            let alpha = mask[srcY * width + srcX]
            let i = y * bytesPerRow + x * 4
            outPixels[i] = fill
            outPixels[i + 1] = fill
            outPixels[i + 2] = fill
            outPixels[i + 3] = alpha
        }
    }

    guard let provider = CGDataProvider(data: Data(outPixels) as CFData),
          let image = CGImage(
              width: outW,
              height: outH,
              bitsPerComponent: 8,
              bitsPerPixel: 32,
              bytesPerRow: bytesPerRow,
              space: CGColorSpaceCreateDeviceRGB(),
              bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
              provider: provider,
              decode: nil,
              shouldInterpolate: true,
              intent: .defaultIntent
          ),
          let dest = CGImageDestinationCreateWithURL(outputURL as CFURL, "public.png" as CFString, 1, nil) else {
        return false
    }

    CGImageDestinationAddImage(dest, image, nil)
    return CGImageDestinationFinalize(dest)
}

let args = CommandLine.arguments
if args.count != 4 {
    fputs("usage: render.swift <baseline_png> <dark_png> <light_png>\n", stderr)
    exit(2)
}

let baseline = URL(fileURLWithPath: args[1])
let darkOut = URL(fileURLWithPath: args[2])
let lightOut = URL(fileURLWithPath: args[3])

guard let (pixels, width, height) = loadRGBA(url: baseline) else {
    fputs("failed to load baseline image\n", stderr)
    exit(3)
}

let mask = alphaMask(pixels, width, height)
let bbox = boundingBox(mask, width, height)

if !writeVariant(mask: mask, width: width, height: height, bbox: bbox, isDark: true, outputURL: darkOut) {
    fputs("failed to write dark variant\n", stderr)
    exit(4)
}

if !writeVariant(mask: mask, width: width, height: height, bbox: bbox, isDark: false, outputURL: lightOut) {
    fputs("failed to write light variant\n", stderr)
    exit(5)
}
"""


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _extract_alpha(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3].astype(np.uint8)
    has_transparency = bool(np.any(alpha < 255))
    if has_transparency:
        return alpha

    rgb = rgba[:, :, :3].astype(np.float32)
    luma = rgb[:, :, 0] * 0.2126 + rgb[:, :, 1] * 0.7152 + rgb[:, :, 2] * 0.0722
    border = np.concatenate((luma[0, :], luma[-1, :], luma[:, 0], luma[:, -1]))
    bg = float(np.median(border))
    diff = np.abs(luma - bg)
    alpha_mask = np.clip(diff * 6.0, 0.0, 255.0).astype(np.uint8)
    alpha_mask[diff < 4.0] = 0
    return alpha_mask


def _crop_alpha(alpha: np.ndarray) -> np.ndarray:
    ys, xs = np.where(alpha > 0)
    if ys.size == 0 or xs.size == 0:
        return alpha

    y0 = int(ys.min())
    y1 = int(ys.max()) + 1
    x0 = int(xs.min())
    x1 = int(xs.max()) + 1
    pad = max(8, int(round(min(alpha.shape[0], alpha.shape[1]) * 0.03)))
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(alpha.shape[0], y1 + pad)
    x1 = min(alpha.shape[1], x1 + pad)
    return alpha[y0:y1, x0:x1]


def _save_variants_with_pillow(alpha: np.ndarray, spec: AssetSpec) -> None:
    dark = np.zeros((alpha.shape[0], alpha.shape[1], 4), dtype=np.uint8)
    dark[:, :, :3] = 255
    dark[:, :, 3] = alpha

    light = np.zeros((alpha.shape[0], alpha.shape[1], 4), dtype=np.uint8)
    light[:, :, 3] = alpha

    dark_path = BRAND_DIR / f"{spec.output_prefix}.dark.png"
    light_path = BRAND_DIR / f"{spec.output_prefix}.light.png"
    Image.fromarray(dark, mode="RGBA").save(dark_path)
    Image.fromarray(light, mode="RGBA").save(light_path)


def _render_with_fitz(spec: AssetSpec) -> None:
    pdf_path = BRAND_DIR / spec.pdf_name
    with fitz.open(pdf_path) as doc:
        page = doc[0]
        zoom = TARGET_WIDTH / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)

    channels = pix.n
    rgba = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, channels))
    if channels == 3:
        alpha_full = np.full((pix.height, pix.width, 1), 255, dtype=np.uint8)
        rgba = np.concatenate([rgba, alpha_full], axis=2)

    alpha = _crop_alpha(_extract_alpha(rgba))
    _save_variants_with_pillow(alpha, spec)


def _render_with_macos_fallback(spec: AssetSpec, swift_script: Path) -> None:
    if shutil.which("sips") is None or shutil.which("swift") is None:
        raise RuntimeError("macOS fallback requires both `sips` and `swift` in PATH")

    pdf_path = BRAND_DIR / spec.pdf_name
    dark_out = BRAND_DIR / f"{spec.output_prefix}.dark.png"
    light_out = BRAND_DIR / f"{spec.output_prefix}.light.png"

    with tempfile.TemporaryDirectory(prefix="signalcraft-brand-") as tmp:
        baseline = Path(tmp) / f"{spec.output_prefix}.baseline.png"
        module_cache = Path(tmp) / "swift-module-cache"
        module_cache.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "sips",
                "-s",
                "format",
                "png",
                str(pdf_path),
                "--resampleWidth",
                str(TARGET_WIDTH),
                "--out",
                str(baseline),
            ]
        )
        _run(
            [
                "swift",
                "-module-cache-path",
                str(module_cache),
                str(swift_script),
                str(baseline),
                str(dark_out),
                str(light_out),
            ]
        )


def main() -> int:
    missing = []
    if fitz is None:
        missing.append("PyMuPDF (fitz)")
    if Image is None:
        missing.append("Pillow")

    use_preferred_backend = not missing

    swift_script_path = None
    if not use_preferred_backend:
        swift_script_path = Path(tempfile.mkdtemp(prefix="signalcraft-brand-swift-")) / "render.swift"
        swift_script_path.write_text(SWIFT_FALLBACK.strip() + "\n", encoding="utf-8")
        print(
            f"Preferred backend unavailable ({', '.join(missing)}). Falling back to macOS renderer.",
            file=sys.stderr,
        )

    for spec in ASSETS:
        pdf_path = BRAND_DIR / spec.pdf_name
        if not pdf_path.exists():
            raise FileNotFoundError(f"Missing source asset: {pdf_path}")

        if use_preferred_backend:
            _render_with_fitz(spec)
        else:
            _render_with_macos_fallback(spec, swift_script_path)

    print("Generated brand PNG variants:")
    for spec in ASSETS:
        print(f"- {BRAND_DIR / (spec.output_prefix + '.dark.png')}")
        print(f"- {BRAND_DIR / (spec.output_prefix + '.light.png')}")

    if missing:
        print(
            "Tip: install PyMuPDF + Pillow for the preferred deterministic backend.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
