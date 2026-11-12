"""Attach the opt-in Jia helium chemistry to the pinned PICLas 4.3 source."""

from pathlib import Path
import sys


def replace(source, anchor, updated):
    if updated in source:
        return source
    if source.count(anchor) != 1:
        raise ValueError(f"Unexpected PICLas source near {anchor!r}")
    return source.replace(anchor, updated, 1)


root = Path(sys.argv[1]) / "src/particles"
path = root / "dsmc/dsmc_bg_gas.f90"
source = path.read_text()
anchor = "PUBLIC :: HeIonConversionRate\n"
source = replace(source, anchor, anchor + "LOGICAL, PROTECTED, PUBLIC :: UseJiaChemistry = .FALSE.\n")
anchor = 'CALL prms%SetSection("Background gas")'
source = replace(source, anchor, anchor + """
CALL prms%CreateLogicalOption('Particles-JiaChemistry', 'Enable six-species helium MCC chemistry', '.FALSE.')""")
anchor = "IF (HeIonConversionRate.LE.0.) He2ElectrodeYield = -1."
source = replace(source, anchor, """UseJiaChemistry = GETLOGICAL('Particles-JiaChemistry')
IF (HeIonConversionRate.LE.0..AND..NOT.UseJiaChemistry) He2ElectrodeYield = -1.
IF (UseJiaChemistry) THEN
  IF (nSpecies.NE.6.OR.BGGas%NumberOfSpecies.NE.1.OR.BGGas%UseDistribution.OR.BGGas%UseRegions.OR.UseVarTimeStep) &
    CALL Abort(__STAMP__, 'Jia chemistry requires six species, a uniform He reservoir and a fixed time step')
  IF (HeIonConversionRate.GT.0..OR.BGGas%MapBGSpecToSpec(1).NE.1) &
    CALL Abort(__STAMP__, 'Jia chemistry includes R16 and requires species 1 as the sole reservoir')
  IF (ANY(Species(:)%Name.NE.[CHARACTER(LEN=8) :: 'He','HeIon1','electron','He2Ion1','HeMeta','He2Meta'])) &
    CALL Abort(__STAMP__, 'Jia chemistry species order is He, HeIon1, electron, He2Ion1, HeMeta, He2Meta')
END IF""")
path.write_text(source)

path = root / "mcc/mcc.f90"
source = path.read_text()
anchor = "PUBLIC :: MonteCarloCollision\n"
source = replace(source, anchor, anchor + """PUBLIC :: WriteJiaReactionCounts
REAL :: JiaReactionCounts(23) = 0.
REAL :: JiaMaxHazard = 0.
""")
anchor = "USE MOD_DSMC_BGGas              ,ONLY: BGGas_AssignParticleProperties, HeIonConversionRate"
source = replace(source, anchor, anchor + ", UseJiaChemistry")
anchor = "        CALL DSMC_perform_collision(iPair,iElem)"
source = replace(source, anchor, anchor + """
        IF (UseJiaChemistry.AND.iSpec.EQ.3.AND.jSpec.EQ.1) THEN
          CALL JiaBackgroundEvent(PartIndex,bggPartIndex)
        END IF""")
anchor = "! Delete the dummy particle"
source = replace(source, anchor, """IF (UseJiaChemistry) CALL JiaCellReactions(iElem,GlobalElemID,Volume,dt)
"""+anchor)
marker = "! Jia chemistry implementation\n"
if marker in source:
    source = source[:source.index(marker)].rstrip() + "\n\nEND MODULE MOD_MCC\n"
anchor = "END MODULE MOD_MCC"
implementation = Path(__file__).with_name("jia_chemistry.f90").read_text()
source = replace(source, anchor, marker + implementation + "\n" + anchor)
path.write_text(source)

path = root / "dsmc/dsmc_main.f90"
source = path.read_text()
anchor = "USE MOD_MCC                   ,ONLY: MonteCarloCollision"
source = replace(source, anchor, anchor + ", WriteJiaReactionCounts")
anchor = "END IF ! CollisMode.NE.0\n"
source = replace(source, anchor, anchor + "CALL WriteJiaReactionCounts()\n")
path.write_text(source)
