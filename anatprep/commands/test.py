from anatprep.vendor.pymp2rage import MP2RAGE
import json

# Load params
with open('/data/projects/7T079_Visual_Changes_after_Eye_Amputation/7T079_pilot/code/mp2rage.json') as f:
    params = json.load(f)

# Use actual paths from your run-1
fitter = MP2RAGE(
    MPRAGE_tr=params["RepetitionTimePreparation"],
    invtimesAB=params["InversionTime"],
    flipangleABdegree=params["FlipAngle"],
    nZslices=params["NumberShots"],
    FLASH_tr=[params["RepetitionTimeExcitation"], params["RepetitionTimeExcitation"]],
    inv1="/data/projects/7T079_Visual_Changes_after_Eye_Amputation/7T079_pilot/rawdata/sub-7T079C02/ses-MR1/anat/sub-7T079C02_ses-MR1_run-1_inv-1_part-mag_MP2RAGE.nii.gz",
    inv1ph="/data/projects/7T079_Visual_Changes_after_Eye_Amputation/7T079_pilot/rawdata/sub-7T079C02/ses-MR1/anat/sub-7T079C02_ses-MR1_run-1_inv-1_part-phase_MP2RAGE.nii.gz",
    inv2="/data/projects/7T079_Visual_Changes_after_Eye_Amputation/7T079_pilot/rawdata/sub-7T079C02/ses-MR1/anat/sub-7T079C02_ses-MR1_run-1_inv-2_part-mag_MP2RAGE.nii.gz",
    inv2ph="/data/projects/7T079_Visual_Changes_after_Eye_Amputation/7T079_pilot/rawdata/sub-7T079C02/ses-MR1/anat/sub-7T079C02_ses-MR1_run-1_inv-2_part-phase_MP2RAGE.nii.gz",
)

# Basic fitting (should work)
print("T1w_uni shape:", fitter.t1w_uni.shape)
print("T1map shape:", fitter.t1map.shape)

# B1 correction (will show full traceback)
fitter.correct_for_B1("/data/projects/7T079_Visual_Changes_after_Eye_Amputation/7T079_pilot/rawdata/sub-7T079C02/ses-MR1/fmap/sub-7T079C02_ses-MR1_acq-dream_run-1_TB1map.nii.gz")
