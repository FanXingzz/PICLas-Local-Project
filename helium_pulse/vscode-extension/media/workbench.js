const vscode = acquireVsCodeApi();
const element = id => document.getElementById(id);
const dataset = element('dataset');
const field = element('field');
const time = element('time');
const plot = element('plot');
const message = element('plot-message');
const requests = new Map();
const cache = new Map();
const palettes = vscode.getState()?.palettes || {};
const defaultColors = {
    E: { scale: 'log', manual: false, low: 1e4, high: 1e7 },
    ElectronDensityCell: { scale: 'auto', manual: false, low: 1e14, high: 1e18 },
    Phi: { scale: 'linear', manual: false, low: 0, high: 1500 }
};
let nextRequest = 0;
let catalog;
let selection;
let detail;
let dirty = false;
let playing = false;
let playVersion = 0;
let renderVersion = 0;
let queuedFrame;
let drawing = false;
let taskRunning = false;
let savingModel = false;
let renamingCase = false;
let editRevision = 0;
let checks;
let progressRun;
let adaptiveReady = false;

function status(text, error = false) {
    element('status').textContent = text;
    element('status').classList.toggle('error', error);
}

function request(method, args = {}) {
    const id = ++nextRequest;
    return new Promise((resolve, reject) => {
        requests.set(id, { resolve, reject });
        vscode.postMessage({ id, method, args });
    });
}

function durationText(seconds) {
    if (seconds === null) return '—';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor(seconds / 60) % 60;
    return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分 ${seconds % 60} 秒`;
}

async function pollProgress() {
    const section = element('run-progress');
    try {
        const progress = await request('runProgress', { key: progressRun });
        section.hidden = !progress;
        if (!progress) return;
        progressRun = progress.id;
        const labels = { running: '求解中', saving: '正在保存结果', complete: '已完成',
            stopped: '已停止', failed: '运行失败' };
        const formatNs = value => Number(value.toPrecision(6));
        element('run-progress-case').textContent = progress.label;
        element('run-progress-state').textContent = progress.conversionStatus === 'running' ? '正在导出 VTU'
            : progress.state === 'complete' && progress.conversionStatus === 'failed' ? '求解完成，VTU 导出失败'
            : labels[progress.state];
        element('run-progress-time').textContent = progress.endNs === null ? `${formatNs(progress.currentNs)} ns`
            : `${formatNs(progress.currentNs)} / ${formatNs(progress.endNs)} ns`;
        const bar = element('run-progress-bar');
        if (progress.percent === null) bar.removeAttribute('value');
        else bar.value = progress.percent;
        element('run-progress-percent').textContent = progress.percent === null ? '—' : `${progress.percent.toFixed(2)}%`;
        element('run-progress-eta').textContent = `预计剩余 ${durationText(progress.etaSeconds)}`;
    } catch {
        if (!section.hidden) element('run-progress-state').textContent = '等待读取进度';
    } finally {
        window.setTimeout(pollProgress, 3000);
    }
}

function safe(action) {
    return async (...args) => {
        try { await action(...args); }
        catch (error) { status(error.message, true); }
    };
}

function options(select, choices) {
    select.replaceChildren(...choices.map(([value, label]) => new Option(label, value)));
}

function form(id, items, values, readOnly, onInput = markDirty) {
    const holder = element(id);
    holder.replaceChildren();
    for (const item of items) {
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'number';
        input.step = item.integer ? '1' : 'any';
        if (item.min !== undefined) input.min = item.min;
        if (item.max !== undefined) input.max = item.max;
        if (item.help) {
            input.title = item.help;
            input.setAttribute('aria-description', item.help);
        }
        input.value = values[item.id] ?? '';
        input.dataset.key = item.id;
        input.readOnly = readOnly;
        input.addEventListener('input', onInput);
        label.append(item.label, input);
        holder.append(label);
    }
}

function fields(id) {
    return Object.fromEntries(Array.from(element(id).querySelectorAll('input'), input =>
        [input.dataset.key, input.value === '' ? null : Number(input.value)]));
}

function setFields(id, values) {
    for (const input of element(id).querySelectorAll('input')) {
        if (input.dataset.key in values) input.value = values[input.dataset.key];
    }
}

function draft() {
    return { geometry: { ...fields('geometry'), ...fields('taper'), needle_shape: element('needle-shape').value },
        mesh: fields('mesh') };
}

function modelSelected() {
    return catalog?.models.find(model => model.id === selection?.id);
}

function caseSelected() {
    return catalog?.models.find(model => model.id === (selection?.case || selection?.id));
}

function saveView() {
    vscode.setState({ selection: selection?.id, palettes, focus: element('focus').value });
}

function loadColors() {
    const palette = palettes[field.value] || defaultColors[field.value];
    element('color-heading').textContent = ({
        ElectronDensityCell: '电子密度色标 (m⁻³)', E: '电场色标 (V/m)', Phi: '电势色标 (V)'
    })[field.value] || '色标';
    element('color-scale').disabled = !palette;
    element('manual-color').disabled = !palette;
    element('apply-color').disabled = !palette;
    if (palette) {
        element('color-scale').value = palette.scale;
        element('manual-color').checked = palette.manual;
        element('color-low').value = palette.low;
        element('color-high').value = palette.high;
    }
    for (const name of ['color-low', 'color-high']) element(name).disabled = !palette?.manual;
}

function applyColors() {
    if (!field.value) return;
    const scale = element('color-scale').value;
    const manual = element('manual-color').checked;
    const low = element('color-low').valueAsNumber;
    const high = element('color-high').valueAsNumber;
    const log = scale === 'log' || (scale === 'auto' && field.value === 'ElectronDensityCell');
    if (manual && (!Number.isFinite(low) || !Number.isFinite(high) || high <= low || (log && low <= 0))) {
        throw new Error(log ? '对数范围要求 0 < 下限 < 上限。' : '请填写下限小于上限的有效范围。');
    }
    palettes[field.value] = { scale, manual, low, high };
    saveView();
    status(manual ? '当前场量的色标范围已固定，切换算例会沿用。' : '当前场量使用自动范围。');
    redraw();
}

function updateActions() {
    const model = modelSelected();
    const currentCase = caseSelected();
    element('geometry-section').hidden = !model;
    element('save-section').hidden = !model;
    element('save-parameters').hidden = !model?.canSaveParameters;
    element('save-parameters').disabled = savingModel || !dirty || !model?.canSaveParameters || model.running;
    element('clone').disabled = savingModel;
    element('pulse-section').hidden = !detail?.parameters.length;
    element('initial-section').hidden = !detail?.initialFields?.length;
    element('case-weight-section').hidden = !model?.canSaveParameters || !detail?.caseWeightFields?.length;
    element('select-model').hidden = !selection?.case || !catalog.models.some(m => m.id === selection.case);
    element('pv-result').disabled = !detail?.vtuAvailable || !field.value;
    element('pv-model').disabled = !detail?.modelAvailable;
    element('rename-case').hidden = !currentCase;
    element('rename-case').disabled = !currentCase || renamingCase;
    element('delete-result').hidden = Boolean(model);
    element('delete-result').disabled = Boolean(model) || !selection?.deletable;
    element('delete-result').title = selection?.deleteBlock || '将所选运行移到项目回收站';
    element('delete-case').hidden = !currentCase;
    element('delete-case').disabled = !currentCase;
    element('delete-case').title = currentCase?.deleteBlock || '将算例移到项目回收站';
    element('clean-plot').disabled = !detail?.frames.length || !field.value;
    element('export-png').disabled = !detail?.frames.length || !field.value;
    element('focus').disabled = !detail?.geometry;
    document.querySelector('[data-file="MODEL_SETTINGS.md"]').disabled = !detail?.settingsAvailable;
    document.querySelector('[data-file="REACTIONS.md"]').hidden = !detail?.reactionsAvailable;
    document.querySelector('[data-task="solver"]').disabled = taskRunning;
    document.querySelector('[data-task="mesh"]').disabled = taskRunning || dirty || !model || model.ready;
    for (const name of ['pilot', 'run']) {
        document.querySelector(`[data-task="${name}"]`).disabled =
            taskRunning || savingModel || dirty || !model?.ready || model.draft || (name === 'run' && model.review);
    }
    document.querySelector('[data-task="export"]').disabled =
        taskRunning || !selection?.case || !detail?.frames.length;
    updateAdaptiveActions();
}

function updateAdaptiveActions() {
    element('save-adaptive-weight').disabled = taskRunning;
    element('run-adaptive-weight').disabled = taskRunning || !adaptiveReady;
}

async function loadAdaptiveWeight() {
    const { fields: controls, mergeFields = [], ready } = await request('adaptiveWeightSettings');
    adaptiveReady = ready;
    element('adaptive-weight-section').hidden = !controls.length;
    form('adaptive-weight-fields', controls, Object.fromEntries(controls.map(item => [item.id, item.value])),
        false, () => {});
    form('adaptive-merge-fields', mergeFields, Object.fromEntries(mergeFields.map(item => [item.id, item.value])),
        false, () => {});
    updateAdaptiveActions();
}

function adaptiveSettings() {
    return { ...fields('adaptive-weight-fields'), ...fields('adaptive-merge-fields') };
}

function caseWeights() {
    if (modelSelected()?.canSaveParameters && detail?.caseWeightFields?.length) {
        return { ...fields('case-weight-fields'), ...fields('case-merge-fields') };
    }
}

function markDirty() {
    dirty = true;
    editRevision++;
    status(modelSelected()?.canSaveParameters ? '参数草稿已修改。可保存参数或另存为独立算例。'
        : '参数草稿已修改，可预览或另存为独立算例。');
    updateActions();
}

async function loadCatalog(preferred, { keepView = false } = {}) {
    catalog = await request('catalog');
    taskRunning = catalog.taskRunning;
    const keptSelection = !preferred && (dirty || keepView)
        ? [...catalog.models, ...catalog.runs].find(item => item.id === selection?.id) : null;
    const showValidation = element('show-validation').checked;
    const datasets = [
        ['正式结果', catalog.runs.filter(run => !run.validation && !run.adaptive)],
        ['待审核模型', catalog.models.filter(model => model.review)],
        ['氦气算例', catalog.models.filter(model => !model.review &&
            (!model.validation || showValidation || model.id === keptSelection?.id))]
    ];
    const adaptive = catalog.runs.filter(run => run.adaptive);
    if (adaptive.length) datasets.push(['动态权重短测', adaptive]);
    if (showValidation) datasets.push(['静电及短验证', catalog.runs.filter(run => run.validation)]);
    dataset.replaceChildren(...datasets.map(([title, items]) => {
        const group = document.createElement('optgroup');
        group.label = title;
        group.append(...items.map(item => new Option(item.label, item.id)));
        return group;
    }));
    if (keptSelection) {
        dataset.value = keptSelection.id;
        selection = keptSelection;
        updateActions();
        return;
    }
    options(element('diameter'), [['', '自定义'], ...Object.entries(catalog.diameters).map(([l, v]) => [v, l])]);
    options(element('preset'), [['', '自定义'], ...Object.keys(catalog.meshPresets).map(name => [name, name])]);
    const visible = new Set(Array.from(dataset.options, option => option.value));
    dataset.value = [preferred, selection?.id, vscode.getState()?.selection, catalog.latest, catalog.runs[0].id]
        .find(key => visible.has(key));
    await selectDataset();
}

async function selectDataset() {
    stop();
    dirty = false;
    cache.clear();
    const key = dataset.value;
    selection = [...catalog.runs, ...catalog.models].find(item => item.id === key);
    checks = undefined;
    element('self-check').open = false;
    ++renderVersion;
    plot.hidden = true;
    message.hidden = false;
    message.textContent = '正在读取算例…';
    const loaded = await request('describe', { key });
    if (dataset.value !== key) return;
    detail = loaded;
    const model = modelSelected();
    if (detail.frames.length && !field.value) field.value = 'ElectronDensityCell';
    if (!detail.frames.length) field.value = '';
    if (!detail.geometry) element('focus').value = 'full';
    loadColors();
    saveView();
    time.max = Math.max(0, detail.frames.length - 1);
    time.value = 0;
    time.disabled = detail.frames.length < 2;
    element('play').disabled = time.disabled;
    element('assessment').textContent = detail.invalid ? '此运行未通过粒子守恒检查' : detail.assessment;
    element('assessment').hidden = !element('assessment').textContent;
    form('pulse', detail.parameters, Object.fromEntries(detail.parameters.map(item => [item.id, item.value])), !model);
    form('initial', detail.initialFields, Object.fromEntries(detail.initialFields.map(item => [item.id, item.value])), !model);
    for (const [id, controls] of [['case-weight-fields', detail.caseWeightFields || []],
                                 ['case-merge-fields', detail.caseMergeFields || []]]) {
        form(id, controls, Object.fromEntries(controls.map(item => [item.id, item.value])), !model);
    }
    if (model) {
        form('geometry', detail.geometryFields, detail.geometry, false);
        form('taper', detail.taperFields, detail.taperControls, false);
        element('needle-shape').value = detail.taperControls.needle_shape;
        element('taper').hidden = element('needle-shape').value !== 'tapered';
        form('mesh', detail.meshFields, detail.meshControls, false);
        element('diameter').value = detail.geometry.tube_bore_um;
        const mesh = detail.meshControls;
        element('preset').value = Object.keys(catalog.meshPresets).find(name =>
            Object.entries(catalog.meshPresets[name]).every(([k, v]) => mesh[k] === v)) || '';
    }
    updateActions();
    status(model?.draft ? (detail.initialFields.length ? '可编辑并另存。此算例待独立求解器验证。' :
        '反应网络待接入，请查看「模型自检」。') : model?.review ? '待审核，可查看参数与短验证。' :
        (model ? (model.ready ? '网格就绪。' : '该算例等待生成网格。') : ''));
    await redraw();
}

function checkRow(name, detail) {
    const row = document.createElement('p');
    const label = document.createElement('strong');
    const value = document.createElement('span');
    label.textContent = name;
    value.textContent = detail;
    row.append(label, value);
    return row;
}

function filterChecks() {
    if (!checks) return;
    const query = element('reaction-filter').value.trim().toLowerCase();
    const list = element('check-reactions');
    const plan = checks.planned.map(({ id, equation, rate }) => ({
        name: `R${id} · ${equation}`,
        detail: [rate.coefficient, rate.unit, rate.note].filter(value => value != null && value !== '').join(' ')
    }));
    const wall = checks.plannedSurfaces;
    const plannedSurfaces = wall.reactions ? [
        ...wall.reactions.map(name => ({ name, detail: '中和或猝灭' })),
        { name: '论文阴极 He⁺ / He₂⁺ γ', detail: Object.values(wall.cathode_ion_yield).join(' / ') },
        { name: '论文陶瓷 He⁺ / He₂⁺ γ', detail: Object.values(wall.ceramic_ion_yield).join(' / ') }
    ] : [];
    list.replaceChildren();
    for (const [title, rows] of [['输入中的碰撞与反应', checks.reactions], ['输入中的界面', checks.surfaces],
                                ['Jia 气相反应清单', plan], ['Jia 界面参考', plannedSurfaces]]) {
        const matches = rows.filter(row => `${row.name} ${row.detail}`.toLowerCase().includes(query));
        if (!matches.length) continue;
        const heading = document.createElement('h3');
        heading.textContent = title;
        list.append(heading, ...matches.map(row => checkRow(row.name, row.detail)));
    }
    if (!list.childElementCount) list.textContent = '没有匹配条目。';
}

element('self-check').ontoggle = safe(async () => {
    if (!element('self-check').open || !selection) return;
    const key = selection.id;
    element('check-items').textContent = '正在核对输入…';
    element('check-reactions').replaceChildren();
    element('check-hashes').replaceChildren();
    const result = await request('selfCheck', { key });
    if (selection?.id !== key) return;
    checks = result;
    element('check-items').replaceChildren(...checks.checks.map(row => checkRow(row.label, row.value)));
    element('check-hashes').replaceChildren(...Object.entries(checks.hashes).map(([name, hash]) => checkRow(name, hash)));
    filterChecks();
});
element('reaction-filter').oninput = filterChecks;

function showImage(data) {
    plot.src = 'data:image/png;base64,' + data;
    plot.hidden = false;
    message.hidden = true;
}

function plotOptions() {
    return { key: selection.id, field: field.value, index: Number(time.value),
        color: palettes[field.value] || defaultColors[field.value], focus: element('focus').value,
        clean: element('clean-plot').checked,
        mesh_overlay: element('mesh-overlay').checked && !element('clean-plot').checked,
        equal: element('equal-scale').checked };
}

async function redraw(preview) {
    if (!detail || !selection) return;
    const args = plotOptions();
    const stamp = detail.frames[args.index];
    element('time-label').textContent = stamp === undefined || !field.value || preview
        ? '几何' : `${Number(stamp.toPrecision(6))} ns · ${args.index + 1}/${detail.frames.length}`;
    if (preview) args.draft = preview;
    queuedFrame = { args, version: ++renderVersion };
    if (drawing) return;
    drawing = true;
    try {
        while (queuedFrame) {
            const { args: frame, version } = queuedFrame;
            queuedFrame = null;
            const key = JSON.stringify(frame);
            try {
                let data = cache.get(key);
                if (!data) {
                    data = await request('render', frame);
                    if (cache.size >= 42) cache.delete(cache.keys().next().value);
                    cache.set(key, data);
                }
                if (version === renderVersion) showImage(data);
            } catch (error) {
                if (version === renderVersion) {
                    plot.hidden = true;
                    message.hidden = false;
                    message.textContent = error.message;
                }
            }
        }
    } finally {
        drawing = false;
    }
}

function stop() {
    playing = false;
    ++playVersion;
    element('play').textContent = '播放';
}

element('play').onclick = () => {
    if (playing) { stop(); return; }
    if (!field.value) field.value = 'ElectronDensityCell';
    playing = true;
    const version = ++playVersion;
    element('play').textContent = '暂停';
    async function next() {
        if (!playing || version !== playVersion) return;
        if (!drawing) {
            time.value = (Number(time.value) + 1) % detail.frames.length;
            await redraw();
        }
        if (playing && version === playVersion) setTimeout(next, 300);
    }
    next();
};

element('refresh').onclick = safe(() => loadCatalog());
element('show-validation').onchange = safe(() => loadCatalog());
element('rename-case').onclick = safe(async () => {
    const model = caseSelected();
    if (!model || renamingCase) return;
    renamingCase = true;
    updateActions();
    try {
        const name = await request('renameCase', { key: model.id });
        if (name) {
            await loadCatalog(undefined, { keepView: true });
            status(`算例已重命名为「${name}」。`);
        }
    } finally {
        renamingCase = false;
        updateActions();
    }
});
element('delete-result').onclick = safe(async () => {
    const moved = await request('delete', { key: selection.id });
    if (moved) {
        await loadCatalog();
        status(`运行结果已移到 ${moved}`);
    }
});
element('delete-case').onclick = safe(async () => {
    const model = caseSelected();
    if (!model) return;
    const moved = await request('deleteCase', { key: model.id });
    if (moved) {
        await loadCatalog();
        status(`算例已移到 ${moved}`);
    }
});
element('clean-plot').onchange = () => redraw();
element('export-png').onclick = safe(async () => {
    if (await request('exportPNG', plotOptions())) status('已保存当前帧 PNG。');
});
dataset.onchange = safe(selectDataset);
time.oninput = () => { stop(); redraw(); };
field.onchange = () => { loadColors(); updateActions(); redraw(); };
element('focus').value = vscode.getState()?.focus || 'full';
element('focus').onchange = () => { saveView(); redraw(); };
element('color-scale').onchange = safe(applyColors);
element('manual-color').onchange = safe(() => {
    const manual = element('manual-color').checked;
    for (const name of ['color-low', 'color-high']) element(name).disabled = !manual;
    applyColors();
});
element('apply-color').onclick = safe(applyColors);
for (const name of ['color-low', 'color-high']) {
    element(name).onkeydown = safe(event => {
        if (event.key === 'Enter') applyColors();
    });
}
element('mesh-overlay').onchange = () => redraw();
element('equal-scale').onchange = () => redraw();
element('preview').onclick = () => { stop(); redraw(draft()); };
element('needle-shape').onchange = () => {
    element('taper').hidden = element('needle-shape').value !== 'tapered';
    markDirty();
};
element('select-model').onclick = safe(async () => {
    dataset.value = selection.case;
    await selectDataset();
});
element('diameter').onchange = event => {
    if (event.target.value) {
        setFields('geometry', { tube_bore_um: Number(event.target.value) });
        markDirty();
    }
};
element('preset').onchange = event => {
    if (event.target.value) {
        setFields('mesh', catalog.meshPresets[event.target.value]);
        markDirty();
    }
};
element('save-parameters').onclick = safe(async () => {
    const key = selection.id;
    const revision = editRevision;
    savingModel = true;
    updateActions();
    try {
        await request('saveParameters', { key, draft: draft(), revision: detail.parameterRevision,
            parameters: fields('pulse'), initial: fields('initial'), weights: caseWeights() });
        if (selection?.id !== key) return;
        if (revision === editRevision) {
            dirty = false;
            await loadCatalog(key);
        } else {
            const saved = await request('describe', { key });
            if (selection?.id !== key) return;
            detail.parameterRevision = saved.parameterRevision;
        }
        if (selection?.id === key) {
            status(dirty ? '已保存提交时的参数。后续修改仍为草稿。' : '参数已保存，可运行完整脉冲。');
        }
    } finally {
        savingModel = false;
        updateActions();
    }
});
element('clone').onclick = safe(async () => {
    savingModel = true;
    updateActions();
    try {
        const key = await request('clone', { key: selection.id, draft: draft(),
            parameters: fields('pulse'), initial: fields('initial'), weights: caseWeights() });
        await loadCatalog(key);
        status('已创建独立算例。');
    } finally {
        savingModel = false;
        updateActions();
    }
});
for (const button of document.querySelectorAll('[data-file]')) {
    button.onclick = safe(() => request('open', { key: selection.id, file: button.dataset.file }));
}
for (const button of document.querySelectorAll('[data-task]')) {
    button.onclick = safe(async () => {
        taskRunning = true;
        updateActions();
        try {
            await request('task', { key: selection.id, name: button.dataset.task, ranks: Number(element('ranks').value) });
            status('任务已启动。');
        } catch (error) {
            taskRunning = false;
            updateActions();
            throw error;
        }
    });
}
element('save-adaptive-weight').onclick = safe(async () => {
    await request('saveAdaptiveWeight', { settings: adaptiveSettings() });
    status('已保存动态权重参数。');
});
element('run-adaptive-weight').onclick = safe(async () => {
    taskRunning = true;
    updateActions();
    try {
        await request('task', { name: 'adaptive', adaptive: adaptiveSettings() });
        status('动态权重短测已启动。');
    } catch (error) {
        taskRunning = false;
        updateActions();
        throw error;
    }
});
element('pv-result').onclick = safe(() => request('paraview', { key: selection.id, field: field.value }));
element('pv-model').onclick = safe(() => request('paraview', { key: selection.id, field: '', geometry: true }));

window.addEventListener('message', safe(async event => {
    const reply = event.data;
    if (reply.event === 'taskDone') {
        taskRunning = false;
        await loadCatalog();
        let run;
        if (!dirty && reply.code === 0 && (reply.case || reply.job === 'adaptive')) {
            run = reply.job === 'adaptive' ? catalog.runs.find(item => item.adaptive && item.complete) :
                catalog.runs.find(item => item.case === reply.case && item.complete &&
                    item.kind === (reply.job === 'pilot' ? 'pilot' : '') && !item.label.startsWith('无效 · '));
            if (run) {
                progressRun = run.id;
                if (run.validation) element('show-validation').checked = true;
                await loadCatalog(run.id);
            }
        }
        const conversionFailed = run?.conversionStatus === 'failed';
        const result = conversionFailed ? '求解已完成，HDF5 可查看。VTU 导出失败，可重试「导出 VTU」。'
            : reply.code === 0 ? '任务已完成。' : '任务已退出，请查看 VS Code 终端。';
        status(dirty ? result + (modelSelected()?.canSaveParameters ? ' 参数草稿已保留，可点击「保存参数」。'
            : ' 参数草稿已保留，可另存为独立算例。') : result, reply.code !== 0 || conversionFailed);
        return;
    }
    const pending = requests.get(reply.id);
    if (!pending) return;
    requests.delete(reply.id);
    if (reply.error) pending.reject(new Error(reply.error));
    else pending.resolve(reply.result);
}));

plot.addEventListener('load', () => vscode.postMessage({ event: 'firstPlotLoaded' }), { once: true });
safe(loadCatalog)();
safe(loadAdaptiveWeight)();
pollProgress();
