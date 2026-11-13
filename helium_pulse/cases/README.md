# 二维氦气算例索引

## 当前六物种算例

- [100 μm · +1500 V · Jia 初始状态](He_W_D100um_TaperR2um_Jia_InitialState/)
- [10 μm · +10 kV · R200 nm](He_Tube2D_D10um_R200nm_Gap1mm_Custom_TaperS1um/) · [50 μm · +10 kV · R1 μm](He_Tube2D_D50um_R1um_Gap1mm_Custom_TaperS5um/)
- [100 μm · 钨针 R2 μm · Jia 六物种](He_W_D100um_TaperR2um_Jia2023/)
- [正式脉冲设置](He_W_D100um_TaperR2um_Jia2023/runs/20261112-094232-research-9ZQunK/MODEL_SETTINGS.md) · [运行日志](He_W_D100um_TaperR2um_Jia2023/runs/20261112-094232-research-9ZQunK/solver.log)

## 已完成的完整正脉冲

| 管径 | 对照条件 | 结果 |
| --- | --- | --- |
| 100 μm | 钨针，石英吸收并充电 | [运行目录](He_W_D100um_R2um_Gap1mm_Pos1500V_Seed1e16_QuartzAbsorb/runs/20261111-125011-research-QZ3sBc/) |
| 100 μm | 钨针，石英电子总返回 | [运行目录](He_W_D100um_R2um_Gap1mm_Pos1500V_Seed1e16_QuartzDunaevsky/runs/20261111-131339-research-RoDHIz/) |
| 50 μm | 钨针，石英吸收，全气隙种子 | [运行目录](He_W_D50um_R2um_Gap1mm_Pos1500V_Seed1e16_SEE015_Refl020/runs/20261111-114633-research-l6wfPv/) |
| 50 μm | 钨针，石英电子总返回 | [运行目录](He_W_D50um_R2um_Gap1mm_Pos1500V_Seed1e16_QuartzDunaevsky/runs/20261111-133302-research-ASMuCi/) |
| 50 μm | 正针局部种子、无电极发射 | [运行目录](He_D50um_R2um_Gap1mm_Pos1500V_AnodeSeed_NoEmission/runs/20261111-111250-research-3FAKbK/) |

## 网格与化学对照

- 50 μm 针尖和近壁网格：[中档](He_W_D50um_R2um_Gap1mm_QuartzAbsorb_Medium/) · [细档](He_W_D50um_R2um_Gap1mm_QuartzAbsorb_Fine/) · [针尖再加密](He_W_D50um_R2um_Gap1mm_QuartzAbsorb_TipFine/) · [锥形圆头](He_W_D50um_TaperedR2um_Shaft10um_Gap1mm_QuartzAbsorb/)
- 100 μm 针尖和近壁网格：[中档](He_W_D100um_R2um_Gap1mm_QuartzAbsorb_Medium/) · [细档](He_W_D100um_R2um_Gap1mm_QuartzAbsorb_Fine/) · [针尖再加密](He_W_D100um_R2um_Gap1mm_QuartzAbsorb_TipFine/) · [锥形圆头](He_W_D100um_TaperedR2um_Shaft10um_Gap1mm_QuartzAbsorb/)
- [二维网格采样数据](axisymmetric_d50_d100_refinement.csv) · [历史三维网格](../archive/3d-meshes/)
