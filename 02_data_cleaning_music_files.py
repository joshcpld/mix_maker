########################################################################################################################
########################################################################################################################
############################################### DATA CLEANING OF MUSIC FILES  ##########################################
########################################################################################################################
########################################################################################################################

# Dad's entire music collection hinges on the track numbers (8 digits long), which create a link between the 
# file name and music documentation. I now have a robust list of tracks with corresponding mix IDs attached to them 
# (from the previous script).
# 
# However, I need to do a few things with the music files themself before I try and attached their attributes to them.
# I need to understand all the music files better: 

#   * Do they all actually have unique track ID numbers? I am pretty certain there are a few outliers which do not.
#   * Are they all the same format (i.e. mp3 or m4a)? If not, I will likely have to use different library to work
#     work with them.

import os
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import os
import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

########################################################################################################################
##################################################### CONFIG ###########################################################
########################################################################################################################

MUSIC_ROOT           = Path("data/music")
CLEANED_DOC_PATH     = Path("data/documentation/cleaned_permanent_iphone_set_contents.csv")
MASTER_OUTPUT_PATH   = Path("data/documentation/documentation_master.csv")

########################################################################################################################
############################################### CREATING A MUSIC FILE DF  ##############################################
########################################################################################################################

# Build a dataframe with one row per file containing:
#   - file_name
#   - file_type (extension)
#   - folder (immediate parent folder, e.g. mix name)
file_info = []

for folder, _, files in os.walk(MUSIC_ROOT):
    for file in files:
        file_path = os.path.join(folder, file)
        file_name = os.path.basename(file_path)
        file_type = os.path.splitext(file_name)[1].lstrip(".")  # extension without dot
        parent_folder = os.path.basename(folder)

        file_info.append({
            "file_name": file_name,
            "file_type": file_type,
            "folder": parent_folder
        })

df = pd.DataFrame(file_info)

print("Total files found:", len(df))
print(df.head())

########################################################################################################################
############################################### ANALYSING MUSIC FILE DF  ###############################################
########################################################################################################################

# Questions to answer:
#   - How many filenames are exactly 8 digits vs just contain an 8-digit sequence vs other?
#   - What file types exist and in what shares?

def classify_filename(name):
    base = os.path.splitext(name)[0]
    if re.fullmatch(r"\d{8}", base):
        return "8-digit only"
    elif re.search(r"\d{8}", name):
        return "contains 8-digit"
    else:
        return "other"

df["name_category"] = df["file_name"].apply(classify_filename)

# Share of filename categories
name_counts = df["name_category"].value_counts(normalize=True)
ax1 = name_counts.plot(kind="bar", edgecolor="black")
plt.title("Share of file names by pattern")
plt.ylabel("Share")
plt.xticks(rotation=0)

for i, v in enumerate(name_counts.values):
    ax1.text(i, v + 0.01, f"{v:.2%}", ha="center")

plt.tight_layout()
plt.show()

# Share of file types
filetype_counts = df["file_type"].value_counts(normalize=True)
ax2 = filetype_counts.plot(kind="bar", edgecolor="black")
plt.title("Share of file types")
plt.ylabel("Share")
plt.xlabel("File type")

for i, v in enumerate(filetype_counts.values):
    ax2.text(i, v + 0.01, f"{v:.2%}", ha="center")

plt.tight_layout()
plt.show()

# In practice, these are all m4a, so the main complexity is in the filenames rather than file formats.

########################################################################################################################
############################################### FILES WITHOUT 8-DIGIT IDS ##############################################
########################################################################################################################

# The "other" category is the problematic one: files whose names do not contain an 8-digit sequence.
df_other = df.loc[df["name_category"] == "other", ["file_name", "file_type", "folder"]]

print("Files with no 8-digit ID in name:", len(df_other))
print(df_other.head(20))

# Check whether these "other" files are concentrated in specific mixes,
# and whether they represent entire mixes with no IDs at all.
other_counts = df_other.groupby("folder").size().reset_index(name="n_other")
total_counts = df.groupby("folder").size().reset_index(name="n_total")

comparison = other_counts.merge(total_counts, on="folder", how="left")
comparison["share_other"] = comparison["n_other"] / comparison["n_total"]

print("Share of 'other' filenames by folder:")
print(comparison.head(20))

check = (comparison["n_other"] == comparison["n_total"]).all()
print("For folders listed above, are all files 'other' (no IDs)?", check)

print("Number of mixes affected:", len(comparison))

# Interpretation:
# - For these mixes, every file in the folder has no 8-digit ID in its name.
# - Later, we infer IDs by assuming folder order = documentation order,
#   except for known problematic cases (e.g. ZZZZ9908 / Burning Spear album).

########################################################################################################################
############################################### FILES WITH 8-DIGIT IDS #################################################
########################################################################################################################

# Now look at files that either *are* an 8-digit ID or at least contain one.
df_contains = df.loc[df["name_category"] == "contains 8-digit", ["file_name", "file_type", "folder"]]

print("Files whose names contain 8-digit sequences:")
print(df_contains.head(20))

# Extract an 8-digit track_id from the filename
df_contains["track_id"] = df_contains["file_name"].str.extract(r"(\d{8})")
df_contains["valid_track_id"] = df_contains["track_id"].str.fullmatch(r"\d{8}")

print("Sample of extracted track IDs:")
print(df_contains.head(20))

print("Validity of extracted 8-digit IDs:")
print(df_contains["valid_track_id"].value_counts())

# All True => we can safely use these 8-digit segments as track IDs.

########################################################################################################################
########################################## JOINING WITH DOCUMENTATION ##################################################
########################################################################################################################

# Load the cleaned documentation produced by the previous script.
df_documentation = pd.read_csv(CLEANED_DOC_PATH)

########################################################################################################################
########################## HANDLING FILES WITH NO IDS (name_category == 'other') #######################################
########################################################################################################################

# For mixes with no IDs in filenames:
# - Assume track order in the folder matches track order in the documentation.
# - We align them by:
#       * inferring mix_id from folder name
#       * adding a row_number per mix in both dfs
#       * joining on (mix_id, row_number)

df_other = df.loc[df["name_category"] == "other", ["file_name", "file_type", "folder"]].copy()

# Infer mix_id from folder name: first two tokens, then remove the space.
df_other["mix_id"] = (
    df_other["folder"]
    .str.extract(r'^(\S+\s+\S+)', expand=False)
    .str.replace(" ", "", regex=False)
)

# Row index within each mix (1, 2, 3, ...) for alignment with documentation.
df_other["row_number"] = df_other.groupby("mix_id").cumcount() + 1
print("Sample of 'other' files with inferred mix_id and row_number:")
print(df_other.head(20))

# Add matching row_number to documentation so it can be joined 1-to-1 by position.
df_documentation["row_number"] = df_documentation.groupby("mix_id").cumcount() + 1
print("Documentation with row_number sample:")
print(df_documentation.head(20))

# Join "other" files to documentation.
df_other_joined = df_other.merge(
    df_documentation,
    on=["mix_id", "row_number"],
    how="left"
)

# Inspect missing values: we expect NAs where documentation doesn’t truly match (e.g. the Burning Spear mix).
plt.figure(figsize=(12, 6))
sns.heatmap(df_other_joined.isna(), cbar=False, cmap="viridis")
plt.title("NAs in df_other_joined")
plt.tight_layout()
plt.show()

df_other_joined_nans = df_other_joined[df_other_joined.isna().any(axis=1)]
print("Rows with NAs after joining 'other' files:")
print(df_other_joined_nans.head(20))

# As expected, substantial NAs appear only for the known problematic mix; we’re okay with leaving that as unknown.

# Drop row_number now that alignment is done.
df_other_joined.drop(columns=["row_number"], inplace=True)
print("Joined 'other' files:")
print(df_other_joined.head())

########################################################################################################################
########################## HANDLING FILES WITH 8-DIGIT INFO (name_category != 'other') #################################
########################################################################################################################

# For files that either *are* 8-digit IDs or contain one, we extract/clean track_no
# and directly join on track_no to the documentation.

df_eight_digits = df[df["name_category"] != "other"].copy()

# Build track_no:
# - If the filename is exactly an 8-digit ID, strip the ".m4a".
# - Otherwise, extract the first 8-digit sequence.
df_eight_digits["track_no"] = np.where(
    df_eight_digits["name_category"] == "8-digit only",
    df_eight_digits["file_name"].str.replace(".m4a", "", regex=False),
    df_eight_digits["file_name"].str.extract(r'(\d{8})')[0]
)

print("Files with 8-digit-based track_no:")
print(df_eight_digits.head())

# Join with documentation on track_no
df_eight_digits_joined = df_eight_digits.merge(
    df_documentation,
    on="track_no",
    how="left"
)

print("Joined 8-digit files sample:")
print(df_eight_digits_joined.head())

# Check for missing metadata in the join.
plt.figure(figsize=(12, 6))
sns.heatmap(df_eight_digits_joined.isna(), cbar=False, cmap="viridis")
plt.title("NAs in df_eight_digits_joined (before filling unknowns)")
plt.tight_layout()
plt.show()

df_eight_digits_joined_nans = df_eight_digits_joined[df_eight_digits_joined.isna().any(axis=1)]
print("Rows with NAs after joining on track_no:")
print(df_eight_digits_joined_nans)

# A few files have no matching documentation; we label these as unknown tracks.

na_mask = df_eight_digits_joined.isna().any(axis=1)

# Fill missing metadata with "Unknown"
metadata_cols = ["artist", "title", "from_cd_artist", "from_cd_title"]
df_eight_digits_joined.loc[na_mask, metadata_cols] = "Unknown"

# For these unknown rows, derive mix_id and mix_name directly from the folder name.
folder_series = df_eight_digits_joined.loc[na_mask, "folder"]
df_eight_digits_joined.loc[na_mask, ["mix_id", "mix_name"]] = pd.DataFrame({
    "mix_id": folder_series.str.replace(" ", "", regex=False),
    "mix_name": folder_series
}).values

# Flag unknown tracks for reference
df_eight_digits_joined["is_unknown_track"] = na_mask

# Re-check NAs after filling
plt.figure(figsize=(12, 6))
sns.heatmap(df_eight_digits_joined.isna(), cbar=False, cmap="viridis")
plt.title("NAs in df_eight_digits_joined (after filling unknowns)")
plt.tight_layout()
plt.show()

########################################################################################################################
############################################### FINAL CLEAN-UP & EXPORT ################################################
########################################################################################################################

# Remove columns that are only needed for intermediate steps.
df_eight_digits_joined = df_eight_digits_joined.drop(
    columns=["name_category", "unknown", "row_number", "is_unknown_track", "from_cd_title"],
    errors="ignore"  # ignore in case some columns don’t exist in certain runs
)

print("Final master documentation sample:")
print(df_eight_digits_joined.head(20))

df_eight_digits_joined.to_csv(MASTER_OUTPUT_PATH, index=False)
print(f"Master documentation written to: {MASTER_OUTPUT_PATH}")