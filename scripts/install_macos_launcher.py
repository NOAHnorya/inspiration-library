import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from string import Template

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="安装灵感库 macOS 桌面启动器")
    parser.add_argument("--name", default="灵感库")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--desktop", default=str(Path.home() / "Desktop"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if not sys.platform == "darwin":
        raise ValueError("桌面启动器仅支持 macOS")
    target = Path(args.desktop).expanduser().resolve() / (args.name + ".app")
    if target.exists():
        info_path = target / "Contents" / "Info.plist"
        if not args.replace or not info_path.exists():
            raise ValueError("目标应用已存在；只有更新本工具创建的应用时才使用 --replace: " + str(target))
        with info_path.open("rb") as handle:
            if plistlib.load(handle).get("CFBundleIdentifier") != "local.inspiration-library.launcher":
                raise ValueError("拒绝覆盖非灵感库应用: " + str(target))
    contents = target / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    (contents / "Resources").mkdir(parents=True, exist_ok=True)
    info = {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleDisplayName": args.name,
        "CFBundleExecutable": "launch.py",
        "CFBundleIconFile": "inspiration",
        "CFBundleIdentifier": "local.inspiration-library.launcher",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": args.name,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle)
    template = Template((ROOT / "scripts" / "launcher_template.py").read_text(encoding="utf-8"))
    launcher = template.substitute(project_root=repr(str(ROOT)), python_executable=repr(str(Path(args.python).resolve())), port=args.port)
    executable = contents / "MacOS" / "launch.py"
    executable.write_text(launcher, encoding="utf-8")
    os.chmod(executable, 0o755)
    source = Image.open(ROOT / "assets" / "inspiration-icon.png")
    iconset = contents / "Resources" / "inspiration.iconset"
    iconset.mkdir(exist_ok=True)
    for name, size in [("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64),
                       ("128x128", 128), ("128x128@2x", 256), ("256x256", 256), ("256x256@2x", 512),
                       ("512x512", 512), ("512x512@2x", 1024)]:
        source.resize((size, size), Image.Resampling.LANCZOS).save(iconset / ("icon_" + name + ".png"))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(contents / "Resources" / "inspiration.icns")], check=True)
    for path in sorted(iconset.iterdir()):
        path.unlink()
    iconset.rmdir()
    target.touch()
    print({"ok": True, "app": str(target), "port": args.port})


if __name__ == "__main__":
    main()
