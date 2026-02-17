# anatprep

Anatomical preprocessing pipeline for 7T MP2RAGE data.

Takes BIDS-organized rawdata (from [7T_BIDS_Organiser](https://github.com/RioPhillips/7T_BIDS_Organiser)) through pymp2rage fitting, SPM masking, denoising, CAT12 segmentation, sinus masking, and iterative brainmask refinement with fMRIprep - based on the [Knapen anatomical workflow](https://github.com/tknapen/tknapen.github.io/wiki/Anatomical-workflows) and the [linescanning repo](https://github.com/gjheij/linescanning) by Heij. 


## Installation

```bash
# Create conda environment
conda env create -f environment.yml
conda activate anatprep

# Install the package 
pip install git+https://github.com/RioPhillips/7T_anatprep.git

# or editable with dev dependencies
git clone https://github.com/RioPhillips/7T_anatprep.git
pip install -e ".[dev]"
```

### Dependencies

- **MATLAB** + **SPM12/25** + **CAT12** + "Image Processing" toolbox (for `spm-mask` and `cat12`)
- **FSL** (for FLIRT coregistration in `sinus-auto`)
- **Docker** (for fMRIprep)
- **ITK-Snap** (for manual mask editing)
- **FreeSurfer license** (for fMRIprep)


## Setup

anatprep expects the same study directory structure as 7T_BIDS_organiser:

```
my_study/
├── code/
│   ├── config.json              # dcm2bids config
│   ├── mp2rage.json             # MP2RAGE parameters
│   └── anatprep_config.yml      # anatprep config
├── rawdata/                     # BIDS rawdata from dcm2bids
│   └── sub-S01/
│       └── ses-MR1/
│           └── anat/
└── derivatives/                 # anatprep writes here
    ├── anatprep/
    ├── fmriprep/
    └── freesurfer/
```

### code/anatprep_config.yml

```yaml
tools:
  spm_path: "/path/to/spm"
  matlab_cmd: "/path/to/matlab"
  freesurfer:
    license: "/path/to/license.txt"
  fmriprep:
    docker_image: "nipreps/fmriprep:latest"
    n_threads: 8
    mem_mb: 32000
```

See `configs/example_anatprep_config.yml` for a full example.


## Usage

### Step by step

```bash
cd /path/to/my_study


# 1. Compute T1w + T1map
anatprep pymp2rage --subject S01 --session MR1

# 2. Brain mask from INV2
anatprep mask --subject S01 --session MR1 ( + either --bet or --spm)

# 3. Remove background noise
anatprep denoise --subject S01 --session MR1

# 4. CAT12 segmentation
anatprep cat12 --subject S01 --session MR1

# 5. Auto-generate sinus mask
anatprep sinus-auto --subject S01 --session MR1

# 6. Manual sinus mask editing
anatprep sinus-edit --subject S01 --session MR1

# 7. Run fMRIprep (iteration 1)
anatprep fmriprep --subject S01 --session MR1

# 8. Check status
anatprep status --subject S01

# 9. Refine brainmask if needed
anatprep brainmask-edit --subject S01 --session MR1

# 10. Re-run fMRIprep (iteration 2)
anatprep fmriprep --subject S01 --session MR1

# ... repeat 8-10 until satisfied ...
```

### Process all sessions

Omit `--session` to process all sessions for a subject:

```bash
anatprep mask --subject S01 --bet
anatprep pymp2rage --subject S01
# etc.
```

### Check status

```bash
# Overview of all subjects
anatprep status

# Detailed status for one subject
anatprep status --subject S01 --verbose
```


## Output structure

```
derivatives/anatprep/
└── sub-S01/
    └── ses-MR1/
        ├── sub-S01_ses-MR1_run-1_desc-spmmask_mask.nii.gz
        ├── sub-S01_ses-MR1_run-1_desc-pymp2rage_T1w.nii.gz
        ├── sub-S01_ses-MR1_run-1_desc-pymp2rage_T1map.nii.gz
        ├── sub-S01_ses-MR1_run-1_desc-pymp2rage_mask.nii.gz
        ├── sub-S01_ses-MR1_run-1_desc-denoised_T1w.nii.gz
        ├── sub-S01_ses-MR1_run-1_desc-sinusauto_mask.nii.gz
        ├── sub-S01_ses-MR1_run-1_desc-sinusfinal_mask.nii.gz
        ├── cat12/
        │   └── run-1/
        ├── iter-1/
        ├── iter-2/
        ├── iteration_state.json
        └── logs/
```


## Commands

| Command | Description |
|---------|-------------|
| `pymp2rage` | Compute T1w (UNIT1) + T1map from inversions, utilizes B1-fieldmap correction if available |
| `mask` | Brain mask from INV2 via either FSL BET or SPM segmentation |
| `denoise` | Remove background noise |
| `cat12` | CAT12 tissue segmentation |
| `sinus-auto` | Auto-generate sinus exclusion mask |
| `sinus-edit` | Manual sinus mask editing (ITK-Snap) |
| `fmriprep` | Run fMRIprep + FreeSurfer via Docker |
| `brainmask-edit` | Refine brainmask manually (ITK-Snap) |
| `status` | Show pipeline status and configuration |


## Common options

| Option | Description |
|--------|-------------|
| `--studydir`, `-s` | Study directory (auto-detected from CWD) |
| `--subject`, `-sub` | Subject ID (without sub- prefix) |
| `--session`, `-ses` | Session ID (optional - processes all if omitted) |
| `--force`, `-f` | Force overwrite existing outputs |
| `--verbose`, `-v` | Verbose output |
