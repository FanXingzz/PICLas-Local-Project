import sys
from pathlib import Path

path = Path(sys.argv[1]) / "src/equations/poisson/equation.f90"
source = path.read_text()

def insert(anchor, content):
    global source
    if source.count(anchor) != 1:
        raise ValueError(f"Expected one source anchor: {anchor!r}")
    source = source.replace(anchor, content + anchor)

insert("CONTAINS\n", """REAL, PRIVATE :: PulsePeak, PulseRise, PulseFlat, PulseFall

""")
insert("CALL prms%CreateRealArrayOption('RefState'", """CALL prms%CreateRealOption('PulsePeak', 'Positive trapezoidal electrode peak [V]', '1500.')
CALL prms%CreateRealOption('PulseRise', 'Pulse rise time [s]', '2.e-9')
CALL prms%CreateRealOption('PulseFlat', 'Pulse plateau time [s]', '5.e-9')
CALL prms%CreateRealOption('PulseFall', 'Pulse fall time [s]', '2.e-9')
""")
insert("IniAmplitude  = GETREAL", """PulsePeak = GETREAL('PulsePeak')
PulseRise = GETREAL('PulseRise')
PulseFlat = GETREAL('PulseFlat')
PulseFall = GETREAL('PulseFall')
""")
insert("CASE(1001) ! linear in y-z", """CASE(9100) ! Trapezoidal voltage on a type-2 Dirichlet boundary
  IF (.NOT.PRESENT(t)) CALL CollectiveStop(__STAMP__,'Pulse boundary requires time')
  IF (.NOT.(PulsePeak.GT.0.)) CALL CollectiveStop(__STAMP__,'PulsePeak must be positive')
  IF (PulseRise.LE.0. .OR. PulseFlat.LT.0. .OR. PulseFall.LE.0.) &
    CALL CollectiveStop(__STAMP__,'Invalid pulse duration')
  Resu(:) = PulsePeak * MAX(0., MIN(1., t/PulseRise, (PulseRise+PulseFlat+PulseFall-t)/PulseFall))
""")
path.write_text(source)
