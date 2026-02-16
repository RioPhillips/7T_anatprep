#!/usr/bin/env bash
set -euo pipefail

# cat12_batch.sh
# CAT12 tissue segmentation via SPM/MATLAB for pre-processed 7T MP2RAGE.
#
#
# Supports CAT12 versions: 1450 and 2170+ (found in Contents.txt).
#
# Usage:
#   cat12_batch.sh -s <SPM_PATH> -m <MATLAB_CMD> -i <INPUT_FILE> -o <OUTPUT_DIR> -l <LOG_DIR>
#                  [--full]
#
# Options:
#   -s  Path to SPM12 installation (must contain toolbox/cat12)
#   -m  MATLAB command (default: matlab)
#   -i  Input NIfTI (.nii or .nii.gz)
#   -o  Output directory for CAT12 results
#   -l  Log directory
#   --full  Enable bias correction + SANLM filtering (for raw/unprocessed data)

SPM_PATH=""
MATLAB_CMD="matlab"
INPUT_FILE=""
OUTPUT_DIR=""
LOG_DIR=""
MODE="brain"  # default: no bias/SANLM for pre-processed data

usage() {
cat <<EOF
Usage:
  cat12_batch.sh -s <SPM_PATH> -m <MATLAB_CMD> -i <INPUT_FILE> -o <OUTPUT_DIR> -l <LOG_DIR> [--full]

Options:
  -s, --spm      Path to SPM12 installation
  -m, --matlab   MATLAB command (default: matlab)
  -i, --input    Input NIfTI file (.nii or .nii.gz)
  -o, --output   Output directory
  -l, --logdir   Log directory
  --full         Full processing mode (bias correction + SANLM). Default: brain-only.
EOF
exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--spm)     SPM_PATH="$2"; shift 2 ;;
    -m|--matlab)  MATLAB_CMD="$2"; shift 2 ;;
    -i|--input)   INPUT_FILE="$2"; shift 2 ;;
    -o|--output)  OUTPUT_DIR="$2"; shift 2 ;;
    -l|--logdir)  LOG_DIR="$2"; shift 2 ;;
    --full)       MODE="full"; shift ;;
    *)            echo "Unknown option: $1"; usage ;;
  esac
done

[[ -z "$SPM_PATH" || -z "$INPUT_FILE" || -z "$OUTPUT_DIR" || -z "$LOG_DIR" ]] && usage

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"

# Validate inputs 

# Find CAT12 directory
CAT12_DIR=$(find -L "$SPM_PATH" -type d -name "*cat12*" -print -quit 2>/dev/null)
if [[ -z "$CAT12_DIR" ]]; then
  echo "[cat12] ERROR: CAT12 directory not found under $SPM_PATH"
  exit 1
fi

# Detect CAT12 version from Contents.txt
VER=""
if [[ -f "$CAT12_DIR/Contents.txt" ]]; then
  VER=$(grep "Version" "$CAT12_DIR/Contents.txt" | cut -d" " -f3 2>/dev/null || true)
fi

# If we can't read version, try to infer from directory structure
if [[ -z "$VER" ]]; then
  if [[ -d "$CAT12_DIR/templates_MNI152NLin2009cAsym" ]]; then
    VER="2170"  # newer CAT12 has this template dir
    echo "[cat12] WARNING: Could not read version from Contents.txt, inferring >= 2170"
  else
    VER="1450"
    echo "[cat12] WARNING: Could not read version from Contents.txt, assuming 1450"
  fi
fi

echo "[cat12] MATLAB version: $MATLAB_CMD"
echo "[cat12] SPM path:       $SPM_PATH"
echo "[cat12] CAT12 path:     $CAT12_DIR"
echo "[cat12] CAT12 version:  $VER"
echo "[cat12] Mode:           $MODE"
echo "[cat12] Input:          $INPUT_FILE"
echo "[cat12] Output:         $OUTPUT_DIR"

# Check TPM exists
if [[ ! -f "$SPM_PATH/tpm/TPM.nii" ]]; then
  echo "[cat12] ERROR: TPM.nii not found at $SPM_PATH/tpm/TPM.nii"
  exit 1
fi

# Handle gzip 

INPUT_WAS_GZ=0
if [[ "$INPUT_FILE" == *.gz ]]; then
  INPUT_WAS_GZ=1
  NII_FILE="${OUTPUT_DIR}/$(basename "${INPUT_FILE%.gz}")"
  echo "[cat12] Decompressing .nii.gz -> $NII_FILE"
  gunzip -c "$INPUT_FILE" > "$NII_FILE"
else
  # copy to output dir so CAT12 writes mri/ there
  NII_FILE="${OUTPUT_DIR}/$(basename "$INPUT_FILE")"
  if [[ "$(realpath "$INPUT_FILE")" != "$(realpath "$NII_FILE")" ]]; then
    cp "$INPUT_FILE" "$NII_FILE"
  fi
fi

# log and script paths 

LOGFILE="${LOG_DIR}/cat12_$(date +%Y%m%d_%H%M%S).log"
SCRIPT="${OUTPUT_DIR}/cat12_batch.m"

echo "[cat12] MATLAB script:  $SCRIPT"
echo "[cat12] Log file:       $LOGFILE"

# Print image info 

if command -v fslinfo &>/dev/null; then
  dims=$(fslinfo "$NII_FILE" 2>/dev/null | grep -E "^dim[1-3]|^pixdim[1-3]" | awk '{print $2}' | tr '\n' ' ')
  echo "[cat12] Image info: $dims"
fi

# Generate MATLAB batch 

# Start the script
cat > "$SCRIPT" <<MHEAD
%-----------------------------------------------------------------------------
% CAT12 batch - auto-generated $(date)
% CAT12 version: ${VER}, Mode: ${MODE}
%-----------------------------------------------------------------------------
clear;
addpath(genpath('${SPM_PATH}'));

MHEAD

# Version-specific batch generation 

if [[ "$VER" == "1450" ]]; then
  # CAT12 v1450 
  cat >> "$SCRIPT" <<M1450
matlabbatch{1}.spm.tools.cat.estwrite.data = {'${NII_FILE},1'};
matlabbatch{1}.spm.tools.cat.estwrite.nproc = 0;
matlabbatch{1}.spm.tools.cat.estwrite.opts.tpm = {'${SPM_PATH}/tpm/TPM.nii'};
matlabbatch{1}.spm.tools.cat.estwrite.opts.affreg = 'mni';
matlabbatch{1}.spm.tools.cat.estwrite.opts.biasstr = 0.75;
matlabbatch{1}.spm.tools.cat.estwrite.opts.accstr = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.APP = 1070;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.NCstr = -Inf;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.LASstr = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.gcutstr = 2;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.cleanupstr = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.WMHC = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.SLC = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.restypes.native = struct([]);
matlabbatch{1}.spm.tools.cat.estwrite.extopts.registration.dartel.darteltpm = {'${SPM_PATH}/toolbox/cat12/templates_1.50mm/Template_1_IXI555_MNI152.nii'};
matlabbatch{1}.spm.tools.cat.estwrite.extopts.vox = 1.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.pbtres = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.scale_cortex = 0.7;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.add_parahipp = 0.1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.close_parahipp = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.ignoreErrors = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.verb = 2;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.print = 2;
matlabbatch{1}.spm.tools.cat.estwrite.output.surface = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.ROImenu.noROI = struct([]);
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.atlas.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.atlas.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.label.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.label.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.label.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.bias.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.bias.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.bias.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.las.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.las.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.las.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.jacobianwarped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.warps = [0 0];
M1450

else
  # CAT12 v2170+ (r2170, r2577, etc.) 
  # "brain" mode: APP=0, NCstr=0, biasstr=eps  (data already preprocessed)
  # "full" mode:  APP=1070, NCstr=2, biasstr=0.5

  if [[ "$MODE" == "brain" ]]; then
    APP_VAL=0
    NCSTR_VAL=0
    BIASSTR_VAL="2.22044604925031e-16"
    echo "[cat12] Brain mode: APP=0, NCstr=0, biasstr=eps (pre-processed input)"
  else
    APP_VAL=1070
    NCSTR_VAL=2
    BIASSTR_VAL="0.5"
    echo "[cat12] Full mode: APP=1070, NCstr=2, biasstr=0.5"
  fi

  cat >> "$SCRIPT" <<M2170
matlabbatch{1}.spm.tools.cat.estwrite.data = {'${NII_FILE},1'};
matlabbatch{1}.spm.tools.cat.estwrite.nproc = 0;
matlabbatch{1}.spm.tools.cat.estwrite.useprior = '';
matlabbatch{1}.spm.tools.cat.estwrite.opts.tpm = {'${SPM_PATH}/tpm/TPM.nii'};
matlabbatch{1}.spm.tools.cat.estwrite.opts.affreg = 'mni';
matlabbatch{1}.spm.tools.cat.estwrite.opts.biasstr = ${BIASSTR_VAL};
matlabbatch{1}.spm.tools.cat.estwrite.opts.accstr = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.restypes.native = struct([]);
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.setCOM = 1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.APP = ${APP_VAL};
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.affmod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.NCstr = ${NCSTR_VAL};
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.LASstr = 0; 
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.LASmyostr = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.gcutstr = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.cleanupstr = 0.3;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.BVCstr = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.WMHC = 2;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.SLC = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.mrf = 1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.registration.regmethod.shooting.shootingtpm = {'${CAT12_DIR}/templates_MNI152NLin2009cAsym/Template_0_GS.nii'};
matlabbatch{1}.spm.tools.cat.estwrite.extopts.registration.regmethod.shooting.regstr = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.registration.vox = 1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.registration.bb = 12;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.pbtres = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.pbtmethod = 'pbt2x';
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.SRP = 22;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.reduce_mesh = 1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.vdist = 2;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.scale_cortex = 0.7;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.add_parahipp = 0.1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.surface.close_parahipp = 1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.experimental = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.new_release = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.lazy = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.ignoreErrors = 1;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.verb = 2;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.admin.print = 2;
matlabbatch{1}.spm.tools.cat.estwrite.output.BIDS.BIDSno = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.surface = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.surf_measures = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.ROImenu.noROI = struct([]);
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.GM.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WM.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.CSF.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.ct.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.ct.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.ct.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.pp.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.pp.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.pp.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.WMH.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.SL.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.TPMC.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.TPMC.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.TPMC.mod = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.TPMC.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.atlas.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.label.native = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.label.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.label.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.labelnative = 1;
matlabbatch{1}.spm.tools.cat.estwrite.output.bias.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.bias.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.bias.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.las.native = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.las.warped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.las.dartel = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.jacobianwarped = 0;
matlabbatch{1}.spm.tools.cat.estwrite.output.warps = [0 0];
matlabbatch{1}.spm.tools.cat.estwrite.output.rmat = 0;
M2170

fi

# execution commands 

cat >> "$SCRIPT" <<MRUN

cat_get_defaults('extopts.expertgui',1);
spm_jobman('initcfg');
spm('defaults','fMRI');
spm_jobman('run', matlabbatch);
exit
MRUN

# Run MATLAB 

echo "[cat12] Starting MATLAB..."
"$MATLAB_CMD" -nodisplay -nosplash -batch "run('$SCRIPT')" > "$LOGFILE" 2>&1
MATLAB_EXIT=$?

# Check results 

# the mri/ directory with tissue maps
MRI_DIR="${OUTPUT_DIR}/mri"
TISSUE_MAPS_OK=0

if [[ -d "$MRI_DIR" ]]; then
  P1_COUNT=$(ls "$MRI_DIR"/p1*.nii* 2>/dev/null | wc -l)
  P2_COUNT=$(ls "$MRI_DIR"/p2*.nii* 2>/dev/null | wc -l)
  P3_COUNT=$(ls "$MRI_DIR"/p3*.nii* 2>/dev/null | wc -l)
  P0_COUNT=$(ls "$MRI_DIR"/p0*.nii* 2>/dev/null | wc -l)

  if [[ $P1_COUNT -gt 0 && $P2_COUNT -gt 0 && $P3_COUNT -gt 0 ]]; then
    TISSUE_MAPS_OK=1
  fi
fi

if [[ $TISSUE_MAPS_OK -eq 0 ]]; then
  echo "[cat12] ERROR: CAT12 did not produce tissue maps"
  echo "[cat12] MATLAB exit code: $MATLAB_EXIT"

  # check log for known error patterns
  if [[ -f "$LOGFILE" ]]; then
    if grep -q "Attempt to grow array along ambiguous dimension" "$LOGFILE"; then
      echo "[cat12] Known error: cat_vol_morph dimension issue."
      echo "[cat12] This often happens when APP is enabled on pre-processed data."
      echo "[cat12] Try running with --brain mode (default) or check input image."
    fi
    if grep -q "spm_kamap" "$LOGFILE"; then
      echo "[cat12] Known error: spm_kamap field not recognized."
      echo "[cat12] Your CAT12 version may not support this field. Check version compatibility."
    fi
    if grep -q "Failed: CAT12" "$LOGFILE"; then
      echo "[cat12] CAT12 segmentation failed. See log: $LOGFILE"
    fi
    echo "[cat12] Last 20 lines of log:"
    tail -n 20 "$LOGFILE"
  fi
  exit 1
fi

echo "[cat12] Tissue maps produced successfully in $MRI_DIR"

# Post-processing: convert, create mask 

#  mri/ and report/ contents up to output dir
#  handle err/ directory
if [[ -d "${OUTPUT_DIR}/err" ]]; then
  echo "[cat12] WARNING: CAT12 created an error directory (info in report)"
  rm -rf "${OUTPUT_DIR}/err"
fi

# convert to .nii.gz if input was gzipped
if [[ $INPUT_WAS_GZ -eq 1 ]]; then
  echo "[cat12] Converting output .nii -> .nii.gz"
  for f in "$MRI_DIR"/*.nii; do
    [[ -f "$f" ]] && gzip "$f"
  done
  # clean up the decompressed input
  rm -f "$NII_FILE"
fi

# header geometry from input to outputs
if command -v fslcpgeom &>/dev/null; then
  echo "[cat12] Copying header geometry from input image"
  for f in "$MRI_DIR"/*; do
    [[ -f "$f" ]] && fslcpgeom "$INPUT_FILE" "$f" 2>/dev/null || true
  done
fi

# binary brain mask from p0 segmentation
P0_IMG=$(find "$MRI_DIR" -name "p0*" -print -quit 2>/dev/null)
if [[ -n "$P0_IMG" ]] && command -v fslmaths &>/dev/null; then
  echo "[cat12] Creating binary mask from p0 segmentation"
  fslmaths "$P0_IMG" -bin "$MRI_DIR/mask$(basename "$P0_IMG")"
fi


if [[ -d "${OUTPUT_DIR}/report" ]]; then
  cp "${OUTPUT_DIR}"/report/catreport* "$OUTPUT_DIR"/ 2>/dev/null || true
fi

echo "[cat12] Done --> $OUTPUT_DIR"
echo "[cat12] Log:  $LOGFILE"