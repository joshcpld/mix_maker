########################################################################################################################
########################################################################################################################
######################################### ATTACHING METADATA AND CREATING MIXES  #######################################
########################################################################################################################
########################################################################################################################


# Context:
# - We already have a master documentation dataframe with track-level metadata.
# - This script attaches that metadata to the actual audio files and creates:
#     1. Tagged .m4a files with artist/title/album + cover art.
#     2. Per-mix tracklist.txt files with crossfade-aware start times.
#     3. Per-mix crossfaded mix files using ffmpeg.


import os
import shutil
import random
import subprocess
import time

import pandas as pd
from mutagen.mp4 import MP4, MP4Cover

########################################################################################################################
######################################################## CONFIG ########################################################
########################################################################################################################

MUSIC_ROOT         = "data/music"
PAINTINGS_ROOT     = "data/paintings"
MASTER_DOC_PATH    = "data/documentation/documentation_master.csv"
FADE_SEC           = 10        # crossfade length in seconds
BITRATE            = "192k"    # ffmpeg output bitrate
MAX_MIXES_THIS_RUN = 30        # how many mixes to render in this run (for batching)


########################################################################################################################
######################################### 1. LOAD MASTER DOCUMENTATION #################################################
########################################################################################################################

documentation_df = pd.read_csv(MASTER_DOC_PATH)

# One album/mix per distinct mix_name
albums = sorted(documentation_df["mix_name"].dropna().unique())

########################################################################################################################
######################################### 2. LIST AVAILABLE PAINTING FILES #############################################
########################################################################################################################

paintings = [
    f for f in os.listdir(PAINTINGS_ROOT)
    if os.path.isfile(os.path.join(PAINTINGS_ROOT, f))
       and f.lower().endswith((".jpg", ".jpeg", ".png"))
]

print(f"Found {len(albums)} albums and {len(paintings)} paintings.")

########################################################################################################################
######################################## 3. ASSIGN PAINTINGS TO ALBUMS #################################################
########################################################################################################################

# Assign paintings to albums at random without replacement.
# When we exhaust the pool, we reshuffle and start again.
assignment = {}
paintings_pool = paintings.copy()
random.shuffle(paintings_pool)

idx = 0
for album in albums:
    if idx >= len(paintings_pool):
        paintings_pool = paintings.copy()
        random.shuffle(paintings_pool)
        idx = 0

    assignment[album] = paintings_pool[idx]
    idx += 1

album_paintings_df = pd.DataFrame({
    "mix_name": albums,
    "painting_file": [assignment[a] for a in albums]
})

print("\nSample painting assignments:")
print(album_paintings_df.head())

########################################################################################################################
########################### 4. COPY EACH PAINTING INTO ITS ALBUM FOLDER ###############################################
########################################################################################################################

# Map mix_name -> folder from documentation (one row per mix_name/folder pair).
album_folders = (
    documentation_df[["mix_name", "folder"]]
    .dropna()
    .drop_duplicates()
)

album_paintings_with_folders = album_paintings_df.merge(
    album_folders,
    on="mix_name",
    how="left"
)

for _, row in album_paintings_with_folders.iterrows():
    mix_name = row["mix_name"]
    painting_file = row["painting_file"]
    folder = row["folder"]

    if pd.isna(folder) or not isinstance(painting_file, str):
        continue

    src = os.path.join(PAINTINGS_ROOT, painting_file)
    dest_folder = os.path.join(MUSIC_ROOT, folder)
    os.makedirs(dest_folder, exist_ok=True)

    dest = os.path.join(dest_folder, painting_file)

    if os.path.isfile(src):
        if not os.path.exists(dest):
            shutil.copy2(src, dest)
            print(f"[COPIED] {src} -> {dest}")
        else:
            print(f"[SKIP - EXISTS] {dest}")
    else:
        print(f"[MISSING PAINTING] {src}")

########################################################################################################################
####################### 5. MERGE PAINTING ASSIGNMENT INTO TRACK-LEVEL DATA ############################################
########################################################################################################################

documentation_with_art = documentation_df.merge(
    album_paintings_df,
    on="mix_name",
    how="left"
)

########################################################################################################################
##################### 6. TAG EACH AUDIO FILE WITH METADATA + COVER IMAGE ##############################################
########################################################################################################################

def tag_file(row):
    file_path = os.path.join(MUSIC_ROOT, row["folder"], row["file_name"])

    # We only tag .m4a files (mutagen MP4 handler).
    if not file_path.lower().endswith(".m4a"):
        return

    if not os.path.isfile(file_path):
        print(f"[MISSING] {file_path}")
        return

    try:
        audio = MP4(file_path)
    except Exception as e:
        print(f"[ERROR OPENING] {file_path}: {e}")
        return

    if audio.tags is None:
        audio.add_tags()

    # Core tags
    audio["\xa9ART"] = [str(row["artist"])]
    audio["\xa9nam"] = [str(row["title"])]
    audio["\xa9alb"] = [str(row["mix_name"])]

    # Cover art tag from the assigned painting
    painting_file = row.get("painting_file")
    if isinstance(painting_file, str):
        cover_path = os.path.join(PAINTINGS_ROOT, painting_file)
        if os.path.isfile(cover_path):
            with open(cover_path, "rb") as f:
                cover_bytes = f.read()

            ext = os.path.splitext(painting_file)[1].lower()
            if ext in [".jpg", ".jpeg"]:
                cover = MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)
            elif ext == ".png":
                cover = MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_PNG)
            else:
                cover = MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)

            audio["covr"] = [cover]

    try:
        audio.save()
        print(f"[TAGGED + COVER] {file_path}")
    except Exception as e:
        print(f"[ERROR SAVING] {file_path}: {e}")

# Tag all rows in the documentation
documentation_with_art.apply(tag_file, axis=1)

########################################################################################################################
############################################ CREATING TRACKLISTS #######################################################
########################################################################################################################

# Now that everything is tagged, build tracklist.txt for each mix with crossfade-aware timings.

def get_duration(row):
    path = os.path.join(MUSIC_ROOT, row["folder"], row["file_name"])
    if not os.path.isfile(path):
        return None
    try:
        audio = MP4(path)
        return audio.info.length
    except Exception:
        return None

documentation_df["duration"] = documentation_df.apply(get_duration, axis=1)

# Order tracks within each mix and compute crossfade-aware start times:
# start_k = sum_{i<k} d_i - (k-1) * FADE_SEC
documentation_df = documentation_df.sort_values(["mix_name", "file_name"])
documentation_df["track_index"] = documentation_df.groupby("mix_name").cumcount() + 1

documentation_df["idx0"] = documentation_df["track_index"] - 1
documentation_df["cum_dur"] = documentation_df.groupby("mix_name")["duration"].cumsum()
documentation_df["start_sec"] = (
    documentation_df["cum_dur"]
    - documentation_df["duration"]
    - documentation_df["idx0"] * FADE_SEC
)

def format_time(sec):
    if pd.isna(sec):
        return "??:??"
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"

documentation_df["start_time"] = documentation_df["start_sec"].apply(format_time)

# Drop helper columns if not needed later
documentation_df = documentation_df.drop(columns=["idx0", "cum_dur"])

# Initial tracklist.txt per mix (with header)
for mix_name, group in documentation_df.groupby("mix_name"):
    mix_folder = group.iloc[0]["folder"]
    output_path = os.path.join(MUSIC_ROOT, mix_folder, "tracklist.txt")

    lines = []
    lines.append("start time — artist — title")
    lines.append("")

    for _, row in group.iterrows():
        line = f"{row['start_time']} — {row['artist']} — {row['title']}"
        lines.append(line)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Tracklist written to: {output_path}")

# Check which tracklists failed (e.g. due to unknown tracks defaulting to 00:00)
failed = []
for root, dirs, files in os.walk(MUSIC_ROOT):
    if "tracklist.txt" in files:
        path = os.path.join(root, "tracklist.txt")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
            if "00:00 — Unknown — Unknown" in text:
                failed.append(path)

print("Number of failed tracklists:", len(failed))
print("\nFailed tracklists:")
for p in failed:
    print(p)

# These failures correspond to mixes with an "unknown" track where mix_name
# is inconsistent with the rest of the folder. We fix them explicitly.

mapping = {
    60000309: "Car CD 03",
    60131914: "Supermodifed dance 06",
    60020512: "Drm 049 Superchilled 11",
    60020615: "Drm 050 Superchilled 12"
}

documentation_df["mix_name"] = documentation_df.apply(
    lambda row: mapping.get(row["track_no"], row["mix_name"]),
    axis=1
)

########################################################################################################################
########################## REWRITE TRACKLISTS AFTER FIXING MIX NAMES ###################################################
########################################################################################################################

# Recompute durations and start times (same logic as above, now with corrected mix_name).
documentation_df["duration"] = documentation_df.apply(get_duration, axis=1)

documentation_df = documentation_df.sort_values(["mix_name", "file_name"])
documentation_df["track_index"] = documentation_df.groupby("mix_name").cumcount() + 1

documentation_df["idx0"] = documentation_df["track_index"] - 1
documentation_df["cum_dur"] = documentation_df.groupby("mix_name")["duration"].cumsum()
documentation_df["start_sec"] = (
    documentation_df["cum_dur"]
    - documentation_df["duration"]
    - documentation_df["idx0"] * FADE_SEC
)

documentation_df["start_time"] = documentation_df["start_sec"].apply(format_time)
documentation_df = documentation_df.drop(columns=["idx0", "cum_dur"])

# Rewrite tracklist.txt files (now all with the same header format)
for mix_name, group in documentation_df.groupby("mix_name"):
    mix_folder = group.iloc[0]["folder"]
    output_path = os.path.join(MUSIC_ROOT, mix_folder, "tracklist.txt")

    lines = []
    lines.append("start time — artist — title")
    lines.append("")

    for _, row in group.iterrows():
        line = f"{row['start_time']} — {row['artist']} — {row['title']}"
        lines.append(line)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Tracklist written to: {output_path}")

########################################################################################################################
############################################ CREATING MIX TRACKS #######################################################
########################################################################################################################

# Finally, create single crossfaded mix files per folder using ffmpeg.
# Requires ffmpeg installed and available on PATH.

def build_crossfade_mix_for_folder(folder_path, fade_sec=FADE_SEC, bitrate=BITRATE):
    """
    Build a crossfaded mix for all .m4a files in a folder.
    Output file: <folder_name>.m4a in the same folder, with NO metadata.
    """
    folder_abs = os.path.abspath(folder_path)
    print(f"\n=== Processing folder: {folder_abs} ===")

    # Only original track files, skip existing test/xfade outputs.
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
        "-map_metadata", "-1",      # strip all metadata
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

# Use batching so you can run mixes in chunks instead of all at once.
mix_folders = (
    documentation_df[["mix_name", "folder"]]
    .drop_duplicates()
    .reset_index(drop=True)
)

print("Total mixes detected:", len(mix_folders))
print(f"Processing up to {MAX_MIXES_THIS_RUN} mixes in this run.")

for idx, row in mix_folders.head(MAX_MIXES_THIS_RUN).iterrows():
    mix_name = row["mix_name"]
    rel_folder = row["folder"]
    folder_path = os.path.join(MUSIC_ROOT, rel_folder)

    print(f"\n### [{idx+1}] Mix: {mix_name}")
    build_crossfade_mix_for_folder(folder_path)