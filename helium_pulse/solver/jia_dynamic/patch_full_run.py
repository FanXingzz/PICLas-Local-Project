"""Apply the case's physical needle gap to the adaptive electron protection."""

from pathlib import Path
import sys


def replace(path, changes):
    text = path.read_text(encoding="utf-8")
    for old, new in changes:
        if text.count(old) != 1:
            raise ValueError(f"{path}: expected one match for {old!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def configure(source):
    particles = source / "src/particles"
    replace(particles / "particle_vars.f90", [
        ("REAL :: AdaptiveExponent, AdaptiveMaxGain, AdaptiveTipWidth",
         "REAL :: AdaptiveExponent, AdaptiveMaxGain, AdaptiveTipWidth, AdaptiveTipHalfGap"),
    ])
    replace(particles / "particle_init.f90", [
        ("CALL prms%CreateRealOption('Part-AdaptiveVMPFTipWidth','Electron tip protection distance in meters','2.5e-5')",
         "CALL prms%CreateRealOption('Part-AdaptiveVMPFTipWidth','Electron tip protection distance in meters','2.5e-5')\n"
         "CALL prms%CreateRealOption('Part-AdaptiveVMPFTipHalfGap','Half of the needle tip gap in meters','5.e-4')"),
        ("    AdaptiveTipWidth = GETREAL('Part-AdaptiveVMPFTipWidth')",
         "    AdaptiveTipWidth = GETREAL('Part-AdaptiveVMPFTipWidth')\n"
         "    AdaptiveTipHalfGap = GETREAL('Part-AdaptiveVMPFTipHalfGap')"),
        ("        .NOT.(AdaptiveTipWidth.GE.0..AND.AdaptiveTipWidth.LE.5.e-4)) THEN",
         "        .NOT.(AdaptiveTipHalfGap.GT.0..AND.AdaptiveTipWidth.GE.0..AND. &\n"
         "        AdaptiveTipWidth.LE.MIN(AdaptiveTipHalfGap,5.e-4))) THEN"),
        ("Invalid adaptive vMPF benchmark settings", "Invalid adaptive vMPF settings"),
        ("Adaptive vMPF requires positive checkpoint weights and populations",
         "Adaptive vMPF requires positive reference weights and populations"),
        ("Adaptive merge for the six-species helium benchmark", "Adaptive merge for six-species helium"),
        ("Maximum target weight relative to the checkpoint", "Maximum target weight relative to the reference"),
        ("Weighted checkpoint population", "Weighted reference population"),
        ("Mean checkpoint macro weight", "Mean reference macro weight"),
    ])
    replace(particles / "particle_vMPF.f90", [
        ("  IF (gain.GT.1.) target(s) = AdaptiveReferenceWeight(s)*gain",
         "  IF (gain.GT.1..AND.counts(s).GT.0.) THEN\n"
         "    ! Seed and reaction-product macro weights may differ substantially.\n"
         "    target(s) = MIN(AdaptiveReferenceWeight(s)*gain,population(s)/counts(s)*AdaptiveMaxGain)\n"
         "  END IF"),
        ("USE MOD_Particle_Vars, ONLY: PartState, Species, AdaptiveMinCount, AdaptiveTipWidth, vMPFSplitThreshold",
         "USE MOD_Particle_Vars, ONLY: PartState, Species, AdaptiveMinCount, AdaptiveTipWidth, &\n"
         "                             AdaptiveTipHalfGap, vMPFSplitThreshold"),
        ("REAL, PARAMETER :: halfGap=5.e-4, excitationEv=19.82", "REAL, PARAMETER :: excitationEv=19.82"),
        ("GE.halfGap-AdaptiveTipWidth", "GE.AdaptiveTipHalfGap-AdaptiveTipWidth"),
    ])


if __name__ == "__main__":
    configure(Path(sys.argv[1]))
