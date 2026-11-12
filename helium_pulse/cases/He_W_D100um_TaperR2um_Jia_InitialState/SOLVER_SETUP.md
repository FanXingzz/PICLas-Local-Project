# jia初始状态求解器

算例输入已建立，状态为待编译验证。工作台的「待审核模型」可以浏览几何和参数。此算例的正式运行需要独立求解器。

两根钨针与石英壁都使用表面模型 7。两根钨针的原子离子产额来自各自的 `SurfModEmissionYield=0.25`，分子离子产额来自 `Particles-He2-MetalYield=0.10`。石英壁的原子离子产额为 `Part-Boundary3-SurfModEmissionYield=0.02`，分子离子产额为 `Particles-He2-QuartzYield=0.02`。发射粒子为电子。

「初始粒子与界面发射」中的数值可以编辑并另存为独立算例。上面的数值是 `jia初始状态` 的默认值。带电粒子的初始密度采用 Jia 第 2 节，原始配置全域初始正负电荷相等。电子初温沿用项目的 1 eV，重粒子初温为 298 K。石英发射电子沿用 0–4 eV 均匀能谱。 [Jia 等，第 2 节](https://doi.org/10.1088/1361-6463/ac9eca)

[求解器源码补丁](solver-source.patch)固定到 PICLas 4.3.0 的提交 `514af4c6e5ec2a16f75db99295b34b08dfeced90`。补丁包含原六物种算例的气相反应实现，并按金属或介质边界读取各自的分子离子产额。石英二次电子从已知碰撞面进入轴对称轨迹追踪。原生介质充电同时记入吸收的入射粒子和发射电子的反号电荷。

如需编译，在 WSL 中执行本目录的 `bash build_solver.sh`。编译产物位于 `/home/fanxing/piclas_projects/helium_jia_initial_state_workspace/build/bin/piclas`，与正式算例当前使用的二进制分别存放。工作台现有运行入口仍使用项目求解器。新算例首次运行前应验证三处离子发射采样、石英电荷收支以及低权重的初始粒子数。
