"""Add the independent adaptive merge controller to the pinned PICLas source."""
from pathlib import Path
import sys


def replace(path, changes):
    text = path.read_text(encoding="utf-8")
    for old, new in changes:
        if text.count(old) != 1:
            raise ValueError(f"{path}: unexpected upstream text for {old.splitlines()[0]}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8", newline="\n")


root = Path(sys.argv[1])/"src/particles"
code = Path(__file__).with_name("adaptive_vmpf.f90").read_text(encoding="utf-8")
replace(root/"particle_vars.f90", [
    ("! Variable particle weighting (vMPF)\n", """! Variable particle weighting (vMPF)
LOGICAL :: UseAdaptiveVMPF = .FALSE.
INTEGER :: AdaptiveInterval, AdaptiveMinCount
REAL :: AdaptiveExponent, AdaptiveMaxGain, AdaptiveTipWidth
REAL :: AdaptiveReferenceCount(6), AdaptiveReferenceWeight(6)
"""),
])
replace(root/"particle_init.f90", [
    ('CALL prms%SetSection("vMPF")\n', """CALL prms%SetSection("vMPF")
CALL prms%CreateLogicalOption('Part-AdaptiveVMPF','Adaptive merge for the six-species helium benchmark','.FALSE.')
CALL prms%CreateRealOption('Part-AdaptiveVMPFExponent','Exponent of weighted population growth','0.5')
CALL prms%CreateIntOption('Part-AdaptiveVMPFInterval','Controller update interval in particle steps','50')
CALL prms%CreateIntOption('Part-AdaptiveVMPFMinCount','Minimum retained members of an adaptive group','16')
CALL prms%CreateRealOption('Part-AdaptiveVMPFMaxGain','Maximum target weight relative to the checkpoint','2.0')
CALL prms%CreateRealOption('Part-AdaptiveVMPFTipWidth','Electron tip protection distance in meters','2.5e-5')
CALL prms%CreateRealOption('Part-Species[$]-vMPFReferencePopulation','Weighted checkpoint population','0.',numberedmulti=.TRUE.)
CALL prms%CreateRealOption('Part-Species[$]-vMPFReferenceWeight','Mean checkpoint macro weight','0.',numberedmulti=.TRUE.)
"""),
    ("  vMPFSplitAndMergeStep = GETINT('Part-vMPFSplitAndMergeStep')\n", """  vMPFSplitAndMergeStep = GETINT('Part-vMPFSplitAndMergeStep')
  UseAdaptiveVMPF = GETLOGICAL('Part-AdaptiveVMPF')
  IF (UseAdaptiveVMPF) THEN
    AdaptiveExponent = GETREAL('Part-AdaptiveVMPFExponent')
    AdaptiveInterval = GETINT('Part-AdaptiveVMPFInterval')
    AdaptiveMinCount = GETINT('Part-AdaptiveVMPFMinCount')
    AdaptiveMaxGain = GETREAL('Part-AdaptiveVMPFMaxGain')
    AdaptiveTipWidth = GETREAL('Part-AdaptiveVMPFTipWidth')
    IF (nSpecies.NE.6.OR.vMPFSplitAndMergeStep.NE.1.OR. &
        .NOT.(AdaptiveExponent.GE.0..AND.AdaptiveExponent.LE.1.).OR. &
        AdaptiveInterval.LT.1.OR.AdaptiveInterval.GT.1000.OR.AdaptiveMinCount.LT.4.OR.AdaptiveMinCount.GT.100.OR. &
        .NOT.(AdaptiveMaxGain.GE.1..AND.AdaptiveMaxGain.LE.8.).OR. &
        .NOT.(AdaptiveTipWidth.GE.0..AND.AdaptiveTipWidth.LE.5.e-4)) THEN
      CALL Abort(__STAMP__,'Invalid adaptive vMPF benchmark settings')
    END IF
    DO iSpec=2,nSpecies
      WRITE(hilf,'(I0)') iSpec
      AdaptiveReferenceCount(iSpec) = GETREAL('Part-Species'//TRIM(hilf)//'-vMPFReferencePopulation')
      AdaptiveReferenceWeight(iSpec) = GETREAL('Part-Species'//TRIM(hilf)//'-vMPFReferenceWeight')
      IF (.NOT.(AdaptiveReferenceCount(iSpec).GT.0..AND.AdaptiveReferenceWeight(iSpec).GT.0.)) THEN
        CALL Abort(__STAMP__,'Adaptive vMPF requires positive checkpoint weights and populations')
      END IF
    END DO
  END IF
"""),
])
replace(root/"particle_vMPF.f90", [
    ("USE MOD_TimeDisc_Vars         ,ONLY: iter\n", """USE MOD_TimeDisc_Vars         ,ONLY: iter
USE MOD_Particle_Vars         ,ONLY: UseAdaptiveVMPF, AdaptiveInterval, AdaptiveExponent
"""),
    ("INTEGER, ALLOCATABLE  :: iPartIndx_Node(:,:), nPart(:)\n", """INTEGER, ALLOCATABLE  :: iPartIndx_Node(:,:), nPart(:)
LOGICAL :: adaptiveSample
REAL :: population(nSpecies), macroCounts(nSpecies), targetWeights(nSpecies), adaptiveRemoved(nSpecies)
"""),
    ("IF(MOD(iter,INT(vMPFSplitAndMergeStep,8)).NE.0) RETURN\n", """IF(MOD(iter,INT(vMPFSplitAndMergeStep,8)).NE.0) RETURN
adaptiveSample = .FALSE.
IF (UseAdaptiveVMPF) THEN
  adaptiveSample = MOD(iter,INT(AdaptiveInterval,8)).EQ.0 .AND. AdaptiveExponent.GT.0.
END IF
targetWeights = 0.
adaptiveRemoved = 0.
IF (adaptiveSample) CALL AdaptiveVMPFTargets(population,macroCounts,targetWeights)
"""),
    ("      CALL SplitParticles(iPartIndx_Node(iSpec,1:nPart(iSpec)), nPart(iSpec), vMPFSplitThreshold(iSpec))\n", """      CALL SplitParticles(iPartIndx_Node(iSpec,1:nPart(iSpec)), nPart(iSpec), vMPFSplitThreshold(iSpec))
    ELSE IF(targetWeights(iSpec).GT.0..AND.vMPFMergeThreshold(iSpec).GT.0) THEN
      CALL AdaptiveVMPFMerge(iPartIndx_Node(iSpec,1:nPart(iSpec)),nPart(iSpec),iSpec,iElem, &
                             targetWeights(iSpec),adaptiveRemoved(iSpec))
"""),
    ("END SUBROUTINE SplitAndMerge\n", """IF (adaptiveSample) CALL WriteAdaptiveVMPF(iter,population,macroCounts,targetWeights,adaptiveRemoved)
END SUBROUTINE SplitAndMerge

""" + code + "\n"),
])
