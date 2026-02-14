#!/usr/bin/env bash
set -euo pipefail

# cat12_batch.sh
# CAT12 segmentation via SPM in headless MATLAB mode.
#
# Usage:
#   cat12_batch.sh -s <SPM_PATH> -m <MATLAB_CMD> -i <input_nii> -o <output_dir> -l <log_dir>

SPM_PATH=""
MATLAB_CMD="matlab"
INPUT_FILE=""
OUTPUT_DIR=""
LOG_DIR=""

usage() {
cat <<EOF
Usage:
  cat12_batch.sh -s <SPM_PATH> -m <MATLAB_CMD> -i <INPUT_FILE> -o <OUTPUT_DIR> -l <LOG_DIR>
EOF
exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--spm) SPM_PATH="$2"; shift 2 ;;
    -m|--matlab) MATLAB_CMD="$2"; shift 2 ;;
    -i|--input) INPUT_FILE="$2"; shift 2 ;;
    -o|--output) OUTPUT_DIR="$2"; shift 2 ;;
    -l|--logdir) LOG_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

[[ -z "$SPM_PATH" || -z "$INPUT_FILE" || -z "$OUTPUT_DIR" || -z "$LOG_DIR" ]] && usage

echo "[cat12] Starting CAT12 segmentation"
echo "[cat12] Input:  $INPUT_FILE"
echo "[cat12] Output: $OUTPUT_DIR"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"

LOGFILE="${LOG_DIR}/cat12_$(date +%Y%m%d_%H%M%S).log"
SCRIPT="${OUTPUT_DIR}/cat12_batch.m"

# handle gzip
if [[ "$INPUT_FILE" == *.gz ]]; then
  NII_FILE="${OUTPUT_DIR}/$(basename "${INPUT_FILE%.gz}")"
  gunzip -c "$INPUT_FILE" > "$NII_FILE"
else
  NII_FILE="$INPUT_FILE"
fi

# find CAT12 toolbox
CAT12_DIR=$(find "$SPM_PATH"/toolbox -maxdepth 1 -type d -iname "cat12*" | head -n 1 || true)
if [[ -z "$CAT12_DIR" ]]; then
  echo "[cat12] ERROR: CAT12 not found under $SPM_PATH/toolbox/"
  exit 1
fi
echo "[cat12] Found CAT12 at: $CAT12_DIR"

# generate MATLAB batch script
cat > "$SCRIPT" <<MATLAB
clear; clc;
fprintf('\\n[cat12] Running CAT12 segmentation...\\n');
addpath(genpath('$SPM_PATH'));
spm('defaults','fMRI');
spm_jobman('initcfg');

matlabbatch{1}.spm.tools.cat.estwrite.data = {'$NII_FILE,1'};
matlabbatch{1}.spm.tools.cat.estwrite.output.surface = 0;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.APP = 1070;
matlabbatch{1}.spm.tools.cat.estwrite.extopts.segmentation.cleanupstr = 0.5;
matlabbatch{1}.spm.tools.cat.estwrite.opts.affreg = 'mni';
matlabbatch{1}.spm.tools.cat.estwrite.opts.biasstr = 0.75;

try
    spm_jobman('run', matlabbatch);
    fprintf('\\n[cat12] CAT12 segmentation completed successfully.\\n');
catch ME
    fprintf(2, '\\n[cat12] ERROR: %s\\n', ME.message);
    exit(1);
end
exit;
MATLAB

echo "[cat12] Running MATLAB batch"
"$MATLAB_CMD" -batch "run('$SCRIPT')" > "$LOGFILE" 2>&1 || {
  echo "[cat12] MATLAB failed! See log: $LOGFILE"
  tail -n 20 "$LOGFILE"
  exit 1
}

echo "[cat12] Done --> $OUTPUT_DIR"
