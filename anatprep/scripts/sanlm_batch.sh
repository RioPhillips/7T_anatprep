#!/usr/bin/env bash
set -euo pipefail

# Wrapper for SANLM and SPM Bias Correction
function Usage {
    cat <<USAGE
Usage: sanlm_batch.sh -s <spm_path> -m <matlab_cmd> -i <in.nii.gz> -o <out.nii.gz> [-n] [-b]
  -n  Run SANLM denoising
  -b  Run SPM Bias correction
USAGE
    exit 1
}

DO_SANLM=0
DO_BIAS=0
while getopts "s:m:i:o:nb" opt; do
    case "$opt" in
        s) SPM_PATH=$OPTARG ;;
        m) MATLAB_CMD=$OPTARG ;;
        i) INPUT=$OPTARG ;;
        o) OUTPUT=$OPTARG ;;
        n) DO_SANLM=1 ;;
        b) DO_BIAS=1 ;;
        *) Usage ;;
    esac
done

[[ -z "${SPM_PATH:-}" || -z "${INPUT:-}" || -z "${OUTPUT:-}" ]] && Usage

mkdir -p "$(dirname "$OUTPUT")"

# Setup Paths
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

LOG_DIR="$(dirname "$OUTPUT")/logs"
mkdir -p "$LOG_DIR"
LOGFILE="${LOG_DIR}/sanlm_bias_$(date +%Y%m%d_%H%M%S).log"

cp "$INPUT" "$TMP_DIR/input.nii.gz"
gunzip "$TMP_DIR/input.nii.gz"
IN_NII="$TMP_DIR/input.nii"
FINAL_NII="$TMP_DIR/final.nii"

echo "[sanlm_bias] MATLAB cmd: $MATLAB_CMD"
echo "[sanlm_bias] SPM path:   $SPM_PATH"
echo "[sanlm_bias] Input:      $INPUT"
echo "[sanlm_bias] Output:     $OUTPUT"
echo "[sanlm_bias] Log file:   $LOGFILE"

# MATLAB Logic
MLAB_FILE="$TMP_DIR/sanlm_bias_batch.m"
cat > "$MLAB_FILE" <<MATLAB
clear;
addpath(genpath('$SPM_PATH'));
spm('defaults','FMRI');
spm_jobman('initcfg');

current_file = '$IN_NII';

if $DO_SANLM == 1
    fprintf('--- Running SANLM ---\\n');
    matlabbatch = [];
    matlabbatch{1}.spm.tools.cat.tools.sanlm.data = {[current_file ',1']};
    matlabbatch{1}.spm.tools.cat.tools.sanlm.prefix = 'sanlm_';
    matlabbatch{1}.spm.tools.cat.tools.sanlm.NCstr = Inf;
    matlabbatch{1}.spm.tools.cat.tools.sanlm.rician = 0;
    spm_jobman('run', matlabbatch);

    [p,n,e] = fileparts(current_file);
    current_file = fullfile(p, ['sanlm_' n e]);
end

if $DO_BIAS == 1
    fprintf('--- Running Bias Correction ---\\n');
    matlabbatch = [];
    matlabbatch{1}.spm.spatial.preproc.channel.vols = {[current_file ',1']};
    matlabbatch{1}.spm.spatial.preproc.channel.biasreg = 0.001;
    matlabbatch{1}.spm.spatial.preproc.channel.biasfwhm = 60;
    matlabbatch{1}.spm.spatial.preproc.channel.write = [1 1];

    matlabbatch{1}.spm.spatial.preproc.tissue(1).tpm = {fullfile('$SPM_PATH','tpm','TPM.nii,1')};
    matlabbatch{1}.spm.spatial.preproc.tissue(1).ngaus = 1;
    matlabbatch{1}.spm.spatial.preproc.tissue(1).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(1).warped = [0 0];

    matlabbatch{1}.spm.spatial.preproc.tissue(2).tpm = {fullfile('$SPM_PATH','tpm','TPM.nii,2')};
    matlabbatch{1}.spm.spatial.preproc.tissue(2).ngaus = 1;
    matlabbatch{1}.spm.spatial.preproc.tissue(2).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(2).warped = [0 0];

    matlabbatch{1}.spm.spatial.preproc.tissue(3).tpm = {fullfile('$SPM_PATH','tpm','TPM.nii,3')};
    matlabbatch{1}.spm.spatial.preproc.tissue(3).ngaus = 2;
    matlabbatch{1}.spm.spatial.preproc.tissue(3).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(3).warped = [0 0];

    matlabbatch{1}.spm.spatial.preproc.tissue(4).tpm = {fullfile('$SPM_PATH','tpm','TPM.nii,4')};
    matlabbatch{1}.spm.spatial.preproc.tissue(4).ngaus = 3;
    matlabbatch{1}.spm.spatial.preproc.tissue(4).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(4).warped = [0 0];

    matlabbatch{1}.spm.spatial.preproc.tissue(5).tpm = {fullfile('$SPM_PATH','tpm','TPM.nii,5')};
    matlabbatch{1}.spm.spatial.preproc.tissue(5).ngaus = 4;
    matlabbatch{1}.spm.spatial.preproc.tissue(5).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(5).warped = [0 0];

    matlabbatch{1}.spm.spatial.preproc.tissue(6).tpm = {fullfile('$SPM_PATH','tpm','TPM.nii,6')};
    matlabbatch{1}.spm.spatial.preproc.tissue(6).ngaus = 2;
    matlabbatch{1}.spm.spatial.preproc.tissue(6).native = [0 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(6).warped = [0 0];

    matlabbatch{1}.spm.spatial.preproc.warp.mrf = 1;
    matlabbatch{1}.spm.spatial.preproc.warp.cleanup = 0;
    matlabbatch{1}.spm.spatial.preproc.warp.reg = [0 0.001 0.5 0.05 0.2];
    matlabbatch{1}.spm.spatial.preproc.warp.affreg = 'mni';
    matlabbatch{1}.spm.spatial.preproc.warp.fwhm = 0;
    matlabbatch{1}.spm.spatial.preproc.warp.samp = 3;
    matlabbatch{1}.spm.spatial.preproc.warp.write = [0 0];

    spm_jobman('run', matlabbatch);

    [p,n,e] = fileparts(current_file);
    current_file = fullfile(p, ['m' n e]);
end

movefile(current_file, '$FINAL_NII');
exit(0);
MATLAB

echo "[sanlm_bias] Starting MATLAB..."
"$MATLAB_CMD" -nodisplay -nosplash -batch "run('$MLAB_FILE')" 2>&1 | tee "$LOGFILE"
MATLAB_EXIT=${PIPESTATUS[0]}

if [[ $MATLAB_EXIT -ne 0 ]]; then
    echo "[sanlm_bias] ERROR: MATLAB exited with status $MATLAB_EXIT"
    exit $MATLAB_EXIT
fi

if [[ ! -f "$FINAL_NII" ]]; then
    echo "[sanlm_bias] ERROR: expected final NIfTI not found: $FINAL_NII"
    exit 1
fi

echo "[sanlm_bias] Compressing final NIfTI -> $OUTPUT"
gzip -c "$FINAL_NII" > "$OUTPUT"

echo "[sanlm_bias] Done"