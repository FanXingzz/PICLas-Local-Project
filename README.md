# PICLas 等离子体仿真项目

这个项目保存了氮气负流注和常压氦气石英管内针—针脉冲放电的输入、网格、数据与 VS Code 工作台。氦气主算例为二维轴对称，石英管内径 100 μm，钨针间距 1 mm，针尖曲率半径 2 μm，正脉冲 +1500 V，上升、平顶、下降分别为 2、5、2 ns。

## 在另一台 Windows 电脑上打开

工作台 **1.5.7** 随当前仓库源码提供，包含参数保存、算例重命名和运行进度。已有 Git 检出可用 `git pull` 更新，再双击 [Open-PICLas.cmd](Open-PICLas.cmd) 安装仓库中的新版扩展。

1. 在 [迁移 Release](https://github.com/FanXingzz/PICLas-Local-Project/releases/tag/migration-2026-11-12) 下载迁移 ZIP 及 SHA-256 校验文件。该归档保留发布时的工作台版本、历史数据和通用预编译求解器。使用新版时，在新目录下载当前源码，将所需数据和 `runtime/` 复制到对应的相对路径。
2. 将 ZIP 完整解压到本地目录，例如 `D:\Simulation\PICLas-Local-Project`。可在 PowerShell 运行 `Get-FileHash .\PICLas-Local-Project-migration-2026-11-12.zip -Algorithm SHA256`，与校验文件中的值比较。
3. 安装 [Visual Studio Code](https://code.visualstudio.com/download) 和 [Python](https://www.python.org/downloads/windows/) 3.11 或更新版本，建议使用 3.12。使用自定义 VS Code 安装位置时，可把环境变量 `PICLAS_CODE_CLI` 指向安装目录中的 `bin\code.cmd`。
4. 双击 [Open-PICLas.cmd](Open-PICLas.cmd)。第一次打开会建立项目目录内的 `.venv`、联网安装 Python 绘图依赖，并安装包内的 PICLas 工作台扩展。VS Code 若询问是否信任此工作区，核对目录后选择信任。

已有 HDF5 的几何、电子密度、电势和电场可直接在 Windows 工作台查看。查看这些数据无需 WSL。ParaView 是可选工具，安装后可打开已有 VTU 的时间序列。若工作台找不到 ParaView，可将环境变量 `PICLAS_PARAVIEW` 指向实际的 `paraview.exe`，然后重新打开工作台。

## 工作台和研究数据

| 内容 | 位置 |
| --- | --- |
| 氦气算例和历史对照 | [算例索引](helium_pulse/cases/README.md) · [研究记录](helium_pulse/docs/研究记录.md) |
| 100 μm Jia 六物种算例 | [模型设置](helium_pulse/cases/He_W_D100um_TaperR2um_Jia2023/MODEL_SETTINGS.md) · [反应清单](helium_pulse/cases/He_W_D100um_TaperR2um_Jia2023/CHEMISTRY_PLAN.json) |
| 100 μm 运行快照 | [快照元数据](SNAPSHOT.json) · [运行目录](helium_pulse/cases/He_W_D100um_TaperR2um_Jia2023/runs/20261112-094232-research-9ZQunK/) |
| Jia 初始状态对照 | [模型设置](helium_pulse/cases/He_W_D100um_TaperR2um_Jia_InitialState/MODEL_SETTINGS.md) · [独立求解器说明](helium_pulse/cases/He_W_D100um_TaperR2um_Jia_InitialState/SOLVER_SETUP.md) |
| 原始氮气负流注 | [模型设置](official_streamer/pic-mcc/MODEL_SETTINGS.md) · [原始结果目录](official_streamer/pic-mcc/) |
| 网格和短验证 | [文档索引](helium_pulse/docs/README.md) · [验证目录](helium_pulse/verification/) |

在「正式结果」选一项运行，用时间轴播放。电子密度色标可设为对数和固定范围。HDF5 的 `/PartData` 存有宏粒子的坐标、速度、物种和权重，`/ElemData` 存有单元量。在「氦气算例」选择 `jia初始状态`，可以编辑脉冲、初始粒子和界面发射，再点击「保存参数」。几何或网格修改可另存为独立算例。选中算例或它的运行结果后可点击「重命名算例」，算例目录和历史结果保持原样。运行时工作台显示已算时间及预计剩余时间。删除操作把选中的数据移到 `helium_pulse/.workbench-trash`。

迁移时 100 μm 六物种正式计算尚在运行，本包以最近一帧已写完的 HDF5 为截点。对应逐步诊断保留到同一时刻，工作台标为「运行快照」。快照时刻和来源以 [SNAPSHOT.json](SNAPSHOT.json) 为准。已完成的历史结果随包保留。缓存、运行锁和已移入项目回收站的文件不纳入迁移包。

## 在另一台电脑运行或编译

### 使用随包求解器

预编译的 `piclas` 和 `piclas2vtk` 位于 `runtime/linux-x86_64`，针对 Ubuntu 24.04 x86-64。它们随包携带所需的 PETSc 等非系统动态库，仍依赖目标 Ubuntu 的 MPI、HDF5 和 BLAS 运行库。首次使用时，在 Windows 管理员 PowerShell 安装 [WSL](https://learn.microsoft.com/windows/wsl/install)，再在 Ubuntu 24.04 终端进入解压目录。

```bash
bash Setup-WSL.sh
cd helium_pulse
bash run_case.sh 6 pilot ./cases/He_W_D100um_TaperR2um_Jia2023
bash run_case.sh 6 research ./cases/He_W_D100um_TaperR2um_Jia2023
```

先完成 6 ps 短验证，再启动完整脉冲。每次运行写入新的 `runs/` 目录，脚本限制 MPI 进程为 1–6，并以单线程方式调用 BLAS。更换电脑后若预编译版本报告非法指令，需在目标机器上重编译。查看已有数据不受此限制。

工作台的「生成网格」需要单独安装 PyHOPE 等依赖。执行 `bash Setup-WSL.sh --mesh`，再在工作台把模型另存并生成网格。

### 从源码重编译

PICLas 源码版本为 4.3.0 的 `514af4c6e5ec2a16f75db99295b34b08dfeced90`。在 Ubuntu 24.04 安装 Git、CMake、Ninja、GNU Fortran/C++ 和 OpenMPI 开发包，并准备启用 MPI、HYPRE 与 MUMPS 的 PETSc。以下命令从项目根目录运行。

```bash
sudo apt-get install -y git cmake ninja-build gfortran g++ libopenmpi-dev libopenblas-dev
git clone https://github.com/piclas-framework/piclas.git "$HOME/piclas"
export PICLAS_UPSTREAM="$HOME/piclas"
export PETSC_DIR=/path/to/petsc/install
bash helium_pulse/build_solver.sh
```

编译脚本在独立工作目录应用项目补丁。可以用 `PICLAS_SOLVER_ROOT` 指定该工作目录，用 `PICLAS_VTK_BIN` 指定自行编译的转换器。随包运行工具的上游源码和项目补丁可分别从 [PICLas 对应提交](https://github.com/piclas-framework/piclas/tree/514af4c6e5ec2a16f75db99295b34b08dfeced90) 和 `runtime/linux-x86_64/solver-source.patch` 取得。

`jia初始状态` 已完成初态、界面发射与石英充电的 6 ps 验证。运行此算例需要先在 WSL 中编译 Jia 独立求解器，再点击「完整脉冲」。可用 `PICLAS_JIA_INITIAL_SOLVER_ROOT` 指定独立构建目录。[编译与验证说明](helium_pulse/cases/He_W_D100um_TaperR2um_Jia_InitialState/SOLVER_SETUP.md)

## 定位运行问题

- 工作台仍显示旧版本时，关闭旧的扩展开发窗口，用根目录启动脚本重新打开。
- Python 依赖安装失败时，在项目根目录执行 `.\.venv\Scripts\python.exe -m pip install -r requirements-viewer.txt`。
- VTU 按钮不可用时，先确认运行目录存在 VTU。也可在 WSL 中执行 `bash helium_pulse/convert_results.sh /path/to/run` 从 HDF5 生成。
- 查求解进度读本次运行的 `solver.log` 和 `run-status.txt`。`pulse-summary.json` 是生成时的分析快照，以它自己的结束时间为准。
- 每次运行的 `MODEL_SETTINGS.md`、`parameter.ini`、`DSMC.ini`、`input-sha256.txt` 和求解器补丁共同记录可复现的设置。
