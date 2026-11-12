from pathlib import Path
import shutil
from tube_cases import replace_parameters
root=Path(__file__).resolve().parent
base=root/'cases/He_W_D50um_R2um_Gap1mm_Pos1500V_Seed1e16_SEE015_Refl020'
for name, reflection, ions, electrons, yield_ in [('electron_absorb_p0',0,0,128,0),('electron_reflect_p1',1,0,128,0),('ion_emit_gamma1',1,128,0,1)]:
    out=root/'verification'/name
    out.mkdir(parents=True,exist_ok=False)
    for file in ('parameter.ini','DSMC.ini','geometry.json','mesh-geometry.json','helium_mesh.h5'):
        shutil.copy2(base/file,out/file)
    values={'PulsePeak':'1.'}
    for b in (1,2):
        values[f'Part-Boundary{b}-SurfModElectronReflection']=str(reflection)
        values[f'Part-Boundary{b}-SurfModEmissionYield']=str(yield_)
    for sp,num in ((2,ions),(3,electrons)):
        k=f'Part-Species{sp}'
        values.update({f'{k}-nInits':'1' if num else '0',f'{k}-MacroParticleFactor':'1.',f'{k}-Init1-ParticleNumber':str(max(1,num)),f'{k}-Init1-BasePointIC':'(/0.000499999,0.,0./)',f'{k}-Init1-RadiusIC':'1.e-8',f'{k}-Init1-CylinderHeightIC':'1.e-10',f'{k}-Init1-velocityDistribution':'constant'})
    text=replace_parameters((out/'parameter.ini').read_text(),values)
    for sp in (2,3):
        text+=f'Part-Species{sp}-Init1-VeloIC = '+('1.e5' if sp==2 else '1.e7')+'\n'+f'Part-Species{sp}-Init1-VeloVecIC = (/1.,0.,0./)\n'
    (out/'parameter.ini').write_text(text)
