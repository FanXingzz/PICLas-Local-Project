# 模型设置

**钨针｜100 μm｜石英吸收与充电｜细档加密**

目录 `He_W_D100um_R2um_Gap1mm_QuartzAbsorb_Fine`。

## 几何、网格与驱动

- 网格方法 `axisymmetric`，结构 `tube_only`。
- 石英管内径 100 μm。
- 石英管外径 200 μm。
- 针尖半径 2 μm。
- 针尖间距 1000 μm。
- 轴向计算域长度 1300 μm。
- 半球端面，直针杆直径 4 μm。
- 近壁气体与石英首层分别为 0.25、0.5 μm，针尖前方轴向细分 4 倍，直管段轴向最大尺寸 15 μm。
- 两针材料为钨，表面产额和反射概率采用有效参数。
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

- `BC_HV` · 指定脉冲电势，粒子边界 `reflective`，表面模型 7，离子诱导电子产额 0.15，电子镜面反射概率 0.2，发射能谱 uniform-energy，发射能量参数（eV） 4.。
- `BC_Ground` · 电势 0 V，粒子边界 `reflective`，表面模型 7，离子诱导电子产额 0.15，电子镜面反射概率 0.2，发射能谱 uniform-energy，发射能量参数（eV） 4.。
- `BC_Quartz` · 氦气—石英介质界面，粒子边界 `reflective`，吸收 He⁺、e⁻，动态壁面电荷沉积。
- `BC_Outer` · 零法向电场，粒子边界 `open`。
- `BC_Axis` · 轴对称，粒子边界 `symmetric_axis`。
- `BC_Sym` · 降维对称，粒子边界 `symmetric_dim`。

## 初始粒子

- He，1 个初始化区域，宏粒子权重 20。
  - 区域 1 `background`，数密度（m⁻³） `2.4627315e+25`，温度（K） `298`，速度分布 `maxwell_lpn`。
- He⁺，1 个初始化区域，宏粒子权重 37.511191526658。
  - 区域 1 `cylinder`，宏粒子数 `2048`，起点（m） `(/-0.000499,0.,0./)`，半径（m） `4.95e-05`，柱长（m） `0.000998`，温度（K） `298.`，速度分布 `maxwell_lpn`，折合 76822.92 个实际粒子。
- e⁻，1 个初始化区域，宏粒子权重 37.511191526658。
  - 区域 1 `cylinder`，宏粒子数 `2048`，起点（m） `(/-0.000499,0.,0./)`，半径（m） `4.95e-05`，柱长（m） `0.000998`，温度（K） `11604.51812`，速度分布 `maxwell_lpn`，折合 76822.92 个实际粒子。
- 记录的预电离密度 1e+16 m⁻³。
- 随机种子 1、2。

## 原始输入和复现记录

- [parameter.ini](parameter.ini)
- [DSMC.ini](DSMC.ini)
- [geometry.json](geometry.json)
- [mesh.ini](mesh.ini)
- [case-info.json](case-info.json)
