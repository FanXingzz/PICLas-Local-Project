# 常压氦气石英管针—针放电

[启动 VS Code 工作台](Open-in-VSCode.cmd) · [在已打开的 VS Code 中打开工作台](PICLas.piclas-workbench)

当前算例为内径 100 μm、钨针圆头 R2 μm、针距 1 mm、Jia 六物种，使用 +1500 V 的 2/5/2 ns 正脉冲。工作台点「刷新」，在「正式结果」选择对应运行。选择「电子密度 (m⁻³)」后，可拖动时间轴、播放，或在右侧设定对数色标范围。VTU 转换完成后，可用「ParaView 结果」打开时间序列。

| 要找的内容 | 位置 |
| --- | --- |
| 当前模型与完整脉冲 | [模型设置](cases/He_W_D100um_TaperR2um_Jia2023/MODEL_SETTINGS.md) · [本次运行目录](cases/He_W_D100um_TaperR2um_Jia2023/runs/20261112-094232-research-9ZQunK/) |
| 23 条反应及 R15 | [反应清单](cases/He_W_D100um_TaperR2um_Jia2023/CHEMISTRY_PLAN.json) · [R15 文献核查](cases/He_W_D100um_TaperR2um_Jia2023/R15_SOURCE_REVIEW.md) · [短算自检](cases/He_W_D100um_TaperR2um_Jia2023/review-checks.json) |
| 50 μm、100 μm 对照 | [二维算例与结果索引](cases/README.md) |
| 网格、石英壁与文献 | [文档索引](docs/README.md) |
| 短算和功能验证 | [verification](verification/) |
| 历史三维网格 | [archive/3d-meshes](archive/3d-meshes/) |
| 求解器补丁、网格脚本、工作台源码 | [solver](solver/) · [meshing](meshing/) · [vscode-extension](vscode-extension/) |

## 编译和文件说明

- 用启动器打开项目后，按 `Ctrl+Shift+B` 编译。VS Code 调用 [build_solver.sh](build_solver.sh) 在 WSL 中编译 PICLas。
- 在工作台选中算例后，可检查二维几何、调整网格并另存为独立算例。运行最多使用六个 MPI 进程。
- 在工作台选中氦气模型或该模型的一帧结果后，点「删除算例」可将模型及其运行目录移到项目的 `.workbench-trash`。验证结果可用「删除验证」移走。正在运行的算例和标记为关键的算例受保护。已有正式结果会在确认框中列明。
- 算例的 `MODEL_SETTINGS.md` 记录当前设置。每次运行的 `runs/<运行编号>/MODEL_SETTINGS.md`、`parameter.ini` 和 `DSMC.ini` 保存当次设置。反应清单、边界、初始粒子和随机种子可以由这些快照追溯。
- 查看运行进度读 `solver.log`。电子密度与场量来自 `*_State_*.h5`；`*.vtu` 用于 ParaView。正式结果分析生成 `pulse-summary.txt`、`pulse-diagnostics.csv` 和电子密度演化图。
