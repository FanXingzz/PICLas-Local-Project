# 模型设置

**Archive3D_D50um_R2um_Plates_Swept_Medium**

目录 `Archive3D_D50um_R2um_Plates_Swept_Medium`。

## 几何、网格与驱动

- 网格方法 `swept`，结构 `见几何输入`。
- 石英管内径 50 μm。
- 石英管外径 150 μm。
- 针尖半径 2 μm。
- 针尖间距 1000 μm。
- 轴向计算域长度 1300 μm。
- 网格 `helium_mesh.h5`，场求解多项式阶次 1。
- 粒子追踪 `triatracking`。
- 高压针峰值 +1500 V，上升 2 ns、平顶 5 ns、下降 2 ns。
- 求解终止时间 9 ns。
- 时间步 0.1 ps。
- 状态输出间隔 0.25 ns。
- 介质区编号 `(/2/)`，相对介电常数 `(/3.8/)`。

## 气相碰撞与反应

- `UseDSMC=T`，`CollisMode=3`，空碰撞开关 `T`。
- 碰撞截面库 `XSec_Database_He_Plasma.h5`。
- 电子能级库 `Electronic-State-Database.h5`。
- 反应 1（`XSec`） He + e⁻ → He⁺ + e⁻ + e⁻。

## 边界条件

- `BC_HV` · 指定脉冲电势，粒子边界 `open`。
- `BC_Ground` · 电势 0 V，粒子边界 `open`。
- `BC_Quartz` · 氦气—石英介质界面，粒子边界 `reflective`，吸收 He⁺、e⁻，动态壁面电荷沉积。
- `BC_Outer` · 零法向电场，粒子边界 `open`。

## 初始粒子

- He，1 个初始化区域，宏粒子权重 20。
  - 区域 1 `background`，数密度（m⁻³） `2.4627315e+25`，温度（K） `298`，速度分布 `maxwell_lpn`。
- He⁺，1 个初始化区域，宏粒子权重 4.8828125。
  - 区域 1 `cuboid`，宏粒子数 `80`，起点（m） `(/-0.00048,-6.25e-06,-6.25e-06/)`，块长（m） `1.25e-05`，温度（K） `298.`，速度分布 `maxwell_lpn`，底边向量 1（m） `(/0.,1.25e-05,0./)`，底边向量 2（m） `(/0.,0.,1.25e-05/)`，折合 390.625 个实际粒子。
- e⁻，1 个初始化区域，宏粒子权重 4.8828125。
  - 区域 1 `cuboid`，宏粒子数 `80`，起点（m） `(/-0.00048,-6.25e-06,-6.25e-06/)`，块长（m） `1.25e-05`，温度（K） `298.`，速度分布 `maxwell_lpn`，底边向量 1（m） `(/0.,1.25e-05,0./)`，底边向量 2（m） `(/0.,0.,1.25e-05/)`，折合 390.625 个实际粒子。
- 随机种子 1、2。

## 原始输入和复现记录

- [parameter.ini](parameter.ini)
- [DSMC.ini](DSMC.ini)
- [geometry.json](geometry.json)
- [mesh.ini](mesh.ini)
- [case-info.json](case-info.json)
