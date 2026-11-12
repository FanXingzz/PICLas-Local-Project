# 模型设置

**streamer_N2**

目录 `pic-mcc`。

## 几何、网格与驱动

- 网格 `./streamer_mesh.h5`，1500 个单元，场求解多项式阶次 2。
- 粒子追踪 `triatracking`。
- 求解终止时间 0.7 ns。
- 时间步 0.1 ps。
- 状态输出间隔 0.05 ns。

## 气相碰撞与反应

- `UseDSMC=T`，`CollisMode=3`，空碰撞开关 `T`。
- 碰撞截面库 `XSec_Database_N2_Ionized.h5`。
- 电子能级库 `DSMCSpecies_electronic_state_full_Data.h5`。
- 反应 1（`XSec`） N₂ + e⁻ → N₂⁺ + e⁻ + e⁻。

求解日志记录的截面通道

- `N2-electron: Found EFFECTIVE collision cross section.`

## 边界条件

- `BC_Xleft` · 场边界类型 `(/12,0/)`，粒子边界 `symmetric`。
- `BC_Xright` · 场边界类型 `(/4,0/)`，粒子边界 `symmetric`。
- `BC_periodicy+` · 粒子边界 `periodic`。
- `BC_periodicy-` · 粒子边界 `periodic`。
- `BC_periodicz+` · 粒子边界 `periodic`。
- `BC_periodicz-` · 粒子边界 `periodic`。

## 初始粒子

- N₂，1 个初始化区域，宏粒子权重 200。
  - 区域 1 `background`，数密度（m⁻³） `2.506e25`，温度（K） `298.`，速度分布 `maxwell_lpn`。
- N₂⁺，1 个初始化区域，宏粒子权重 200。
  - 区域 1 `cuboid`，宏粒子数 `1000`，起点（m） `(/0.000775 , 0. , 0./)`，块长（m） `0.00005`，温度（K） `298.`，速度分布 `maxwell_lpn`，底边向量 1（m） `(/0, 0.00005 , 0./)`，底边向量 2（m） `(/0, 0. , 0.00005/)`，折合 200000 个实际粒子。
- e⁻，1 个初始化区域，宏粒子权重 200。
  - 区域 1 `cuboid`，宏粒子数 `1000`，起点（m） `(/0.000775 , 0. , 0./)`，块长（m） `0.00005`，温度（K） `298`，速度分布 `maxwell_lpn`，底边向量 1（m） `(/0, 0.00005 , 0./)`，底边向量 2（m） `(/0, 0. , 0.00005/)`，折合 200000 个实际粒子。
- 随机种子 1、2。

## 原始输入和复现记录

- [parameter.ini](parameter.ini)
- [DSMC.ini](DSMC.ini)
- [hopr.ini](hopr.ini)
- [piclas_run_corrected.log](piclas_run_corrected.log)
