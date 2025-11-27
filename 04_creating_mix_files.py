########################################################################################################################
########################################################################################################################
############################################ CREATE MIX FILES ONLY #####################################################
########################################################################################################################
########################################################################################################################

# This script:
#   - DOES NOT reassign or copy any artwork
#   - DOES NOT retag individual track files
# It only:
#   1. Reads documentation_master.csv to find mix folders
#   2. Builds crossfaded mix files with ffmpeg
#   3. Attaches the existing folder artwork (jpg/png) to each mix file

import os
import subprocess
import time

import pandas as pd
from mutagen.mp4 import MP4, MP4Cover

########################################################################################################################
######################################################## CONFIG ########################################################
########################################################################################################################

MUSIC_ROOT         = "data/music"
MASTER_DOC_PATH    = "data/documentation/documentation_master.csv"
FADE_SEC           = 10        # crossfade length in seconds
BITRATE            = "192k"    # ffmpeg output bitrate
MAX_MIXES_THIS_RUN = 62       # or set to a smaller number if you want to batch

########################################################################################################################
######################################### 1. LOAD MASTER DOCUMENTATION #################################################
########################################################################################################################

documentation_df = pd.read_csv(MASTER_DOC_PATH)

# Unique mix_name / folder pairs
mix_folders = (
    documentation_df[["mix_name", "folder"]]
    .dropna()
    .drop_duplicates()
    .reset_index(drop=True)
)

print("Total mixes detected:", len(mix_folders))
print(f"Processing up to {MAX_MIXES_THIS_RUN} mixes in this run.")


########################################################################################################################
############################################ CREATING MIX TRACKS #######################################################
########################################################################################################################

def build_crossfade_mix_for_folder(folder_path, fade_sec=FADE_SEC, bitrate=BITRATE):
    """
    Build a crossfaded mix for all .m4a files in a folder.
    Output file: <folder_name>.m4a in the same folder.
    Does not modify individual track files.
    """
    folder_abs = os.path.abspath(folder_path)
    print(f"\n=== Processing folder: {folder_abs} ===")

    if not os.path.isdir(folder_abs):
        print("⚠️  Folder does not exist, skipping.")
        return

    # Only original track files, skip existing test/xfade/mix outputs.
    files = [
        f for f in os.listdir(folder_abs)
        if f.lower().endswith(".m4a")
        and "test" not in f.lower()
        and "xfade" not in f.lower()
    ]
    files.sort()

    print("Found track files:", files)
    if len(files) < 2:
        print("⚠️  Not enough tracks (need at least 2). Skipping.")
        return

    input_paths = [os.path.join(folder_abs, f) for f in files]

    # Output file named after the folder (mix).
    mix_name = os.path.basename(folder_abs)
    output_file = os.path.join(folder_abs, f"{mix_name}.m4a")

    if os.path.exists(output_file):
        print("✅ Output already exists, skipping:", output_file)
        return

    cmd = ["ffmpeg", "-y"]  # overwrite without asking

    # Add each track as an input.
    for p in input_paths:
        print("Input:", p, "| exists:", os.path.isfile(p))
        cmd.extend(["-i", p])

    # Build the acrossfade filter chain.
    filter_parts = []
    prev_label = "0:a"

    for i in range(1, len(input_paths)):
        in_label = f"{i}:a"
        out_label = f"a{i:02d}"
        part = (
            f"[{prev_label}][{in_label}]"
            f"acrossfade=d={fade_sec}:c1=tri:c2=tri"
            f"[{out_label}]"
        )
        filter_parts.append(part)
        prev_label = out_label

    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", f"[{prev_label}]",  # final mixed audio
        "-map_metadata", "-1",      # strip all metadata from inputs
        "-c:a", "aac",
        "-b:a", bitrate,
        output_file,
    ])

    print("\nRunning command:")
    print(" ".join(cmd), "\n")

    start = time.time()
    process = subprocess.Popen(cmd)
    process.wait()
    elapsed_min = (time.time() - start) / 60

    if process.returncode == 0:
        print(f"🎉 Done: {output_file}")
        print(f"⏱  Elapsed time: {elapsed_min:.2f} minutes")

    else:
        print("❌ ffmpeg failed:", process.returncode)

########################################################################################################################
############################################ RUN OVER ALL MIX FOLDERS ##################################################
########################################################################################################################

for idx, row in mix_folders.head(MAX_MIXES_THIS_RUN).iterrows():
    mix_name = row["mix_name"]
    rel_folder = row["folder"]
    folder_path = os.path.join(MUSIC_ROOT, rel_folder)

    print(f"\n### [{idx+1}] Mix: {mix_name} (folder: {rel_folder})")
    build_crossfade_mix_for_folder(folder_path)