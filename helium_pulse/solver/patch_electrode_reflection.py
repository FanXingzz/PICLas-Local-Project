"""Optional constant electron reflection alongside the existing ion SEE model 7."""
from pathlib import Path
import sys

root = Path(sys.argv[1])/"src/particles/surfacemodel"
marker = "! HELIUM_OPTIONAL_ELECTRON_REFLECTION"


def edit(name, replacements):
    path = root/name
    text = path.read_text()
    if marker in text:
        return
    for before, after, count in replacements:
        if text.count(before) != count:
            raise ValueError(f"Unexpected source anchor in {name}: {before!r}")
        text = text.replace(before, after)
    path.write_text(marker+"\n"+text)


edit("surfacemodel_vars.f90", [
    ("REAL, ALLOCATABLE                :: SurfModSEEFitCoeff(:,:)",
     "REAL, ALLOCATABLE                :: SurfModElectronReflection(:) ! probability for model 7; default zero\n"
     "REAL, ALLOCATABLE                :: SurfModSEEFitCoeff(:,:)", 1),
])
edit("surfacemodel_init.f90", [
    ("CALL prms%SetSection(\"SurfaceModel\")",
     "CALL prms%SetSection(\"SurfaceModel\")\n"
     "CALL prms%CreateRealOption('Part-Boundary[$]-SurfModElectronReflection', &\n"
     " 'Electron reflection probability for ion SEE model 7; zero preserves original absorption', &\n"
     " '0.0', numberedmulti=.TRUE.)", 1),
    ("USE MOD_SurfaceModel_Vars      ,ONLY: SurfModSEEFitCoeff,SurfModSEEvMPF,SurfModSEESubWorkFunc,SurfModSEEReflectElectron",
     "USE MOD_SurfaceModel_Vars      ,ONLY: SurfModSEEFitCoeff,SurfModSEEvMPF,SurfModSEESubWorkFunc,SurfModSEEReflectElectron\n"
     "USE MOD_SurfaceModel_Vars      ,ONLY: SurfModElectronReflection", 1),
    ("ALLOCATE(SurfModSEEFitCoeff(1:4, 1:nPartBound))",
     "ALLOCATE(SurfModElectronReflection(nPartBound))\nSurfModElectronReflection = 0.0\n"
     "ALLOCATE(SurfModSEEFitCoeff(1:4, 1:nPartBound))", 1),
    ("  CASE(7)\n", "  CASE(7)\n"
     "    SurfModElectronReflection(iPartBound) = GETREAL('Part-Boundary'//TRIM(hilf2)//'-SurfModElectronReflection')\n"
     "    IF(SurfModElectronReflection(iPartBound).LT.0.0.OR.SurfModElectronReflection(iPartBound).GT.1.0) &\n"
     "      CALL abort(__STAMP__,'Electron reflection probability must lie in [0,1]')\n", 1),
    ("SUBROUTINE FinalizeSurfaceModel()", "SUBROUTINE FinalizeSurfaceModel()", 1),
    ("SDEALLOCATE(SurfModEmissionYield)",
     "SDEALLOCATE(SurfModEmissionYield)\nSDEALLOCATE(SurfModElectronReflection)", 1),
    # FinalizeSurfaceModel imports MOD_SurfaceModel_Vars without an ONLY list.
])
edit("surfacemodel_SEE.f90", [
    ("USE MOD_SurfaceModel_Vars         ,ONLY: SurfModSEEFitCoeff,SurfModSEEvMPF,SurfModSEESubWorkFunc,SurfModSEEReflectElectron",
     "USE MOD_SurfaceModel_Vars         ,ONLY: SurfModSEEFitCoeff,SurfModSEEvMPF,SurfModSEESubWorkFunc,SurfModSEEReflectElectron\n"
     "USE MOD_SurfaceModel_Vars         ,ONLY: SurfModElectronReflection", 1),
    ("CASE(7) ! 7: SEE-I (bombarding electrons are removed, Ar+ on different materials is considered for SEE)\n"
     "  IF(PARTISELECTRON(PartID_IN))THEN ! Bombarding electron\n    RETURN ! nothing to do",
     "CASE(7) ! Constant positive-ion yield, with optional elastic electron reflection\n"
     "  IF(PARTISELECTRON(PartID_IN))THEN\n"
     "    IF(SurfModElectronReflection(locBCID).GT.0.0) THEN\n"
     "      CALL RANDOM_NUMBER(iRan)\n"
     "      IF(iRan.LT.SurfModElectronReflection(locBCID)) ProductSpec(1) = SpecID\n"
     "    END IF\n"
     "    RETURN ! original particle is reflected or absorbed; no new electron", 1),
])
