#!/usr/bin/env python3
"""
Usage: python3 join_clips.py path/to/file.smil

Can be run like this:
    python3 join_clips.py cam-bpav1/TAKR/BAM_2396/BAM_2396.SMI -ss 300 -t 100 'lut3d=Look_profile_for_resolve_S-Gamut_Slog2/From_SLog2SGumut_To_LC-709TypeA_.cube' 'huesaturation=hue=-10:saturation=-0.25:strength=100,huesaturation=hue=25:saturation=-0.10:colors=r:strength=100,huesaturation=hue=40:saturation=-0.3:colors=m:strength=100,huesaturation=saturation=-0.30:colors=b:strength=100' curves=GimpCurvesConfig.settings=recode260604
"""
import sys
import subprocess
import time
import xml.etree.ElementTree as ET
from math import floor
from pathlib import Path

import re
import configparser
from pathlib import Path

FPS = 25
PARTS_DIR = Path("ffmpeg_parts")
# if True, re-encode when needed (not implemented auto-detect)
REENCODE_ON_NONKEYFRAME = False


CURVES_CONFIG_PATHS = [
    Path.home() / ".config" / "GIMP" / "2.10" /
    "filters" / "GimpCurvesConfig.settings",
    Path.home() / ".config" / "GIMP" / "2.99" /
    "filters" / "GimpCurvesConfig.settings",
    Path.home() / ".var" / "app" / "org.gimp.GIMP" / "config" /
    "GIMP" / "2.10" / "filters" / "GimpCurvesConfig.settings",
    Path.home() / ".var" / "app" / "org.gimp.GIMP" / "config" /
    "GIMP" / "2.99" / "filters" / "GimpCurvesConfig.settings",
]


script_dir = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    # PyInstaller bundle
    script_dir = Path(sys.executable).resolve().parent


def filename_for_index(smilpath: Path, idx: int) -> str:
    # Default mapping: BAM_01.MP4, BAM_02.MP4, ...
    take = smilpath.parent.name
    return smilpath.parent.parent.parent / "CLPR" / f"{take}_{idx:02d}" / f"{take}_{idx:02d}.MP4"


def smpte25_to_ffmpeg_time(tc: str) -> str:
    # Expect format HH:MM:SS:FF
    parts = tc.split(':')
    if len(parts) != 4:
        raise ValueError(f"Unexpected timecode format: {tc}")
    hh, mm, ss, ff = map(int, parts)
    total_seconds = hh * 3600 + mm * 60 + ss + ff / FPS
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds - hours * 3600 - minutes * 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def parse_smil(path: Path):
    ns = {}
    tree = ET.parse(path)
    root = tree.getroot()
    # find all <ref ... clipBegin="smpte-25=..." clipEnd="...">
    refs = []
    for ref in root.findall('.//{*}ref'):
        cb = ref.get('clipBegin')
        ce = ref.get('clipEnd')
        if cb and ce:
            # strip leading "smpte-25="
            if cb.startswith('smpte-25='):
                cb = cb.split('=', 1)[1]
            if ce.startswith('smpte-25='):
                ce = ce.split('=', 1)[1]
            refs.append((cb, ce))
    return refs


def run_single_cmd(*cmd):
    print("Calling:", *cmd)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed: {e}", file=sys.stderr)
        sys.exit(1)


def find_curves_file():
    for p in CURVES_CONFIG_PATHS:
        if p.exists():
            return p
    # fallback: search config dirs for GimpCurvesConfig.settings
    for base in [Path.home() / ".config", Path.home() / ".var" / "app"]:
        for root, dirs, files in os.walk(base):
            if "GimpCurvesConfig.settings" in files:
                return Path(root) / "GimpCurvesConfig.settings"
    raise FileNotFoundError("GimpCurvesConfig.settings not found")


def read_gimp_curves(path: Path, config: str = None):
    text = path.read_text(encoding="utf-8", errors="ignore")
    if config is not None and len(config):
        lines = text.splitlines()
        first, last = 0, -1
        for li, line in enumerate(lines):
            if line.startswith("(GimpCurvesConfig"):
                if config in line:
                    first = li
                elif first > 0:
                    last = li
        # print(first, last)
        text = "".join(lines[first:last])
    # split into channel blocks: either "(channel value)" followed by a (curve ...) block,
    # or "(channel red)" etc. We'll find each "(channel X)" and the next "(curve ... )" block.
    channel_iter = re.finditer(r'\(channel\s+([^\)\s]+)\)', text)
    channels = {}
    for m in channel_iter:
        chan = m.group(1)  # e.g. value, red, green, blue
        # find the (curve ... ) block that follows this channel occurrence
        start = m.end()
        # crude but effective: find the next "(curve" after this position and capture until the matching parenthesis
        curve_pos = text.find("(curve", start)
        if curve_pos == -1:
            continue
        # extract balanced parentheses content for the curve block
        depth = 0
        i = curve_pos
        while i < len(text):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1
        else:
            continue
        curve_block = text[curve_pos:end]
        # find the points line: "(points N a b c d ...)"
        pts_m = re.search(r'\(points\s+([0-9]+)\s+([^\)]+)\)', curve_block)
        if not pts_m:
            channels[chan] = []
            continue
        count = int(pts_m.group(1))
        vals = pts_m.group(2).strip().split()
        # vals should be 2*count floating numbers in normalized 0..1
        nums = [float(v) for v in vals]
        channels[chan] = [(nums[i], nums[i+1])
                          for i in range(0, min(len(nums), 2*count), 2)]
    return channels


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <file.smil>")
        sys.exit(1)
    smil = Path(sys.argv[1])
    if not smil.is_file():
        print("SMIL file not found:", smil)
        sys.exit(1)
    refs = parse_smil(smil)
    if not refs:
        print("No refs parsed from SMIL.")
        sys.exit(1)
    args = sys.argv[2:]
    print(f"Given extra args for ffmpeg: {args}")
    outfn = "joined.mp4"
    PARTS_DIR.mkdir(exist_ok=True)
    files_txt = PARTS_DIR / "files.txt"
    part_cmds = []
    with open(files_txt, "w", encoding="utf-8") as ftxt:
        for i, (cb, ce) in enumerate(refs, start=1):
            partfn = f"part{i:02d}.mp4"
            ftxt.write(f"file '{partfn}'\n")
            outpath = PARTS_DIR / partfn
            src = filename_for_index(smil, i)
            ff_cb = smpte25_to_ffmpeg_time(cb)
            ff_ce = smpte25_to_ffmpeg_time(ce)
            cmd = ["ffmpeg", "-i", str(src), "-ss", ff_cb,
                   "-to", ff_ce, "-c", "copy", str(outpath)]
            part_cmds.append(cmd)
    print("Commands being run for converting each part:")
    print(" ", "\n  ".join(" ".join(cmd) for cmd in part_cmds))
    procs = []
    for cmd in part_cmds:
        outpath = Path(cmd[-1])
        if outpath.is_file():
            continue  # skip exiting files to save time, delete them manually
        procs.append(subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
    # wait for all processes to finish
    while any(proc.poll() is None for proc in procs):
        time.sleep(.5)
    # show their outputs
    for pi, proc in enumerate(procs):
        print(f"# Cmd {pi}: {proc.args}")
        stdout, stderr = proc.communicate()
        if len(stdout):
            print(stdout.decode(), file=sys.stdout)
        if len(stderr):
            print(stderr.decode(), file=sys.stderr)
        if proc.returncode != 0:
            print(f" -> Failed with ({proc.returncode})", file=sys.stderr)
    print(f"\nCreated {files_txt}.\n")
    # convert left/right channel to separate tracks, selectable in VLC player
    # cmd = ["ffmpeg", "-f", "concat", "-safe", "0", "-i", files_txt, "-filter_complex", "[0:a]pan=mono|c0=FL[left];[0:a]pan=mono|c0=FR[right]", "-map", "0:v", "-map", "[left]", "-map", "[right]", "-c:v", "copy", "-c:a:0", "aac", "-b:a", "192k", "-c:a:1", "aac", "-b:a", "192k", "-metadata:s:a:0", "title=Left", "-metadata:s:a:1", "title=Right", "joined_lossless.mp4"]
    # with compression and color conversion
    filterargs = []
    ffmpegargs = []
    skip = []
    for i, arg in enumerate(args):
        print(f"{arg=}")
        if "colortemperature" in arg:
            word = arg.split("=")
            filterargs.append("=".join((word[0], "temperature", word[-1])))
        elif any((key in arg) for key in ("hue", "colorbalance")):
            filterargs.append(arg)
        elif "-ss" in arg:
            skip = args[i:i+2]
            args.pop(i)
        elif arg.startswith("lut3d="):
            lut_path = Path(arg.split("=")[-1])
            if not lut_path.is_file():
                print(f"Given color look-up-tables file not found: '{lut_path}'. Giving up!")
                continue
            print(f"Using look-up-tables from '{lut_path}'.")
            # should be: Look_profile_for_resolve_S-Gamut_Slog2/From_SLog2SGumut_To_LC-709TypeA_.cube
            filterargs.append(f"lut3d=file={lut_path}")
        elif arg.startswith("curves="):
            cvargs = arg.split("=")
            if len(cvargs):
                curves_path = cvargs[1]
            else:
                continue
            curves_config = None
            if len(cvargs) > 2:
                curves_config = cvargs[2]
            # use color correction curves from GIMP, add to filter_opts
            # curves_path = find_curves_file()
            curves_path = Path(curves_path)
            if not curves_path.is_file():
                print(f"Given color curves file not found: '{curves_path}'. Giving up!")
                continue
            print(f"Using GIMP curves from '{curves_path}'.")
            curves = read_gimp_curves(curves_path, curves_config)
            filterargs.append("curves=master='"+" ".join(f"{x:.3f}/{y:.3f}"
                                                         for x, y in curves.get('value', [])) + "'")
        else:
            ffmpegargs.append(arg)
    print(f"{filterargs=}")
    print(f"{ffmpegargs=}")
    print(f"{skip=}")

    # process the original frame from cam, init filter_opts
    ffmpeg_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0"]
    amplify_left_audio = ["-af", "pan=stereo|c0=2.0*c0|c1=c1"]
    filter_opts = "format=yuv420p,"
    origfn = "frame_original.png"
    correctedfn = "frame_corrected.png"
    ffmpeg_cmd = [*ffmpeg_cmd, *skip, "-i", str(files_txt)]
    run_single_cmd(*ffmpeg_cmd, "-vf" if len(filter_opts)
                   else "", filter_opts, "-frames:v", "1", origfn)

    # process the filtered frame
    filter_opts += ",".join(filterargs)
    run_single_cmd(*ffmpeg_cmd, "-vf" if len(filter_opts) else "",
                   filter_opts, "-frames:v", "1", correctedfn)

    answer = input("\n# Joining clips full length now? [Y/n]\n")
    if "n" in answer.lower():
        sys.exit(0)

    otherargs = ["-color_primaries", "bt709", "-color_trc", "bt709",
                "-colorspace", "bt709", "-color_range", "tv"]
    # for approx target file size: compute desired bitrate first
    # bitrate (kbps) = (target_size_MB * 8192) / duration_seconds
    # then 2-pass encoding:
    # ffmpeg -i input.mp4 -c:v libsvtav1 -b:v 1365k -pass 1 -an -f null /dev/null
    # ffmpeg -i input.mp4 -c:v libsvtav1 -b:v 1365k -pass 2 -c:a copy output.mkv
    bitratekb = int(1024 * 1024 * 8 / 7200)  # goal: ~1 GB for 2 hours
    # pass 1:
    cmd = [*ffmpeg_cmd, *ffmpegargs, "-vf" if len(filter_opts) else "", filter_opts,
            "-c:v", "libsvtav1", "-b:v", f"{bitratekb}k", "-pass", "1", *otherargs,
            "-an", "-f", "null", "/dev/null"]
    print(" ".join(cmd))
    run_single_cmd(*cmd)

    cmd = [*ffmpeg_cmd, *ffmpegargs, "-vf" if len(filter_opts) else "", filter_opts,
            "-c:v", "libsvtav1", "-b:v", f"{bitratekb}k", "-pass", "2", *otherargs,
            "-c:a", "libopus", "-b:a", "96k", *amplify_left_audio, outfn]
    # "-metadata:s:a:0", "title=Mic1", "-metadata:s:a:1", "title=Mic2"
    print(" ".join(cmd))
    run_single_cmd(*cmd)


if __name__ == "__main__":
    main()
