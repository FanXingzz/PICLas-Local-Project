! Trial controller for the six-species axisymmetric helium benchmark.
SUBROUTINE AdaptiveVMPFTargets(population, counts, target)
USE MOD_Globals
USE MOD_Particle_Vars, ONLY: PDM, PartSpecies, nSpecies, AdaptiveReferenceCount, AdaptiveReferenceWeight, &
                             AdaptiveExponent, AdaptiveMaxGain
USE MOD_part_tools, ONLY: GetParticleWeight
IMPLICIT NONE
REAL, INTENT(OUT) :: population(nSpecies), counts(nSpecies), target(nSpecies)
REAL :: totals(2,nSpecies), gain
INTEGER :: p, s

totals = 0.
DO p=1,PDM%ParticleVecLength
  IF (.NOT.PDM%ParticleInside(p)) CYCLE
  s = PartSpecies(p)
  totals(1,s) = totals(1,s) + GetParticleWeight(p)
  totals(2,s) = totals(2,s) + 1.
END DO
#if USE_MPI
CALL MPI_ALLREDUCE(MPI_IN_PLACE,totals,2*nSpecies,MPI_DOUBLE_PRECISION,MPI_SUM,MPI_COMM_PICLAS,iError)
#endif
population = totals(1,:)
counts = totals(2,:)
target = 0.
DO s=2,nSpecies
  gain = MIN(AdaptiveMaxGain,MAX(1.,population(s)/AdaptiveReferenceCount(s))**AdaptiveExponent)
  IF (gain.GT.1.) target(s) = AdaptiveReferenceWeight(s)*gain
END DO
END SUBROUTINE AdaptiveVMPFTargets


SUBROUTINE AdaptiveVMPFMerge(ids, n, speciesId, cell, targetWeight, removed)
USE MOD_Globals_Vars, ONLY: ElementaryCharge
USE MOD_Particle_Vars, ONLY: PartState, Species, AdaptiveMinCount, AdaptiveTipWidth, vMPFSplitThreshold
USE MOD_part_tools, ONLY: GetParticleWeight
IMPLICIT NONE
INTEGER, INTENT(IN) :: n, ids(n), speciesId, cell
REAL, INTENT(IN) :: targetWeight
REAL, INTENT(INOUT) :: removed
INTEGER :: eligible(n), minimum, nEligible, i, p, retain
REAL :: weight, energy
REAL, PARAMETER :: halfGap=5.e-4, excitationEv=19.82

minimum = MAX(AdaptiveMinCount,vMPFSplitThreshold(speciesId))
IF (n.LE.minimum) RETURN
! Retain the original merge policy for electron groups that touch the tip regions.
IF (speciesId.EQ.3) THEN
  IF (ANY(ABS(PartState(1,ids)).GE.halfGap-AdaptiveTipWidth)) RETURN
END IF
weight = 0.
nEligible = 0
DO i=1,n
  p = ids(i)
  IF (speciesId.EQ.3) THEN
    energy = 0.5*Species(speciesId)%MassIC*SUM(PartState(4:6,p)**2)/ElementaryCharge
    IF (energy.GE.excitationEv) CYCLE
  END IF
  nEligible = nEligible+1
  eligible(nEligible) = p
  weight = weight+GetParticleWeight(p)
END DO
IF (nEligible.LE.minimum) RETURN
IF (weight.GE.targetWeight*nEligible) RETURN
! The ceiling bounds the new mean weight. At most half of a group can merge per update.
retain = MAX(minimum,(nEligible+1)/2,CEILING(weight/targetWeight))
IF (retain.GE.nEligible) RETURN
CALL MergeParticles(eligible(1:nEligible),nEligible,retain,cell)
removed = removed+REAL(nEligible-retain)
END SUBROUTINE AdaptiveVMPFMerge


SUBROUTINE WriteAdaptiveVMPF(iteration, population, counts, target, removed)
USE MOD_Globals
USE MOD_Particle_Vars, ONLY: nSpecies
USE MOD_TimeDisc_Vars, ONLY: time, dt
IMPLICIT NONE
INTEGER(KIND=8), INTENT(IN) :: iteration
REAL, INTENT(IN) :: population(nSpecies), counts(nSpecies), target(nSpecies)
REAL, INTENT(INOUT) :: removed(nSpecies)
INTEGER :: out, s
LOGICAL :: exists

#if USE_MPI
CALL MPI_ALLREDUCE(MPI_IN_PLACE,removed,nSpecies,MPI_DOUBLE_PRECISION,MPI_SUM,MPI_COMM_PICLAS,iError)
IF (.NOT.MPIRoot) RETURN
#endif
INQUIRE(FILE='AdaptiveVMPF.csv',EXIST=exists)
OPEN(NEWUNIT=out,FILE='AdaptiveVMPF.csv',STATUS='UNKNOWN',POSITION='APPEND',ACTION='WRITE')
IF (.NOT.exists) WRITE(out,'(A)') 'time_s,step,species,weighted_population,macros_before,target_mean_weight,removed'
DO s=2,nSpecies
  WRITE(out,'(ES24.16,A,I0,A,I0,4(A,ES24.16))') time+dt,',',iteration,',',s, &
    ',',population(s),',',counts(s),',',target(s),',',removed(s)
END DO
CLOSE(out)
END SUBROUTINE WriteAdaptiveVMPF
