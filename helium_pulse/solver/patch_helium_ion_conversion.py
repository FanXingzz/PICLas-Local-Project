"""Enable optional He+ conversion in a uniform, pure-He MCC reservoir."""
from pathlib import Path
import sys


def replace_once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise ValueError(f"Unexpected PICLas source near {anchor!r}")
    return text.replace(anchor, replacement, 1)


root = Path(sys.argv[1]) / "src/particles"
path = root / "dsmc/dsmc_vars.f90"
text = path.read_text()
if "He2ElectrodeYield" not in text:
    anchor = "IMPLICIT NONE"
    text = replace_once(text, anchor, anchor+"\nREAL :: He2ElectrodeYield = -1.")
    path.write_text(text)

path = root / "dsmc/dsmc_bg_gas.f90"
text = path.read_text()
if "HeIonConversionRate" not in text:
    text = replace_once(text, "PUBLIC :: DefineParametersBGG,", """REAL :: HeIonConversionRate = 0.
PUBLIC :: HeIonConversionRate
PUBLIC :: DefineParametersBGG,""")
    text = replace_once(text, 'CALL prms%SetSection("Background gas")', """CALL prms%SetSection("Background gas")
CALL prms%CreateRealOption('Particles-He2-ThreeBodyRate', 'He+ conversion rate coefficient [m^6/s]', '0.')""")
    text = replace_once(text, "! 4.) Read-in a background gas distribution", """HeIonConversionRate = GETREAL('Particles-He2-ThreeBodyRate')
IF (HeIonConversionRate.LT.0.) CALL Abort(__STAMP__, 'He2 conversion coefficient must be nonnegative')
IF (HeIonConversionRate.GT.0.) THEN
  IF (nSpecies.NE.4.OR.BGGas%NumberOfSpecies.NE.1.OR.BGGas%UseDistribution.OR.BGGas%UseRegions.OR.UseVarTimeStep) &
    CALL Abort(__STAMP__, 'He2 conversion requires the uniform four-species He model and a fixed time step')
  IF (BGGas%MapBGSpecToSpec(1).NE.1.OR.TRIM(Species(1)%Name).NE.'He'.OR. &
      TRIM(Species(2)%Name).NE.'HeIon1'.OR.TRIM(Species(4)%Name).NE.'He2Ion1') &
    CALL Abort(__STAMP__, 'He2 conversion species order is He, HeIon1, electron, He2Ion1')
END IF

! 4.) Read-in a background gas distribution""")
if "Particles-He2-ElectrodeYield" not in text:
    anchor = "CALL prms%CreateRealOption('Particles-He2-ThreeBodyRate', 'He+ conversion rate coefficient [m^6/s]', '0.')"
    text = replace_once(text, anchor, anchor+
                        "\nCALL prms%CreateRealOption('Particles-He2-ElectrodeYield', 'He2+ yield for SEE model 7', '-1.')")
    text = replace_once(text, "HeIonConversionRate = GETREAL('Particles-He2-ThreeBodyRate')",
                        """HeIonConversionRate = GETREAL('Particles-He2-ThreeBodyRate')
He2ElectrodeYield = GETREAL('Particles-He2-ElectrodeYield')
IF (He2ElectrodeYield.GT.1.) CALL Abort(__STAMP__, 'He2 electrode yield must not exceed one')
IF (HeIonConversionRate.LE.0.) He2ElectrodeYield = -1.""")
text = text.replace("REAL :: He2ElectrodeYield = -1.\nPUBLIC :: HeIonConversionRate, He2ElectrodeYield",
                    "PUBLIC :: HeIonConversionRate")
before, initialization = text.split("SUBROUTINE BGGas_Initialize()", 1)
before_end, after_end = initialization.split("END SUBROUTINE BGGas_Initialize", 1)
anchor = "USE MOD_DSMC_Vars             ,ONLY: BGGas"
if anchor+", He2ElectrodeYield" not in before_end:
    before_end = replace_once(before_end, anchor, anchor+", He2ElectrodeYield")
text = before+"SUBROUTINE BGGas_Initialize()"+before_end+"END SUBROUTINE BGGas_Initialize"+after_end
path.write_text(text)

path = root / "mcc/mcc.f90"
text = path.read_text()
if "HeIonConversionRate" not in text:
    text = replace_once(text, "USE MOD_DSMC_BGGas              ,ONLY: BGGas_AssignParticleProperties",
                        "USE MOD_DSMC_BGGas              ,ONLY: BGGas_AssignParticleProperties, HeIonConversionRate")
    text = replace_once(text, "REAL                          :: ProbNull, dtVar",
                        "REAL                          :: ProbNull, dtVar, ConversionProb, ReservoirTemp")
    text = replace_once(text, "! 1.) Counting the number of particles per species and creating a species-specific particle index list",
                        """! He+ + He + He -> He2+ + He. The fixed reservoir absorbs stabilization recoil and energy.
IF (HeIonConversionRate.GT.0.) THEN
  ConversionProb = 1.-EXP(-HeIonConversionRate*BGGas%NumberDensity(1)**2*dt)
  ReservoirTemp = Species(1)%Init(1)%MWTemperatureIC
  DO iLoop = 1, nPart
    iPart = iPartIndx_NodeTotal(iLoop)
    IF (PartSpecies(iPart).NE.2) CYCLE
    CALL RANDOM_NUMBER(iRan)
    IF (iRan.GE.ConversionProb) CYCLE
    VeloBGGPart = CalcVelocity_maxwell_particle(1,[ReservoirTemp,ReservoirTemp,ReservoirTemp])
    PartState(4:6,iPart) = (Species(2)%MassIC*PartState(4:6,iPart)+Species(1)%MassIC*VeloBGGPart)/Species(4)%MassIC
    PartSpecies(iPart) = 4
  END DO
END IF

! 1.) Counting the number of particles per species and creating a species-specific particle index list""")
if "IF (ALLOCATED(PartIntEn(iPart)%EElec)) PartIntEn(iPart)%EElec = 0." not in text:
    anchor = "    PartSpecies(iPart) = 4"
    text = replace_once(text, anchor, "    IF (ALLOCATED(PartIntEn(iPart)%EElec)) PartIntEn(iPart)%EElec = 0.\n"+anchor)
# Upgrade source trees that already have the conversion patch. PartState is (component, particle).
old_update = "PartState(iPart,4:6) = (Species(2)%MassIC*PartState(iPart,4:6)+Species(1)%MassIC*VeloBGGPart)/Species(4)%MassIC"
if old_update in text:
    text = replace_once(text, old_update, old_update.replace("PartState(iPart,4:6)", "PartState(4:6,iPart)"))
path.write_text(text)

path = root / "surfacemodel/surfacemodel_SEE.f90"
text = path.read_text()
if "He2ElectrodeYield" not in text:
    anchor = "USE MOD_SurfaceModel_Vars         ,ONLY: SurfModElectronReflection"
    text = replace_once(text, anchor, anchor+"\nUSE MOD_DSMC_Vars                  ,ONLY: He2ElectrodeYield")
    anchor = "    IF(SurfModEmissionYield(locBCID).GE.1.0) ProductSpecNbr = INT(SurfModEmissionYield(locBCID))"
    text = replace_once(text, anchor, """    SEEYield = SurfModEmissionYield(locBCID)
    IF(SpecID.EQ.4.AND.He2ElectrodeYield.GE.0.) SEEYield = He2ElectrodeYield
    IF(SEEYield.GE.1.0) ProductSpecNbr = INT(SEEYield)""")
    text = replace_once(text, "MOD(SurfModEmissionYield(locBCID), 1.0)", "MOD(SEEYield, 1.0)")
text = text.replace("USE MOD_DSMC_BGGas                 ,ONLY: He2ElectrodeYield",
                    "USE MOD_DSMC_Vars                  ,ONLY: He2ElectrodeYield")
path.write_text(text)
