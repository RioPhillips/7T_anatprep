"""
anatprep: Anatomical preprocessing pipeline for 7T MP2RAGE data.

Takes BIDS-organized rawdata through SPM masking,
pymp2rage fitting, denoising, CAT12 segmentation, sinus masking,
and iterative brainmask refinement with fMRIprep.
"""

__version__ = "0.1.0"
__author__ = "Rio Phillips"
