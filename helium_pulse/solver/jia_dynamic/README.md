# Jia 动态负载均衡与宏粒子权重求解器

工作台的「完整脉冲」和「6 ps 短验证」为 `solver_profile=jia_initial_state` 的模型选择此求解器，包括 +1500 V 的 Jia 初态算例和从它另存的 +6000 V 算例。运行中 MPI 进程数固定为工作台所选的 1–6 个。多进程使用按实测单元耗时再分区，HDF5 路径转移网格、粒子与石英壁电荷。默认采样 100 步，偏差阈值 10%，全程最多 64 次再分区。

动态权重每 50 步更新，采用指数 0.5，同单元同物种每组至少保留 16 个宏粒子。目标权重以各物种冻结的初始权重与数量为参考，同时限制在参考权重及当前物种平均权重的 2 倍以内。初始未插入某物种时，以该物种的名义种子数和权重作为参考。电子保护区从针尖向针间延伸 25 μm，并按实际半针距限幅。能量达到 19.82 eV 的电子也沿用原固定合并策略。

在工作台选中模型后，打开「正式算例宏粒子权重」编辑该算例的权重设置和各物种固定阈值，再点「保存参数」。工作台会一起更新模型设置和参数校验值。`run_case.sh` 在新运行快照中应用保存的设置，并按半针距限制实际保护宽度。`AdaptiveVMPF.csv` 记录每次更新的目标权重和额外合并数，`ElemTimeStatistics.csv` 记录实际再分区次数。单进程运行启用动态权重，静电场检查沿用固定设置。工作台「动态权重短测」用于独立的检查点对照。

在 VS Code 按 `Ctrl+Shift+B`，或在工作台选中 Jia 算例后点「编译求解器」，都会调用 `bash build_solver.sh`。默认编译目录为 `~/piclas_projects/helium_jia_dynamic_workspace`，可用 `PICLAS_JIA_DYNAMIC_SOLVER_ROOT` 更改。构建输入变更时会重新应用补丁，启动前核对输入、源码和二进制。每次运行的 `solver-build-inputs.txt` 与 `solver-sha256.txt` 记录当次求解器版本。`bash validate.sh --cold-only` 可重复 6 ps 冷启动检查。提供高密度检查点及配套输入后，`bash validate.sh` 还能执行 25 ps 续算。检查点位置可用 `PICLAS_JIA_VALIDATION_REFERENCE` 指定。
