! Six-species, pure-He chemistry for axisymmetric MCC with variable macro weights.
! Species order: He, He+, electron, He2+, He*, He2*.

SUBROUTINE JiaBackgroundEvent(electronID,gasID)
USE MOD_Globals_Vars, ONLY: ElementaryCharge
USE MOD_DSMC_Vars, ONLY: PartIntEn
USE MOD_Particle_Vars, ONLY: PartSpecies, PartMPF
IMPLICIT NONE
INTEGER, INTENT(IN) :: electronID, gasID

! PICLas has already scattered the electron and charged the excitation energy.
! Retain the excited reservoir atom as a transported metastable.
IF (PartSpecies(gasID).EQ.1.AND.PartSpecies(electronID).EQ.3) THEN
  IF (ALLOCATED(PartIntEn(gasID)%EElec)) THEN
    IF (ABS(PartIntEn(gasID)%EElec(1)/ElementaryCharge-19.82).LT.1.E-5) THEN
      PartIntEn(gasID)%EElec = 0.
      PartSpecies(gasID) = 5
      JiaReactionCounts(2) = JiaReactionCounts(2) + PartMPF(electronID)
    ELSE
      JiaReactionCounts(1) = JiaReactionCounts(1) + PartMPF(electronID)
    END IF
  END IF
ELSE IF (PartSpecies(gasID).EQ.2.OR.PartSpecies(electronID).EQ.2) THEN
  JiaReactionCounts(3) = JiaReactionCounts(3) + PartMPF(electronID)
END IF
END SUBROUTINE JiaBackgroundEvent


SUBROUTINE JiaCellReactions(cell,globalCell,volume,step)
USE MOD_Globals, ONLY: Abort
USE MOD_Globals_Vars, ONLY: BoltzmannConst, ElementaryCharge
USE MOD_DSMC_Vars, ONLY: BGGas, PartIntEn
USE MOD_Particle_Vars, ONLY: PEM, PDM, PartSpecies, PartState, PartMPF, Species
USE MOD_part_operations, ONLY: CreateParticle, RemoveParticle
USE MOD_part_tools, ONLY: CalcVelocity_maxwell_particle
IMPLICIT NONE
INTEGER, INTENT(IN) :: cell, globalCell
REAL, INTENT(IN) :: volume, step
INTEGER :: ids(PEM%pNumber(cell)), i, j, id, spec, left, right, a, b, channel, first, last, electronID, heavyID
INTEGER :: productIon, productNeutral
REAL :: nHe, gasTemp, gasTe, te, ratio, electronWeight, electronMean(3), electronMoment
REAL :: relative(3), collisionEnergy, w, hazard, pick, cumulative, rates(23), randomValue, thirdDensity
REAL :: vElectron(3), vHeavy(3), pElectron(3), pHeavy(3), center(3), energy, firstEnergy
REAL :: vNew(3), reducedMass, eMass, heavyMass, ionMass, direction(3), tempVelocity(3)
REAL, PARAMETER :: excitation(6) = [0.,24.587,0.,21.30,19.82,17.90]

nHe = BGGas%NumberDensity(1)
gasTemp = Species(1)%Init(1)%MWTemperatureIC
gasTe = BoltzmannConst*gasTemp/ElementaryCharge
eMass = Species(3)%MassIC
electronWeight = 0.
electronMean = 0.
electronMoment = 0.
id = PEM%pStart(cell)
DO i=1,SIZE(ids)
  ids(i) = id
  IF (PDM%ParticleInside(id).AND.PartSpecies(id).EQ.3) THEN
    electronWeight = electronWeight + PartMPF(id)
    electronMean = electronMean + PartMPF(id)*PartState(4:6,id)
    electronMoment = electronMoment + PartMPF(id)*SUM(PartState(4:6,id)**2)
  END IF
  id = PEM%pNext(id)
END DO
te = gasTe
IF (electronWeight.GT.0.) THEN
  electronMean = electronMean/electronWeight
  te = MAX(gasTe,eMass*(electronMoment/electronWeight-SUM(electronMean**2))/(3.*ElementaryCharge))
END IF
ratio = te/gasTe

! Each distinct unordered pair is tried once. The macro weight reacted is
! min(w1,w2); multiplying by max(w1,w2) recovers the physical pair count.
DO i=1,SIZE(ids)-1
  left = ids(i)
  IF (.NOT.PDM%ParticleInside(left)) CYCLE
  DO j=i+1,SIZE(ids)
    IF (.NOT.PDM%ParticleInside(left)) EXIT
    right = ids(j)
    IF (.NOT.PDM%ParticleInside(right)) CYCLE
    a = MIN(PartSpecies(left),PartSpecies(right))
    b = MAX(PartSpecies(left),PartSpecies(right))
    IF (a.LT.2.OR.(a.EQ.2.AND.b.NE.3).OR.(a.EQ.4).OR.(a.EQ.3.AND.b.EQ.3)) CYCLE
    rates = 0.
    IF (a.EQ.3.OR.(a.EQ.2.AND.b.EQ.3)) THEN
      electronID = left
      IF (PartSpecies(left).NE.3) electronID = right
      heavyID = left+right-electronID
      spec = PartSpecies(heavyID)
      thirdDensity = MAX(0.,electronWeight-PartMPF(electronID))/volume
      SELECT CASE(spec)
      CASE(2)
        first = 8
        last = 10
        rates(8) = 6.78E-19/SQRT(te)
        rates(9) = 7.8E-50*ratio**(-4.4)*thirdDensity
        rates(10) = 7.4E-47*ratio**(-2.)*nHe
      CASE(4)
        first = 11
        last = 15
        rates(11) = 7.12E-21*ratio**(-1.5)
        rates(12) = 2.8E-32*thirdDensity
        rates(13) = 1.2E-33*thirdDensity
        rates(14) = 3.5E-39*nHe
        rates(15) = 1.5E-39*nHe
      CASE(5,6)
        heavyMass = Species(spec)%MassIC
        reducedMass = eMass*heavyMass/(eMass+heavyMass)
        relative = PartState(4:6,electronID)-PartState(4:6,heavyID)
        collisionEnergy = 0.5*reducedMass*SUM(relative**2)/ElementaryCharge
        IF (spec.EQ.5) THEN
          first = 4
          last = 6
          rates(4) = JiaStepIonization(collisionEnergy,4.78,1.28E-13,0.60)
          rates(6) = 2.9E-15
        ELSE
          first = 5
          last = 7
          rates(5) = JiaStepIonization(collisionEnergy,3.4,9.75E-16,0.71)
          rates(7) = 3.8E-15
        END IF
      CASE DEFAULT
        CYCLE
      END SELECT
    ELSE
      ! Jia uses a mass-action rate k*n^2 for identical reactants.
      ! There are half as many unordered pairs as ordered pairs.
      first = 17+2*(a+b-10)
      last = first+1
      SELECT CASE(first)
      CASE(17)
        rates(17:18) = 2.*[2.03E-15,8.7E-16]
      CASE(19)
        rates(19:20) = [2.0E-15,5.0E-16]
      CASE(21)
        rates(21:22) = 2.*[1.5E-15,3.0E-16]
      CASE DEFAULT
        CYCLE
      END SELECT
    END IF
    hazard = SUM(rates(first:last))*MAX(PartMPF(left),PartMPF(right))*step/volume
    JiaMaxHazard = MAX(JiaMaxHazard,hazard)
    IF (hazard.LE.0.) CYCLE
    CALL RANDOM_NUMBER(randomValue)
    IF (randomValue.GE.1.-EXP(-hazard)) CYCLE
    CALL RANDOM_NUMBER(randomValue)
    pick = randomValue*SUM(rates(first:last))
    cumulative = 0.
    DO channel=first,last-1
      cumulative = cumulative+rates(channel)
      IF (pick.LT.cumulative) EXIT
    END DO
    w = MIN(PartMPF(left),PartMPF(right))
    IF (channel.LE.15) THEN
      vElectron = PartState(4:6,electronID)
      vHeavy = PartState(4:6,heavyID)
      pElectron = PartState(1:3,electronID)
      pHeavy = PartState(1:3,heavyID)
      CALL consume(electronID,w)
      CALL consume(heavyID,w)
      electronWeight = MAX(0.,electronWeight-w)
      SELECT CASE(channel)
      CASE(4,5)
        productIon = 2
        energy = collisionEnergy-4.78
        IF (channel.EQ.5) THEN
          productIon = 4
          energy = collisionEnergy-3.4
        END IF
        ionMass = Species(productIon)%MassIC
        center = (eMass*vElectron+heavyMass*vHeavy)/(eMass+heavyMass)
        CALL RANDOM_NUMBER(randomValue)
        ! Resolve outgoing electrons in the Jacobi coordinates of the electron pair
        ! and of its center relative to the ion. This retains recoil and energy.
        firstEnergy = randomValue*energy
        CALL JiaDirection(direction)
        relative = SQRT(2.*firstEnergy*ElementaryCharge/(0.5*eMass))*direction
        CALL JiaDirection(direction)
        reducedMass = (2.*eMass)*ionMass/(2.*eMass+ionMass)
        vNew = SQRT(2.*(energy-firstEnergy)*ElementaryCharge/reducedMass)*direction
        CALL emit(productIon,pHeavy,center-(2.*eMass/(2.*eMass+ionMass))*vNew,w)
        vNew = center+(ionMass/(2.*eMass+ionMass))*vNew
        CALL emit(3,pElectron,vNew+0.5*relative,w)
        CALL emit(3,pHeavy,vNew-0.5*relative,w)
      CASE(6,7)
        ! Superelastic energy release, with the recoiling He products absorbed by the gas reservoir.
        center = (eMass*vElectron+heavyMass*vHeavy)/(eMass+heavyMass)
        energy = collisionEnergy+excitation(spec)
        CALL JiaDirection(direction)
        vNew = center+(heavyMass/(eMass+heavyMass))*SQRT(2.*energy*ElementaryCharge/reducedMass)*direction
        CALL emit(3,pElectron,vNew,w)
      CASE(8:15)
        ! Spectator e or background He remain in their reservoirs for these
        ! zero electron-energy-source channels in the fluid reaction table.
        productNeutral = 5
        IF (channel.EQ.13.OR.channel.EQ.15) productNeutral = 6
        CALL emit(productNeutral,pHeavy,vHeavy,w)
      END SELECT
    ELSE
      pHeavy = PartState(1:3,left)
      heavyMass = Species(PartSpecies(left))%MassIC
      ionMass = Species(PartSpecies(right))%MassIC
      center = (heavyMass*PartState(4:6,left)+ionMass*PartState(4:6,right))/(heavyMass+ionMass)
      CALL consume(left,w)
      CALL consume(right,w)
      productIon = 4
      IF (MOD(channel,2).EQ.0) productIon = 2
      energy = excitation(a)+excitation(b)-excitation(productIon)
      ionMass = Species(productIon)%MassIC
      reducedMass = eMass*ionMass/(eMass+ionMass)
      CALL JiaDirection(direction)
      relative = SQRT(2.*energy*ElementaryCharge/reducedMass)*direction
      CALL emit(productIon,pHeavy,center-eMass/(eMass+ionMass)*relative,w)
      CALL emit(3,pHeavy,center+ionMass/(eMass+ionMass)*relative,w)
    END IF
    JiaReactionCounts(channel) = JiaReactionCounts(channel)+w
  END DO
END DO

! Background assisted reactions with only one non-reservoir reactant.
DO i=1,SIZE(ids)
  id = ids(i)
  IF (.NOT.PDM%ParticleInside(id)) CYCLE
  spec = PartSpecies(id)
  SELECT CASE(spec)
  CASE(2)
    channel = 16
    productNeutral = 4
    hazard = 1.1E-43*nHe**2*step
  CASE(5)
    channel = 23
    productNeutral = 6
    hazard = 2.0E-46*nHe**2*step
  CASE DEFAULT
    CYCLE
  END SELECT
  JiaMaxHazard = MAX(JiaMaxHazard,hazard)
  CALL RANDOM_NUMBER(randomValue)
  IF (randomValue.GE.1.-EXP(-hazard)) CYCLE
  tempVelocity = CalcVelocity_maxwell_particle(1,[gasTemp,gasTemp,gasTemp])
  PartState(4:6,id) = (Species(spec)%MassIC*PartState(4:6,id)+Species(1)%MassIC*tempVelocity) &
                      /Species(productNeutral)%MassIC
  IF (ALLOCATED(PartIntEn(id)%EElec)) PartIntEn(id)%EElec = 0.
  PartSpecies(id) = productNeutral
  JiaReactionCounts(channel) = JiaReactionCounts(channel)+PartMPF(id)
END DO

CONTAINS

SUBROUTINE consume(part,weight)
INTEGER, INTENT(IN) :: part
REAL, INTENT(IN) :: weight
IF (PartMPF(part).GT.weight) THEN
  PartMPF(part) = PartMPF(part)-weight
ELSE
  CALL RemoveParticle(part)
END IF
END SUBROUTINE consume

SUBROUTINE emit(product,pos,velo,weight)
INTEGER, INTENT(IN) :: product
REAL, INTENT(IN) :: pos(3), velo(3), weight
INTEGER :: newID
CALL CreateParticle(product,pos,globalCell,globalCell,velo,0.,0.,0.,NewPartID=newID,NewMPF=weight)
PEM%pNext(PEM%pEnd(cell)) = newID
PEM%pNext(newID) = 0
PEM%pEnd(cell) = newID
PEM%pNumber(cell) = PEM%pNumber(cell)+1
END SUBROUTINE emit

END SUBROUTINE JiaCellReactions


REAL FUNCTION JiaStepIonization(energy,threshold,coefficient,power)
! The Maxwellian average of this sigma(E)*v reproduces
! coefficient*T**power*exp(-threshold/T) with E and T both in eV.
IMPLICIT NONE
REAL, INTENT(IN) :: energy,threshold,coefficient,power
JiaStepIonization = 0.
IF (energy.GT.threshold) THEN
  JiaStepIonization = coefficient*(energy-threshold)**(power+0.5) / &
                      (SQRT(energy)*(2./SQRT(ACOS(-1.)))*GAMMA(power+1.5))
END IF
END FUNCTION JiaStepIonization


SUBROUTINE JiaDirection(direction)
IMPLICIT NONE
REAL, INTENT(OUT) :: direction(3)
REAL :: u(2), angle, z
CALL RANDOM_NUMBER(u)
z = 2.*u(1)-1.
angle = 2.*ACOS(-1.)*u(2)
direction = [SQRT(1.-z*z)*COS(angle),SQRT(1.-z*z)*SIN(angle),z]
END SUBROUTINE JiaDirection


SUBROUTINE WriteJiaReactionCounts()
USE MOD_DSMC_BGGas, ONLY: UseJiaChemistry
USE MOD_TimeDisc_Vars, ONLY: time, dt, tAnalyze
#if USE_MPI
USE MOD_Globals, ONLY: myRank
#endif
IMPLICIT NONE
INTEGER :: out, rank
REAL :: sampleTime
REAL, SAVE :: previous = -1.
CHARACTER(32) :: filename
IF (.NOT.UseJiaChemistry) RETURN
sampleTime = time+dt
IF (sampleTime+0.01*dt.LT.tAnalyze.OR.sampleTime.LE.previous+0.01*dt) RETURN
previous = sampleTime
rank = 0
#if USE_MPI
rank = myRank
#endif
WRITE(filename,'(A,I0,A)') 'JiaReactionCounts_rank',rank,'.csv'
OPEN(NEWUNIT=out,FILE=TRIM(filename),STATUS='UNKNOWN',POSITION='APPEND',ACTION='WRITE')
WRITE(out,'(ES24.16,24(A,ES24.16))') sampleTime,(',',JiaReactionCounts(rank),rank=1,23),',',JiaMaxHazard
CLOSE(out)
END SUBROUTINE WriteJiaReactionCounts
