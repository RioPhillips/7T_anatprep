function [maskFile, maskedFile] = spmBrainMask(niifile, doWriteMaskedFile)
% spmBrainMask  creates brain mask using SPM segmentation (should work for SPM12/SPM25).
%
%   [maskFile, maskedFile] = spmBrainMask(niifile, doWriteMaskedFile)
%
%   creates brain mask (mask_<input>) using SPM segmentation of GM+WM.
%   if doWriteMaskedFile==true, also creates masked anatomical file.
%

if nargin < 2
    doWriteMaskedFile = false;
end

[path, name, ext] = fileparts(niifile);
if isempty(path), path = pwd; end

maskFile = fullfile(path, ['mask_' name ext]);
disp(['Creating mask: ' maskFile]);

%% 1. runs SPM segmentation
matlabbatch{1}.spm.spatial.preproc.channel.vols = {niifile};
matlabbatch{1}.spm.spatial.preproc.channel.biasreg = 0.001;
matlabbatch{1}.spm.spatial.preproc.channel.biasfwhm = 60;
matlabbatch{1}.spm.spatial.preproc.channel.write = [0 0];

% TPMs 1-6
for i = 1:6
    matlabbatch{1}.spm.spatial.preproc.tissue(i).tpm = ...
        {[fullfile(spm('Dir'),'tpm','TPM.nii'), sprintf(',%d', i)]};
    matlabbatch{1}.spm.spatial.preproc.tissue(i).ngaus = 1;
    matlabbatch{1}.spm.spatial.preproc.tissue(i).native = [1 0];
    matlabbatch{1}.spm.spatial.preproc.tissue(i).warped = [0 0];
end

matlabbatch{1}.spm.spatial.preproc.warp.mrf = 1;
matlabbatch{1}.spm.spatial.preproc.warp.cleanup = 1;
matlabbatch{1}.spm.spatial.preproc.warp.reg = [0 0.001 0.5 0.05 0.2];
matlabbatch{1}.spm.spatial.preproc.warp.affreg = 'mni';
matlabbatch{1}.spm.spatial.preproc.warp.fwhm = 0;
matlabbatch{1}.spm.spatial.preproc.warp.samp = 3;
matlabbatch{1}.spm.spatial.preproc.warp.write = [0 0];

spm('defaults','PET');
spm_jobman('initcfg');
spm_jobman('run', matlabbatch);

%% 2. combines GM + WM maps
gmFile = fullfile(path, ['c1' name ext]);
wmFile = fullfile(path, ['c2' name ext]);

if ~isfile(gmFile) || ~isfile(wmFile)
    error('SPM segmentation did not produce c1/c2 images. Aborting.');
end

Vgm = spm_vol(gmFile);
Vwm = spm_vol(wmFile);
gm = spm_read_vols(Vgm);
wm = spm_read_vols(Vwm);

mask = (gm + wm) > 0.2;

%%  3. morphological closing
se = strel('sphere', 2);
mask = imclose(mask, se);

%%  4. write mask
Vout = Vgm;
Vout.fname = maskFile;
spm_write_vol(Vout, mask);
disp(['[spmBrainMask] Wrote mask: ' maskFile]);

%% 5. (optional) write masked anatomical
maskedFile = '';
if doWriteMaskedFile
    maskedFile = fullfile(path, ['masked_' name ext]);
    disp(['[spmBrainMask] Writing masked anatomical: ' maskedFile]);
    Vanat = spm_vol(niifile);
    anat = spm_read_vols(Vanat);
    anat_masked = anat .* double(mask);
    Vmasked = Vanat;
    Vmasked.fname = maskedFile;
    spm_write_vol(Vmasked, anat_masked);
end

%% 6. done
disp('[spmBrainMask] Finished successfully.');
end
