from __future__ import annotations

import argparse
import ctypes
import sys
import tempfile
from pathlib import Path

from ctypes import wintypes

import requests

try:
    import win32api
    import win32con
    import win32gui
    import win32ui
    from PIL import Image, ImageChops, ImageOps
except Exception:
    win32api = None
    win32con = None
    win32gui = None
    win32ui = None
    Image = None


def extract_icon(exe_path: str | Path, out_png_path: str | Path, size: int = 256) -> Path:
    if win32gui is None or win32ui is None or win32con is None or win32api is None or Image is None:
        raise RuntimeError("pywin32 and Pillow are required for icon extraction")

    exe_path = str(exe_path)
    out_png_path = Path(out_png_path)

    def private_extract_icon(target_size: int) -> int | None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
            PrivateExtractIconsW = user32.PrivateExtractIconsW
            PrivateExtractIconsW.argtypes = [
                wintypes.LPCWSTR,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(HICON),
                ctypes.POINTER(wintypes.UINT),
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            PrivateExtractIconsW.restype = ctypes.c_uint

            hicon = HICON()
            icon_id = wintypes.UINT()
            count = PrivateExtractIconsW(exe_path, 0, target_size, target_size, ctypes.byref(hicon), ctypes.byref(icon_id), 1, 0)
            if int(count) > 0 and int(hicon.value) != 0:
                return int(hicon.value)
        except Exception:
            return None
        return None

    def hicon_to_rgba(hicon: int) -> Image.Image:
        info = win32gui.GetIconInfo(hicon)
        hbm_mask = info[3]
        hbm_color = info[4]

        try:
            if hbm_color:
                bmp = win32ui.CreateBitmapFromHandle(hbm_color)
                bmpinfo = bmp.GetInfo()
                w, h = int(bmpinfo["bmWidth"]), int(bmpinfo["bmHeight"])
                bits = bmp.GetBitmapBits(True)
                img = Image.frombuffer("RGBA", (w, h), bits, "raw", "BGRA", 0, 1)
            else:
                hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
                hbmp = win32ui.CreateBitmap()
                hbmp.CreateCompatibleBitmap(hdc, size, size)
                hdc_mem = hdc.CreateCompatibleDC()
                hdc_mem.SelectObject(hbmp)
                hdc_mem.FillSolidRect((0, 0, size, size), 0x000000)
                hdc_mem.DrawIcon((0, 0), hicon)
                bmpinfo = hbmp.GetInfo()
                bmpstr = hbmp.GetBitmapBits(True)
                img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1).convert("RGBA")

            if hbm_mask and img.getchannel("A").getextrema() == (255, 255):
                try:
                    mask_bmp = win32ui.CreateBitmapFromHandle(hbm_mask)
                    minfo = mask_bmp.GetInfo()
                    mw, mh = int(minfo["bmWidth"]), int(minfo["bmHeight"])
                    mbits = mask_bmp.GetBitmapBits(True)
                    stride = ((mw + 31) // 32) * 4
                    mask_img = Image.frombuffer("1", (mw, mh), mbits, "raw", "1;I", stride, 1)
                    if mh == img.size[1] * 2:
                        mask_img = mask_img.crop((0, 0, mw, img.size[1]))
                    alpha = ImageOps.invert(mask_img.convert("L"))
                    img.putalpha(alpha)
                except Exception:
                    pass

            return img
        finally:
            try:
                if hbm_color:
                    win32gui.DeleteObject(hbm_color)
            except Exception:
                pass
            try:
                if hbm_mask:
                    win32gui.DeleteObject(hbm_mask)
            except Exception:
                pass

    def normalize(img: Image.Image) -> Image.Image:
        img = img.convert("RGBA")
        alpha = img.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            bg = Image.new("RGBA", img.size, (0, 0, 0, 0))
            diff = ImageChops.difference(img, bg)
            bbox = diff.getbbox()
        if bbox is None:
            bbox = (0, 0, img.size[0], img.size[1])

        cropped = img.crop(bbox)
        w, h = cropped.size
        target = int(size * 0.92)
        scale = min(target / max(1, w), target / max(1, h))
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))

        resample = Image.Resampling.NEAREST if max(w, h) < 64 else Image.Resampling.LANCZOS
        resized = cropped.resize((new_w, new_h), resample=resample)

        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(resized, ((size - new_w) // 2, (size - new_h) // 2), resized)
        return out

    hicon = private_extract_icon(size)
    if hicon is None:
        large, small = win32gui.ExtractIconEx(exe_path, 0)
        if large:
            hicon = large[0]
        elif small:
            hicon = small[0]

    if hicon is None:
        raise RuntimeError("No icon found")

    try:
        img = hicon_to_rgba(int(hicon))
        out = normalize(img)
        out.save(out_png_path, format="PNG")
    finally:
        try:
            win32gui.DestroyIcon(hicon)
        except Exception:
            pass

    return out_png_path


def upload_to_litterbox(file_path: str | Path, *, time_to_live: str = "72h", timeout_seconds: float = 30.0) -> str:
    file_path = Path(file_path)
    url = "https://litterbox.catbox.moe/resources/internals/api.php"

    ttl = str(time_to_live).strip().lower()
    if ttl not in {"1h", "12h", "24h", "72h"}:
        raise ValueError("time_to_live must be one of: 1h, 12h, 24h, 72h")

    with file_path.open("rb") as f:
        response = requests.post(
            url,
            data={"reqtype": "fileupload", "time": ttl},
            files={"fileToUpload": (file_path.name, f)},
            timeout=timeout_seconds,
        )

    response.raise_for_status()
    text = (response.text or "").strip()
    if not text.startswith("http"):
        raise RuntimeError(f"Unexpected Litterbox response: {text}")
    return text


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="icons")
    parser.add_argument("--exe", required=True)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--png-out", default="")
    parser.add_argument("--ttl", choices=["1h", "12h", "24h", "72h"], default="72h")
    args = parser.parse_args(argv)

    try:
        if args.png_out:
            png_path = Path(args.png_out)
        else:
            png_path = Path(tempfile.gettempdir()) / "renpy-discord-rpc-icon.png"

        extract_icon(args.exe, png_path, size=int(args.size))

        url = upload_to_litterbox(png_path, time_to_live=str(args.ttl), timeout_seconds=float(args.timeout))
        print(url)
        return 0
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
