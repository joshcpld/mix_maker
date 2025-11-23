########################################################################################################################
########################################################################################################################
######################################### DATA CLEANING OF MUSIC DOCUMENTATION #########################################
########################################################################################################################
########################################################################################################################

# The music my dad gave me does not have artist/release information attached to it. Each song on each mix is titled 
# "Track 01" etc with a serial number which corresponds to a separate documentation word document.

# Goal of this script:
# 1. Clean the exported documentation CSV.
# 2. Build a robust list of mixes and verify it matches the folders in data/music.
# 3. Attach mix IDs and mix names to every track row.
# 4. Export a clean CSV for later use (e.g. tagging files).

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

#########################################################################################################################
##################################################### CONFIG ############################################################
#########################################################################################################################

# Central paths for input and output
DOC_PATH    = Path("data/documentation/permanent_iphone_set_contents.csv")
MUSIC_DIR   = Path("data/music")
OUTPUT_PATH = Path("data/documentation/cleaned_permanent_iphone_set_contents.csv")


#########################################################################################################################
##################################################### IMPORT ############################################################
#########################################################################################################################

# CSV exported from the Word document (after stripping formatting in Word).
df = pd.read_csv(DOC_PATH)

# Standardise column names: strip, lowercase, underscores, remove non-alphanumeric.
df.columns = (
    df.columns
      .str.strip()
      .str.lower()
      .str.replace(r'\s+', '_', regex=True)
      .str.replace(r'[^0-9a-z_]', '', regex=True)
)
print("Columns after normalisation:", df.columns.tolist())

# Rename to simpler names. This block documents how the original export maps to what we use.
df.rename(
    columns={
        'artist': 'artist',
        'title': 'title',
        'track_no_on_cdr': 'track_no',
        'track_no_on_source_cd': 'track_no_source',
        'unnamed_4': 'unknown',
        'from_cd_artist': 'from_cd_artist',
        # Values with 'V' in the original name indicate various artists compilations.
        'from_cd_title__v__various_artists': 'from_cd_title',
    },
    inplace=True
)

print("Columns after rename:", df.columns.tolist())

# Quick NA diagnostics (counts + visual heatmap)
print("NA counts per column:\n", df.isna().sum())

plt.figure(figsize=(12, 6))
sns.heatmap(df.isna(), cbar=False, yticklabels=False, cmap="viridis")
plt.title("Missing values heatmap (True = missing)")
plt.tight_layout()
plt.show()


#########################################################################################################################
################################################ DATA WRANGLING #########################################################
#########################################################################################################################

############################################## ROBUST MIX LIST ##########################################################

# Objective: build a clean list of mixes and check it matches the folders we actually have.
# In the documentation, mix names live in 'from_cd_title' and start with "Z".

mask_Z = df['from_cd_title'].astype(str).str.strip().str.upper().str.startswith('Z', na=False)

# Extract mix names from the documentation (only rows starting with "Z").
mix_names = df.loc[mask_Z].copy()
mix_names = mix_names['from_cd_title'].dropna().astype(str).str.strip().to_frame()

# Sort for easier manual inspection.
mix_names.sort_values(by="from_cd_title", inplace=True)

# Build a mix ID from the first two "tokens" (e.g. "Z 0003" -> "Z0003").
# This helps match slightly different naming conventions between doc and folder names.
mix_names["id"] = (
    mix_names["from_cd_title"]
    .str.extract(r'^(.*? .*?) ', expand=False)   # everything up to the first two spaces
    .str.replace(" ", "", regex=False)          # remove the space, e.g. "Z 0003" -> "Z0003"
)

print(len(mix_names), "mix names found in documentation.")
print(mix_names.head())

# Now check this against the actual folders under data/music.
music_dir = MUSIC_DIR

folders = sorted([p.name for p in music_dir.iterdir() if p.is_dir()])
folders_df = pd.DataFrame(folders, columns=['folder_name'])

# Create an ID column for folders using the same rule as for mix_names.
folders_df["id"] = (
    folders_df["folder_name"]
    .str.extract(r'^(.*? .*?) ', expand=False)
    .str.replace(" ", "", regex=False)
)

print(len(folders_df), "mix folders found on disk.")
print(folders_df.head())

# Merge documentation-based mix list with folder-based mix list to find discrepancies.
mix_list = pd.merge(
    folders_df,
    mix_names,
    on="id",
    how="outer"
)

mix_list = mix_list[['id', 'folder_name', 'from_cd_title']]
print(len(mix_list), "rows in merged mix list.")

# Any row with NA in either side indicates a mix that exists only in the doc or only as a folder.
mix_list_na = mix_list[mix_list.isna().any(axis=1)]
print("Discrepancies between documentation and folders (if any):")
print(mix_list_na.head())

# Some mixes also have descriptive names after the ID.
# For example: "Z 0003 Car CD 03 - mixed dance" -> "Car CD 03 - mixed dance"
mix_list["name"] = mix_list["from_cd_title"].str.split(" ", n=2).str[2]
mix_list = mix_list[["id", "name"]]

print("Distinct mix IDs and names:")
print(mix_list.head(10))

# From here on, we're confident the documentation aligns with the music folders
# (aside from known, acceptable discrepancies like missing files for one mix).
# We can now attach mix IDs directly in the main dataframe.


#########################################################################################################################
############################################## ADDING MIX IDS TO ORIGINAL DF ############################################
#########################################################################################################################

# In the original documentation:
# - Each mix has a "header row" containing the mix info (yellow in the original Word doc).
# - All track rows for that mix follow until the next header row.
#
# The plan:
# 1. Detect header rows.
# 2. Build mix_id and mix_name from those rows.
# 3. Forward-fill mix_id and mix_name down to all track rows.
# 4. Drop the header rows so only track rows remain.

# Header rows are identified via the 'artist' column pattern like "ZZZ_0206".
header_mask = df["artist"].str.match(r'^[Zz]{1,4}_\d+$', na=False)

# Build mix_id from 'from_cd_title' on header rows (same rule as earlier).
df.loc[header_mask, "mix_id"] = (
    df.loc[header_mask, "from_cd_title"]
      .str.extract(r'^(.*? .*?) ', expand=False)
      .str.replace(" ", "", regex=False)
)

# Build mix_name as everything after the first two tokens.
df.loc[header_mask, "mix_name"] = (
    df.loc[header_mask, "from_cd_title"].str.split(" ", n=2).str[2]
)

# Forward-fill so each track inherits the mix_id and mix_name of its header.
df["mix_id"] = df["mix_id"].ffill()
df["mix_name"] = df["mix_name"].ffill()

# Drop the header rows; they’re now redundant.
df = df.loc[~header_mask].reset_index(drop=True)

print("Example rows after attaching mix IDs and names:")
print(df.head())


#########################################################################################################################
########################################## CHECK INTEGRITY OF MIX IDS ###################################################
#########################################################################################################################

# Check that the mix IDs we’ve attached to tracks match the mix IDs we found earlier.
mix_ids_df = (
    df[["mix_id"]]
    .dropna()
    .drop_duplicates()
    .astype({"mix_id": str})
    .reset_index(drop=True)
)

# Use consistent naming for joining/sets.
mix_list = mix_list.rename(columns={"id": "mix_id"})
mix_list["mix_id"] = mix_list["mix_id"].astype(str)

set_left  = set(mix_list["mix_id"])
set_right = set(df["mix_id"].dropna().astype(str).unique())

print("Mix IDs from mix_list:", len(set_left))
print("Mix IDs from tracks:  ", len(set_right))
print("Consistent:", set_left == set_right)

# Optional spot checks for specific mixes.
check_1 = df[df["mix_id"].astype(str).str.strip() == "ZZZ0206"]
print("Spot check for mix_id 'ZZZ0206':")
print(check_1.head(20))

check_2 = df[df["mix_id"].astype(str).str.strip() == "Z1044"]
print("Spot check for mix_id 'Z1044':")
print(check_2.head(20))


#########################################################################################################################
################################################## EXPORT CLEAN DATA ####################################################
#########################################################################################################################

df.to_csv(OUTPUT_PATH, index=False)
print(f"Cleaned documentation written to: {OUTPUT_PATH}")