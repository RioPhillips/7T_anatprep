# anatprep

Anatomical preprocessing pipeline for **7T MP2RAGE** data.

It takes BIDS-organised rawdata (e.g. from [7T_BIDS_Organiser](https://github.com/RioPhillips/7T_BIDS_Organiser)) and carries a single anatomical run through pymp2rage fitting, brain masking, background/SANLM denoising, CAT12 segmentation, sinus/dura removal, FreeSurfer `recon-all`, and finally fMRIprep. The design follows the [Knapen lab's anatomical workflow](https://github.com/tknapen/tknapen.github.io/wiki/Anatomical-workflows) and Jurjen Heij's [fmriproc](https://github.com/gjheij/fmriproc) pipeline.

The guiding idea (from Heij's notes) is that FreeSurfer/BET/CAT12 are very sensitive to the INV1×INV2 noise that pymp2rage leaves around the head. So the early steps exist mostly to **give those tools a clean, sharp brain to work on**: mask from INV2, suppress background noise, denoise inside the brain with SANLM, then hand-correct the brain mask before surfaces are reconstructed.

---

## Overall pipeline 

Each step is a separate command, run **per subject, per MP2RAGE run**. Steps with ✋ require manual interaction.

```
pymp2rage        T1w (UNI) + T1map (+ B1-corrected) from the 4 inversion images
   │
mask             brain mask from INV2 magnitude (BET or SPM)
   │
denoise          Heij background removal  -->  SANLM + SPM bias  -->  WSD (uint16)
   │
cat12            CAT12 tissue segmentation; produces the p0 brainmask
   │
sinus-auto       FLAIR-based sagittal-sinus / dura exclusion mask
   │
sinus-edit  ✋   refine the sinus mask, and hand-edit the CAT12 p0 brainmask
   │
apply-mask       bake the edited brainmask into the denoised T1w --> desc-masked_T1w
   │
(isotropic) ✋   mri_convert the masked T1w to isotropic voxels  ← REQUIRED, see notes
   │
run-freesurfer   recon-all on the masked, isotropic T1w (+ FLAIR for pial)
   │
view-surfaces ✋ / brainmask-edit ✋ / run-freesurfer --edit   (iterate until clean)
   │
run-fmriprep     terminal step; reuses the recon-all from derivatives/freesurfer
```

Two optional Nighres steps (`nighres-skullstrip`, `nighres-dura`) are available as alternatives/supplements to `mask` if you have Nighres installed.

---

## Installation

```bash
# 1. environment
conda env create -f environment.yml
conda activate anatprep

# 2a. plain install
pip install git+https://github.com/RioPhillips/7T_anatprep.git

# 2b. editable + dev tools (recommended while developing)
git clone https://github.com/RioPhillips/7T_anatprep.git
cd 7T_anatprep
pip install -e ".[dev]"

# optional: Nighres support
pip install -e ".[nighres]"
```

Every subcommand is also installed as a **standalone console script**, so `anatprep pymp2rage ...` and `pymp2rage ...` are equivalent. The same is true for `mask`, `denoise`, `cat12`, `sinus-auto`, `sinus-edit`, `apply-mask`, `run-freesurfer`, `brainmask-edit`, `view-surfaces`, `run-fmriprep`, `nighres-dura`, `nighres-skullstrip`.

### External dependencies

| Tool | Used by |
|------|---------|
| **MATLAB or MCR + SPM12/25 + CAT12** | `mask --spm`, `denoise`, `cat12` |
| **FSL** (`bet`, `flirt`) | `mask --bet`, `sinus-auto`, pymp2rage B1 registration |
| **MRtrix3** (`maskfilter`) | `sinus-auto` |
| **ANTs** (`ImageMath`) | `denoise` (WSD step) |
| **FreeSurfer** (`recon-all`, `mri_convert`, `freeview`) | `run-freesurfer`, `view-surfaces`, isotropic resample |
| **ITK-Snap** | `brainmask-edit`, `sinus-edit` (if configured) |
| **Docker** + FreeSurfer license | `run-fmriprep` |
| **Nighres** (Python) | `nighres-*` (optional) |

> CAT12 can run via a **standalone MCR build** (no MATLAB licence needed). Point `matlab_cmd` at the MCR launcher (e.g. `.../run_spm25.sh`) and `spm_path` at the SPM bundled *inside* the standalone — the batch scripts auto-detect MCR mode. MCR R2023b + CAT12.9 is a known-good combination.

---

## Study layout & config

anatprep auto-detects the study directory by walking up from the current directory looking for `code/anatprep.yml`, `code/mp2rage.yaml` or `rawdata/`. Pass `--studydir` to override.

```
my_study/
├── code/
│   ├── anatprep.yml         # tool paths & options (below)
│   └── mp2rage.yaml         # MP2RAGE sequence parameters
├── rawdata/                 # BIDS input
│   └── sub-ID/
│       └── anat/            # sessionless: sub-XXXX/anat
│           ├── sub-ID_run-1_inv-1_part-mag_MP2RAGE.nii.gz
│           ├── sub-ID_run-1_inv-1_part-phase_MP2RAGE.nii.gz
│           ├── sub-ID_run-1_inv-2_part-mag_MP2RAGE.nii.gz
│           ├── sub-ID_run-1_inv-2_part-phase_MP2RAGE.nii.gz
│           └── sub-ID_run-1_FLAIR.nii.gz
└── derivatives/             # anatprep writes here
    ├── anatprep/
    ├── freesurfer/
    ├── fmriprep/
    └── logs/anatprep/
```

Session-based studies (`sub-XXXX/ses-YY/anat`) are also supported. pymp2rage needs **both magnitude and phase** for each inversion.
### `code/anatprep.yml`

```yaml
tools:
  spm_path: "/opt/spm/standalone"        # SPM dir (or bundled SPM inside MCR standalone)
  matlab_cmd: "/opt/spm/run_spm25.sh"    # "matlab" binary, or MCR launcher for standalone
  editing_software: "itksnap"            # sinus-edit editor: "freeview" (default) or "itksnap"

  freesurfer:
    license: "/opt/freesurfer/license.txt"
    subjects_dir: "derivatives/freesurfer"   # optional; relative paths resolve under studydir
    cpus: 8                                   # default -openmp threads

  fmriprep:
    docker_image: "nipreps/fmriprep:25.1.4"   # pin a version!
    nthreads: 8            # --nthreads / -j
    omp_nthreads: 8        # --omp-nthreads (threads per process)
    mem_mb: 32000
    output_spaces: "fsnative"
    shm_size: "8g"         # raw `docker run --shm-size`; the 64MB default starves MultiProc
    workdir: null          # default ~/.cache/anatprep/<study>/fmriprep_work

  nighres:
    dura_threshold: 0.8    # used by nighres-dura
```

### `code/mp2rage.yaml`

Required keys (read by `pymp2rage`):

```yaml
RepetitionTimeExcitation: 0.0062
RepetitionTimePreparation: 5.5
InversionTime: [0.8, 2.7]      # [TI1, TI2], seconds
FlipAngle: [5, 7]              # [FA1, FA2], degrees
NumberShots: 159
```

---

## Command reference

Common flags on most commands: `-f/--force` (overwrite existing outputs), `-v/--verbose`. Every command logs to `derivatives/logs/anatprep/sub-<id>/<command>_<timestamp>.log`.

| Command | Inputs | Output |
|---------|--------|--------|
| `pymp2rage` | 4 inversion images (+ optional B1) | T1w, T1map, mask (+ b1corr) |
| `mask` | INV2 magnitude | brain mask |
| `denoise` | T1w, brain mask, INV2 | denoised T1w (uint16) |
| `cat12` | denoised T1w | tissue maps + p0 brainmask |
| `sinus-auto` | denoised T1w, FLAIR, brain mask | sinus-exclusion mask (+ dilated) |
| `sinus-edit` | T1w, mask | hand-edited mask |
| `apply-mask` | image, mask | masked image (`desc-masked_T1w`) |
| `run-freesurfer` | masked T1w (+ FLAIR) | FreeSurfer subject dir |
| `view-surfaces` | FS subject dir | freeview QC (read-only) |
| `brainmask-edit` | FS subject dir | edited `brainmask.mgz`/`wm.mgz` |
| `run-fmriprep` | subject label | fMRIprep derivatives |
| `nighres-skullstrip` / `nighres-dura` | INV2/T1w/T1map / INV2+mask | skull mask / dura mask |

### pymp2rage

```bash
anatprep pymp2rage \
  --inv1-mag   sub-XX_run-1_inv-1_part-mag_MP2RAGE.nii.gz \
  --inv1-phase sub-XX_run-1_inv-1_part-phase_MP2RAGE.nii.gz \
  --inv2-mag   sub-XX_run-1_inv-2_part-mag_MP2RAGE.nii.gz \
  --inv2-phase sub-XX_run-1_inv-2_part-phase_MP2RAGE.nii.gz \
  --b1map  sub-XX_acq-dream_run-1_TB1map.nii.gz \
  --b1mag  sub-XX_acq-dream_run-1_magnitude.nii.gz \
  --out-dir derivatives/anatprep/sub-XX/pymp2rage
```

Computes the UNI T1w, quantitative T1map, and a mask. The output prefix is derived from the BIDS entities shared by all four inputs (they must agree on `sub`/`ses`/`run`).

**B1 correction** (Marques & Gruetter): pass `--b1map` alone if it is already in MP2RAGE space, or pass `--b1map` **and** `--b1mag` to have the magnitude/FID companion registered to INV1 (FLIRT, 6-DOF, mutual info) and the transform applied to the B1 map. Registration outputs are cached and reused unless `--force`. With B1 you also get `desc-pymp2rageb1corr_T1w/T1map`.

### mask

```bash
anatprep mask --bet  INV2_mag.nii.gz  out_desc-bet_mask.nii.gz      # FSL BET (default)
anatprep mask --spm  INV2_mag.nii.gz  out_desc-spmmask_mask.nii.gz  # SPM GM+WM segmentation
```

`OUTPUT_IMAGE` is optional; if omitted it is written to CWD. BET runs with `-f 0.3 -g -0.1`.

### denoise

```bash
anatprep denoise \
  --t1w  pymp2rage_T1w.nii.gz \
  --mask desc-bet_mask.nii.gz \
  --inv2 INV2_mag.nii.gz \
  --out  sub-XX_run-1_desc-denoised_T1w.nii.gz
```

Three stages: (1) Replaces out-of-brain voxels with an INV2-weighted blend so software stops choking on the rim noise; (2) SANLM + SPM bias correction via MATLAB/SPM (`--no-sanlm`/`--no-bias` to skip either); (3) Winsorize `[0.01, 0.99]` --> rescale `[0, 4095]` --> recast to `uint16` with the original header preserved.

### cat12

```bash
anatprep cat12 sub-XX_run-1_desc-denoised_T1w.nii.gz derivatives/anatprep/sub-XX/cat12/run-1
```

CAT12 tissue segmentation in **brain mode** (`APP=0`, `NCstr=0`, `biasstr=eps`, etc.) so it doesn't re-process the already denoised/B1-corrected image. Produces `p1/p2/p3` tissue maps, the `p0` label image, and a binarised `maskp0...` brain mask in `cat12/run-1/mri/`. The command tolerates a MATLAB crash during QC/reporting as long as the tissue maps exist.

### sinus-auto

#### Currently we have edited out the sinus + dura in the `maskp0*` from cat12 above directly and then ran FreeSurfer recon-all.

```bash
anatprep sinus-auto \
  --t1w   sub-XX_run-1_desc-denoised_T1w.nii.gz \
  --flair sub-XX_run-1_FLAIR.nii.gz \
  --mask  desc-bet_mask.nii.gz \
  --out   sub-XX_run-1_desc-sinusauto_mask.nii.gz
```

Registers FLAIR-->T1w, multiplies by the brain mask, then runs BET on the masked FLAIR — because the sagittal sinus is dark on FLAIR, it falls out of the resulting mask naturally (an "anti-sinus" mask). A dilated copy is written alongside as `<out>_dilated.nii.gz`. Without `--flair` it falls back to BET on the T1w as a starting point for manual editing.

### sinus-edit ✋

```bash
anatprep sinus-edit sub-XX_run-1_desc-denoised_T1w.nii.gz sub-XX_run-1_desc-sinusfinal_mask.nii.gz
```

Opens the mask over the T1w for hand-editing (creates an empty mask if absent). The editor is chosen by `tools.editing_software` (`freeview` or `itksnap`). This is also where you refine the CAT12 `p0` brainmask to excise sinus/dura — save the corrected brainmask under a name that `apply-mask` will pick up (the run script expects `edit_new_maskp0<...>.nii.gz`).

### apply-mask

```bash
anatprep apply-mask \
  --input sub-XX_run-1_desc-denoised_T1w.nii.gz \
  --mask  cat12/run-1/mri/edit_new_maskp0sub-XX_run-1_desc-denoised_T1w.nii.gz \
  --out   sub-XX_run-1_desc-masked_T1w.nii.gz
```

Keeps voxels where `mask > 0`, zeros the rest. This bakes the **hand-corrected brainmask** into the T1w, removing dura/sinus/skull so they can't be pulled into the pial surface. No winsorize by default (`denoise` already ran WSD); `-w` is available if you need it.

### run-freesurfer

```bash
# initial recon-all
anatprep run-freesurfer sub-XX_run-1_desc-masked_T1w.nii.gz \
  --flair sub-XX_run-1_FLAIR.nii.gz \
  --subject-id sub-XX --subjects-dir derivatives/freesurfer \
  --cpus 8 --no-fix-ga

# rerun after manual edits (see brainmask-edit)
anatprep run-freesurfer ... --edit pial   # brainmask edit --> -autorecon-pial -autorecon3
anatprep run-freesurfer ... --edit wm     # wm edit        --> -autorecon2-wm -autorecon3
```

`-hires` is **on by default** (`--no-highres` to disable). FLAIR is passed as `-FLAIR ... -FLAIRpial` and re-used automatically on reruns if it was conformed into `mri/FLAIR.mgz`. The subject ID is derived from the filename unless `--subject-id` is given. On `--edit` reruns the subject dir is backed up to `.backups/<id>_<timestamp>/` first.

Parallelism: `--cpus N` sets `-openmp N`; add `--parallel` to also run lh/rh concurrently.

`--no-fix-ga` disables the gyrus-ambiens cortex-label fix. FreeSurfer 8.x hard-fails on some subjects (zero voxels for the GA label).

### view-surfaces ✋ / brainmask-edit ✋

```bash
anatprep view-surfaces  derivatives/freesurfer/sub-XX                 # inspect white/pial in freeview
anatprep brainmask-edit derivatives/freesurfer/sub-XX --target brainmask   # edit in ITK-Snap --> rerun --edit pial
anatprep brainmask-edit derivatives/freesurfer/sub-XX --target wm          #                 --> rerun --edit wm
```

`view-surfaces` is read-only QC. `brainmask-edit` converts the chosen `.mgz` to NIfTI, opens ITK-Snap (one editable volume per session), converts back only if you saved a change, and tells you which `--edit` rerun to do next. Originals are preserved as `<name>.mgz.bak`. Iterate view --> edit --> rerun until the surfaces are clean.

### run-fmriprep

```bash
anatprep run-fmriprep 7T049C10 --anat-desc masked -j 1 -v --force
```

Assembles a small BIDS tree (the cleaned anat renamed to a raw-style `T1w`, plus func/fmap mirrored from rawdata) and runs fMRIprep on it, **reusing the existing `recon-all`** from `derivatives/freesurfer` via `--fs-subjects-dir` (it is not re-run). Defaults to `docker run` (raw, so `--shm-size` can be set); `--local` uses a bare-metal `fmriprep`.

Key options: `--anat-desc denoised|masked` selects which anatprep derivative to use (`masked` auto-sets `--skull-strip-t1w skip`); `--anat-only` for surfaces only; `-j/--cpus`, `--omp-nthreads`, `--mem-mb`; `-u/--bids-filter-file` for a pybids query JSON; `-k/--kwargs-file` for extra fMRIprep flags (one per line, `#` comments allowed); `--clean-workdir` to wipe this subject's workflow folder for a fresh start; `--notrack` (on by default, disables sentry telemetry whose background threads can segfault Python 3.12 during GC).

### nighres-skullstrip / nighres-dura (optional)

```bash
anatprep nighres-skullstrip INV2.nii.gz T1w.nii.gz T1map.nii.gz  out_prefix
anatprep nighres-dura       INV2.nii.gz brain_mask.nii.gz  out_dura_mask.nii.gz --threshold 0.8
```

Nighres-based MP2RAGE skull-stripping and dura estimation, for studies that prefer them over BET/SPM masking.

---

## Two manual steps between `apply-mask` and fMRIprep
 
 
### 1. Make the masked T1w isotropic — REQUIRED
 
`apply-mask` keeps the input voxel grid, and fMRIprep has reliably **crashed** unless the masked T1w is isotropic first. Rename the masked output and resample with `mri_convert` (this isotropic file is what then feeds `run-freesurfer` and `run-fmriprep`):
 
```bash
cd derivatives/anatprep/sub-XX
# keep the original (anisotropic) version under an orig_ prefix
mv sub-XX_run-1_desc-masked_T1w.nii.gz orig_sub-XX_run-1_desc-masked.nii.gz
# resample to 0.64 mm isotropic, cubic interpolation
mri_convert -rt cubic -vs 0.64 0.64 0.64 \
  orig_sub-XX_run-1_desc-masked.nii.gz \
  sub-XX_run-1_desc-masked_T1w.nii.gz
```
 
### 2. Run fMRIprep with `-j 1` (and `--force` to resume)
 
Single-threaded is the only configuration that has run to completion, higher `-j` has been crash-prone:
 
```bash
anatprep run-fmriprep 7T049C10 --anat-desc masked -j 1 -v --force
```
 
If a run dies partway, re-issue the **same command** with `--force` which stops anatprep from skipping the already-started subject and fMRIprep resumes from its persistent work directory rather than starting over.
 
---


## Output structure

```
derivatives/
├── anatprep/sub-XX/
│   ├── pymp2rage/   sub-XX_run-1_desc-pymp2rage_T1w / _T1map / _mask (+ b1corr)
│   ├── masks/       desc-bet_mask, desc-sinusauto_mask (+ _dilated), desc-sinusfinal_mask
│   ├── nighres/     (optional)
│   ├── cat12/run-1/ mri/ p0,p1,p2,p3, maskp0..., edit_new_maskp0...  (edited brainmask)
│   ├── xfm/         cached FLIRT matrices
│   ├── sub-XX_run-1_desc-denoised_T1w.nii.gz
│   └── sub-XX_run-1_desc-masked_T1w.nii.gz   (← made isotropic before recon-all)
├── freesurfer/sub-XX/        recon-all output (reused by fMRIprep)
├── fmriprep/                 fMRIprep derivatives + sourcedata/bids (assembled input tree)
└── logs/anatprep/sub-XX/     <command>_<timestamp>.log
```