# 常压氦气石英管针—针放电

[启动 VS Code 工作台](Open-in-VSCode.cmd) · [在已打开的 VS Code 中打开工作台](PICLas.piclas-workbench)

Jia 初始状态算例采用内径 100 μm、钨针圆头 R2 μm、针距 1 mm、Jia 六物种及 +1500 V 的 2/5/2 ns 正脉冲。另有 10 μm 和 50 μm 两组 +10 kV 算例。工作台点「刷新」，在「正式结果」选择对应运行。选择「电子密度 (m⁻³)」后，可拖动时间轴、播放，或在右侧设定对数色标范围。VTU 转换完成后，可用「ParaView 结果」打开时间序列。

| 要找的内容 | 位置 |
| --- | --- |
| 当前 Jia 初始状态 | [模型设置](cases/He_W_D100um_TaperR2um_Jia_InitialState/MODEL_SETTINGS.md) · [历史 Jia2023 脉冲](cases/He_W_D100um_TaperR2um_Jia2023/runs/20261112-094232-research-9ZQunK/) |
| 23 条反应及 R15 | [反应清单](cases/He_W_D100um_TaperR2um_Jia2023/CHEMISTRY_PLAN.json) · [R15 文献核查](cases/He_W_D100um_TaperR2um_Jia2023/R15_SOURCE_REVIEW.md) · [短算自检](cases/He_W_D100um_TaperR2um_Jia2023/review-checks.json) |
| 10 μm、50 μm、100 μm 对照 | [二维算例与结果索引](cases/README.md) |
| 网格、石英壁与文献 | [文档索引](docs/README.md) |
| 短算和功能验证 | [verification](verification/) |
| 历史三维网格 | [archive/3d-meshes](archive/3d-meshes/) |
| 求解器补丁、网格脚本、工作台源码 | [solver](solver/) · [meshing](meshing/) · [vscode-extension](vscode-extension/) |

## 编译和文件说明

- 用启动器打开项目后，按 `Ctrl+Shift+B` 在 WSL 中编译 Jia 动态求解器。旧算例可以通过「运行生成任务」选择 `PICLas: Build helium pulse solver` 编译通用版。
- 在工作台选中 Jia 初始状态算例或从它另存的算例，点「编译求解器」调用同一个动态构建脚本。「6 ps 短验证」和「完整脉冲」启动前会核对源码和二进制的校验值。命令行 `Run-Jia-Pulse.ps1` 也默认使用 Jia 初始状态算例。[求解器设置](solver/jia_dynamic/README.md)
- 在「正式算例宏粒子权重」设置动态权重和各物种固定阈值。点「保存参数」会更新算例校验值，下次运行应用新参数。[算法调整说明](docs/算法调整说明.md) · [原始算法](docs/原始算法.md)
- 在工作台选中算例后，可检查二维几何、调整网格并另存为独立算例。运行最多使用六个 MPI 进程。
- 选中氦气算例或它的运行结果后，点「重命名算例」可修改显示名称。算例目录与运行快照保留原样。
- 「删除运行结果」可将所选的已停止、失败或验证运行移到 `.workbench-trash`，包括动态权重短测。「删除算例」可移走整个模型及其运行目录。正在运行的记录和标为关键的模型目录受保护，移走整个模型时会列出其中的正式结果数量。
- 算例的 `MODEL_SETTINGS.md` 记录当前设置。每次运行的 `runs/<运行编号>/MODEL_SETTINGS.md`、`parameter.ini` 和 `DSMC.ini` 保存当次设置。反应清单、边界、初始粒子和随机种子可以由这些快照追溯。
- 查看运行进度读 `solver.log`。电子密度与场量来自 `*_State_*.h5`。VTU 导出失败时仍可查看 HDF5，也可在工作台重试导出。工作台默认显示最近完成的正式结果。运行 `python analyze_full_pulse.py <运行目录>` 可生成 `pulse-summary.txt`、`pulse-diagnostics.csv` 和电子密度演化图。
