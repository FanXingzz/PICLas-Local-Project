"""Track quartz secondaries from their known birth side and drain their tracking queue."""
from pathlib import Path
import sys


particles = Path(sys.argv[1]) / "src/particles"
path = particles / "surfacemodel/surfacemodel_tools.f90"
source = path.read_text(encoding="utf-8")
marker = "! Quartz secondary starts on a known rotational boundary side."
if marker not in source:
    before, subroutine = source.split("SUBROUTINE SurfaceModelParticleEmission(", 1)
    original = "USE MOD_Particle_Vars             ,ONLY: InterPlanePartNumber, InterPlanePartIndx, PDM"
    assert subroutine.count(original) == 1
    subroutine = subroutine.replace(
        original, original + ", PEM\nUSE MOD_Symmetry_Vars             ,ONLY: Symmetry", 1)
    anchor = "    ! Add newly created particles to the list of particles to track after the regular tracking loop"
    assert subroutine.count(anchor) == 1
    subroutine = subroutine.replace(anchor, f"""    {marker}
    ! The negative side ID selects the existing exact-rotation boundary recheck
    ! and suppresses the round-off root at the birth point.
    IF(Symmetry%AxisymmetricExact.AND.PartBound%SurfaceModel(locBCID).EQ.11) &
      PEM%LastGlobalElemID(NewPartID) = -SideID
{anchor}""", 1)
    path.write_text(before + "SUBROUTINE SurfaceModelParticleEmission(" + subroutine, encoding="utf-8")

path = particles / "tracking/particle_triatracking.f90"
source = path.read_text(encoding="utf-8")
marker = "! A grazing secondary can reach the wall again within the same time step."
if marker not in source:
    start = "! 2) Loop again over all inter plane particles\nIF(InterPlanePartNumber.GT.0) THEN\n  DO i = 1,InterPlanePartNumber"
    end = "  END DO ! i = 1,InterPlanePartNumber\nEND IF"
    assert source.count(start) == source.count(end) == 1
    first, queued = source.split(start, 1)
    body, last = queued.split(end, 1)
    body = "\n".join(line[2:] if line.startswith("  ") else line for line in body.split("\n"))
    path.write_text(first + f"""{marker}
! Track appended entries as well as those already in the queue.
i = 1
DO WHILE (i.LE.InterPlanePartNumber)""" + body + "  i = i + 1\nEND DO" + last, encoding="utf-8")
