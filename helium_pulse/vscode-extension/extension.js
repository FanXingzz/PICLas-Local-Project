const vscode = require('vscode');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const readline = require('node:readline');

const viewType = 'piclas.workbench';
const marker = 'PICLas.piclas-workbench';

class WorkbenchBridge {
    constructor(root) {
        this.pending = new Map();
        this.nextId = 0;
        const bundledPython = path.join(root, '..', '.venv', 'Scripts', 'python.exe');
        const python = process.env.PICLAS_PYTHON || (fs.existsSync(bundledPython) ? bundledPython : 'python');
        this.process = spawn(python, ['-X', 'utf8', path.join(root, 'vscode_workbench.py')], {
            cwd: root, windowsHide: true
        });
        let stderr = '';
        this.process.stderr.on('data', data => { stderr = (stderr + data.toString()).slice(-3000); });
        this.process.stdin.on('error', error => this.fail(error));
        this.process.on('error', error => this.fail(error));
        this.process.on('exit', code => this.fail(new Error(stderr || `工作台数据服务已退出（${code}）。`)));
        readline.createInterface({ input: this.process.stdout }).on('line', line => {
            try {
                const message = JSON.parse(line);
                const job = this.pending.get(message.id);
                if (!job) return;
                this.pending.delete(message.id);
                if (message.error) job.reject(new Error(message.error));
                else job.resolve(message.result);
            } catch (error) {
                this.fail(error);
            }
        });
    }

    fail(error) {
        this.error = error;
        for (const job of this.pending.values()) job.reject(error);
        this.pending.clear();
    }

    call(method, args = {}) {
        if (this.error) return Promise.reject(this.error);
        const id = ++this.nextId;
        return new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject });
            this.process.stdin.write(JSON.stringify({ id, method, args }) + '\n');
        });
    }

    dispose() {
        this.process.kill();
    }
}

function pathFor(root, key) {
    if (key === 'nitrogen') return path.join(root, '..', 'official_streamer', 'pic-mcc');
    if (typeof key !== 'string') throw new Error('请选择一个算例。');
    const result = path.resolve(root, key);
    const relative = path.relative(root, result);
    if (relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
        throw new Error('请选择项目内的算例。');
    }
    return result;
}

function moveToProjectTrash(root, key) {
    const project = fs.realpathSync(root);
    const target = pathFor(project, key);
    if (path.relative(target, fs.realpathSync(target)) !== '') {
        throw new Error('该目录指向其他位置，无法移走。');
    }
    const trash = path.join(project, '.workbench-trash');
    fs.mkdirSync(trash, { recursive: true });
    if (path.relative(trash, fs.realpathSync(trash)) !== '') {
        throw new Error('项目回收站指向其他位置。');
    }
    const slot = fs.mkdtempSync(path.join(trash, 'item-'));
    const destination = path.join(slot, path.basename(target));
    try {
        fs.renameSync(target, destination);
    } catch (error) {
        try { fs.rmdirSync(slot); } catch { /* Retain a slot another process has used. */ }
        throw new Error(`无法将目录移到项目回收站（${error.code || error.message}）。`);
    }
    return path.relative(project, destination);
}

function htmlFor(webview, extension) {
    const asset = name => webview.asWebviewUri(vscode.Uri.joinPath(extension, 'media', name)).toString();
    const template = fs.readFileSync(path.join(extension.fsPath, 'media', 'index.html'), 'utf8');
    return template.replaceAll('__CSP__', webview.cspSource)
        .replace('__CSS__', asset('workbench.css'))
        .replace('__JS__', asset('workbench.js'));
}

function activate(context) {
    let activeTask = null;
    const diagnostics = vscode.window.createOutputChannel('PICLas 工作台', { log: true });
    context.subscriptions.push(diagnostics);
    context.subscriptions.push(vscode.tasks.onDidEndTaskProcess(({ execution }) => {
        if (execution.task.definition.type === 'piclas-workbench' &&
            execution.task.definition.run === activeTask?.id) activeTask = null;
    }));
    context.subscriptions.push(vscode.window.registerCustomEditorProvider(viewType, {
        openCustomDocument(uri) {
            return { uri, dispose() {} };
        },
        resolveCustomEditor(document, panel) {
            const root = path.dirname(document.uri.fsPath);
            if (!fs.existsSync(path.join(root, 'vscode_workbench.py'))) {
                throw new Error('请打开项目 helium_pulse 文件夹中的 PICLas.piclas-workbench。');
            }
            const bridge = new WorkbenchBridge(root);
            panel.title = 'PICLas 工作台';
            panel.webview.options = { enableScripts: true, localResourceRoots: [
                vscode.Uri.joinPath(context.extensionUri, 'media')
            ] };
            const methods = new Set(['catalog', 'describe', 'render', 'clone', 'paraview', 'selfCheck', 'runProgress',
                'adaptiveWeightSettings', 'saveAdaptiveWeight']);
            let disposed = false;
            const tell = message => { if (!disposed) panel.webview.postMessage(message); };
            const taskDone = vscode.tasks.onDidEndTaskProcess(event => {
                if (event.execution.task.definition.type !== 'piclas-workbench') return;
                const definition = event.execution.task.definition;
                tell({ event: 'taskDone', code: event.exitCode, case: definition.case, job: definition.job });
            });
            const listener = panel.webview.onDidReceiveMessage(async request => {
                if (request.event === 'firstPlotLoaded') {
                    diagnostics.info('工作台首帧已显示。');
                    return;
                }
                const { id, method, args = {} } = request;
                try {
                    let result;
                    if (method === 'catalog') {
                        result = { ...(await bridge.call(method)), taskRunning: activeTask !== null };
                    } else if (method === 'saveParameters') {
                        if (activeTask?.caseId === args.key) throw new Error('此算例有任务正在运行。');
                        result = await bridge.call(method, args);
                    } else if (method === 'renameCase') {
                        const model = (await bridge.call('catalog')).models.find(item => item.id === args.key);
                        if (!model) throw new Error('请选择一个二维氦气算例。');
                        const name = await vscode.window.showInputBox({
                            title: '重命名算例',
                            prompt: '输入在工作台中显示的名称',
                            value: model.name,
                            validateInput: value => {
                                const length = Array.from(value.trim()).length;
                                return length && length <= 100 ? undefined : '请输入 1 至 100 个字符。';
                            }
                        });
                        if (name !== undefined) result = await bridge.call(method, { key: model.id, name });
                    } else if (methods.has(method)) {
                        result = await bridge.call(method, args);
                    } else if (method === 'delete' || method === 'deleteCase') {
                        const isCase = method === 'deleteCase';
                        const group = isCase ? 'models' : 'runs';
                        const findItem = async () => {
                            const items = (await bridge.call('catalog'))[group];
                            const item = items.find(entry => entry.id === args.key);
                            const keyPattern = isCase ? /^cases\/[^/]+$/ : item?.adaptive
                                ? /^verification\/[^/]+\/runs\/[^/]+$/ : /^cases\/[^/]+\/runs\/[^/]+$/;
                            if (!item || !keyPattern.test(item.id)) {
                                throw new Error(isCase ? '请选择氦气算例。' : '请选择一项可移走的运行结果。');
                            }
                            const caseId = isCase ? item.id : item.case;
                            if (caseId && activeTask?.caseId === caseId) {
                                throw new Error('该算例有工作台任务正在运行，暂时不能删除。');
                            }
                            if (!item.deletable) {
                                throw new Error(item.deleteBlock || '此运行结果已保留。');
                            }
                            return item;
                        };
                        const item = await findItem();
                        const detail = isCase
                            ? `${item.label}\n${item.id}\n将同时移走模型输入、网格及 ${item.runCount} 个运行目录。` +
                                (item.formalRunCount ? `其中 ${item.formalRunCount} 个是已完成的正式结果。` : '')
                            : `${item.label}\n${item.id}`;
                        const confirm = await vscode.window.showWarningMessage(
                            `将所选${isCase ? '算例' : '运行结果'}移到项目回收站？`, { modal: true, detail }, '移到项目回收站');
                        if (confirm === '移到项目回收站') {
                            const current = await findItem();
                            result = moveToProjectTrash(root, current.id);
                            diagnostics.info(`已移走 ${current.id} → ${result}`);
                        }
                    } else if (method === 'exportPNG') {
                        const file = await vscode.window.showSaveDialog({
                            defaultUri: vscode.Uri.file(path.join(root, args.clean ? 'PICLas-clean.png' : 'PICLas-frame.png')),
                            filters: { PNG: ['png'] }
                        });
                        if (file) {
                            const png = await bridge.call('render', args);
                            await vscode.workspace.fs.writeFile(file, Buffer.from(png, 'base64'));
                            result = true;
                        }
                    } else if (method === 'open') {
                        if (!['MODEL_SETTINGS.md', 'REACTIONS.md', 'parameter.ini', 'DSMC.ini', 'geometry.json'].includes(args.file)) {
                            throw new Error('请选择工作台提供的输入文件。');
                        }
                        const uri = vscode.Uri.file(path.join(pathFor(root, args.key), args.file));
                        if (args.file.endsWith('.md')) {
                            await vscode.commands.executeCommand('markdown.showPreviewToSide', uri);
                        } else {
                            await vscode.window.showTextDocument(uri, { viewColumn: vscode.ViewColumn.Beside });
                        }
                    } else if (method === 'task') {
                        if (activeTask) throw new Error('已有一项工作台任务在运行。');
                        const jobs = {
                            solver: ['编译求解器', 'solver/jia_dynamic/build_solver.sh'],
                            mesh: ['生成网格', 'build_mesh.sh'],
                            run: ['完整脉冲', 'run_case.sh'],
                            pilot: ['6 ps 短验证', 'run_case.sh'],
                            export: ['导出 VTU', 'convert_results.sh'],
                            adaptive: ['动态权重短测', null]
                        };
                        const job = jobs[args.name];
                        if (!Array.isArray(job)) throw new Error('请选择工作台任务。');
                        let [label, script] = job;
                        if (args.name === 'solver') {
                            const { models, runs } = await bridge.call('catalog');
                            const key = runs.find(item => item.id === args.key)?.case || args.key;
                            const model = models.find(item => item.id === key);
                            script = model?.solverBuildScript || script;
                        }
                        if (args.name === 'adaptive') {
                            const adaptive = await bridge.call('adaptiveWeightSettings');
                            if (!adaptive.ready) throw new Error('动态权重求解器尚未编译。');
                            await bridge.call('saveAdaptiveWeight', { settings: args.adaptive });
                            if (activeTask) throw new Error('已有一项工作台任务在运行。');
                            script = adaptive.script;
                        }
                        const command = ['-d', 'Ubuntu-24.04', '--cd', root, '--', 'bash', script];
                        if (args.name === 'run' || args.name === 'pilot') {
                            if (!Number.isInteger(args.ranks) || args.ranks < 1 || args.ranks > 6) {
                                throw new Error('MPI 进程数须为 1 至 6。');
                            }
                            const checks = await bridge.call('selfCheck', { key: args.key });
                            if (checks.draft || (args.name === 'run' && checks.blocked)) {
                                throw new Error('该算例暂缓启动，请查看「模型自检」。');
                            }
                            if (activeTask) throw new Error('已有一项工作台任务在运行。');
                            command.push(String(args.ranks), args.name === 'run' ? 'research' : 'pilot');
                        }
                        if (!['solver', 'adaptive'].includes(args.name)) {
                            const key = path.relative(root, pathFor(root, args.key)).split(path.sep).join('/');
                            command.push(key);
                        }
                        const run = Date.now();
                        const task = new vscode.Task({ type: 'piclas-workbench', run, job: args.name,
                            case: ['run', 'pilot'].includes(args.name) ? args.key : null }, vscode.TaskScope.Workspace,
                            label, 'PICLas', new vscode.ProcessExecution('wsl.exe', command));
                        task.presentationOptions = { reveal: vscode.TaskRevealKind.Always, clear: true };
                        const caseId = ['solver', 'adaptive'].includes(args.name)
                            ? null : args.key.match(/^cases\/[^/]+/)?.[0];
                        if (activeTask) throw new Error('已有一项工作台任务在运行。');
                        activeTask = { id: run, caseId };
                        try {
                            await vscode.tasks.executeTask(task);
                        } catch (error) {
                            activeTask = null;
                            throw error;
                        }
                    } else {
                        throw new Error('工作台操作无效。');
                    }
                    tell({ id, result });
                } catch (error) {
                    if (method === 'delete' || method === 'deleteCase') diagnostics.warn(error.message);
                    tell({ id, error: error.message });
                }
            });
            panel.onDidDispose(() => {
                disposed = true;
                listener.dispose();
                taskDone.dispose();
                bridge.dispose();
            });
            panel.webview.html = htmlFor(panel.webview, context.extensionUri);
        }
    }, { webviewOptions: { retainContextWhenHidden: true } }));
    context.subscriptions.push(vscode.commands.registerCommand('piclas.openWorkbench', async () => {
        for (const folder of vscode.workspace.workspaceFolders || []) {
            for (const candidate of [path.join(folder.uri.fsPath, marker),
                                     path.join(folder.uri.fsPath, 'helium_pulse', marker)]) {
                if (fs.existsSync(candidate)) {
                    await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(candidate), viewType);
                    return;
                }
            }
        }
        vscode.window.showInformationMessage('请在 VS Code 中打开 PICLas_Local_Project 或 helium_pulse 文件夹。');
    }));
}

module.exports = { activate };
