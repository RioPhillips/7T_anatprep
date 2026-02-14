#!/usr/bin/env bash
set -euo pipefail

# spm_mask.sh
# Creates brain mask using SPM12 segmentation + spmBrainMask.m
#
# Usage:
#   spm_mask.sh -s <SPM_PATH> -m <MATLAB_CMD> <input_image> <output_mask>
#
# Environment:
#   LOG_DIR (optional): where MATLAB log files are saved

usage() {
cat <<EOF
Usage:
  spm_mask.sh -s <SPM_PATH> -m <MATLAB_CMD> <input_image> <output_mask>
EOF
exit 1
}

SPM_PATH=""
MATLAB_CMD=""

while getopts "s:m:" opt; do
  case $opt in
    s) SPM_PATH=$OPTARG ;;
    m) MATLAB_CMD=$OPTARG ;;
    *) usage ;;
  esac
done
shift $((OPTIND-1))

INPUT=${1:-}
OUTPUT=${2:-}

[[ -z "$SPM_PATH" || -z "$MATLAB_CMD" || -z "$INPUT" || -z "$OUTPUT" ]] && usage

# create output dir
OUTDIR=$(dirname "$OUTPUT")
mkdir -p "$OUTDIR"

# log dir
LOG_DIR="${LOG_DIR:-$OUTDIR}"
mkdir -p "$LOG_DIR"

# tmp workspace
WORKDIR=$(mktemp -d -p "${TMPDIR:-/tmp}" spm_mask_XXXX)
trap 'rm -rf "$WORKDIR"' EXIT

# copy helper MATLAB function
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
HELPER="${SCRIPT_DIR}/helpers/spmBrainMask.m"
if [[ -f "$HELPER" ]]; then
  cp "$HELPER" "${WORKDIR}/"
else
  echo "[spm_mask] ERROR: spmBrainMask.m not found at ${HELPER}"
  exit 1
fi

# decompress if needed
if [[ "$INPUT" == *.gz ]]; then
  TMPFILE="${WORKDIR}/$(basename "${INPUT%.gz}")"
  gunzip -c "$INPUT" > "$TMPFILE"
  INPUT="$TMPFILE"
fi

# prepare MATLAB script
SCRIPT_PATH="${WORKDIR}/spm_mask.m"
LOG_PATH="${LOG_DIR}/spm_mask_matlab.log"

cat > "$SCRIPT_PATH" <<MATLAB
try
    addpath('${SPM_PATH}');
    addpath('${WORKDIR}');
    spm('defaults','PET');
    spm_jobman('initcfg');

    [maskFile,~] = spmBrainMask('${INPUT}');

    if ~exist('maskFile','var') || isempty(maskFile)
        [p,n,~] = fileparts('${INPUT}');
        guess = fullfile(p, ['mask_' n '.nii']);
        if exist(guess,'file')
            maskFile = guess;
        else
            error('No mask file found or returned by spmBrainMask.');
        end
    end

    movefile(maskFile,'${OUTPUT%.gz}');
catch ME
    disp('--- MATLAB ERROR REPORT ---');
    disp(getReport(ME,'extended','hyperlinks','off'));
    exit(1);
end
exit;
MATLAB

echo "[spm_mask] Running MATLAB --> spmBrainMask('${INPUT}')"
"$MATLAB_CMD" -nodisplay -nosplash -nodesktop -r "run('${SCRIPT_PATH}');" >"$LOG_PATH" 2>&1 || {
  echo "[spm_mask] MATLAB failed! See log: $LOG_PATH"
  tail -n 30 "$LOG_PATH"
  exit 1
}

# handle gzip
OUTPUT_NII="${OUTPUT%.gz}"

if [[ "${OUTPUT##*.}" == "gz" ]]; then
  if [[ -f "$OUTPUT" ]]; then
    if ! gzip -t "$OUTPUT" &>/dev/null; then
      mv "$OUTPUT" "$OUTPUT_NII"
    fi
  fi
  if [[ -f "$OUTPUT_NII" && ! -f "$OUTPUT" ]]; then
    gzip -f "$OUTPUT_NII"
  fi
fi

# validate
if [[ -f "$OUTPUT" ]] || [[ -f "$OUTPUT_NII" ]]; then
  echo "[spm_mask] Done. Mask created."
else
  echo "[spm_mask] ERROR: No valid mask file produced."
  exit 1
fi
