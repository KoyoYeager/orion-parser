import * as vscode from 'vscode';

export class GraphPanel {
    public static currentPanel: GraphPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private _disposables: vscode.Disposable[] = [];

    public static createOrShow(extensionUri: vscode.Uri, title: string, data: any, graphType: string) {
        const column = vscode.ViewColumn.Beside;

        if (GraphPanel.currentPanel) {
            GraphPanel.currentPanel._panel.reveal(column);
            GraphPanel.currentPanel._update(title, data, graphType);
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            'orionparserGraph',
            title,
            column,
            { enableScripts: true, retainContextWhenHidden: true }
        );

        GraphPanel.currentPanel = new GraphPanel(panel, title, data, graphType);
    }

    private constructor(panel: vscode.WebviewPanel, title: string, data: any, graphType: string) {
        this._panel = panel;
        this._update(title, data, graphType);

        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        this._panel.webview.onDidReceiveMessage(
            async (message) => {
                switch (message.command) {
                    case 'export': await this._handleExport(message.format, message.data, message.graphType, message.funcName); break;
                    case 'jumpToLine': await this._jumpToLine(message.file, message.line); break;
                }
            },
            null, this._disposables
        );
    }

    public dispose() {
        GraphPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const d = this._disposables.pop();
            if (d) { d.dispose(); }
        }
    }

    private _update(title: string, data: any, graphType: string) {
        this._panel.title = `OrionParser: ${title}`;
        this._panel.webview.html = this._getHtml(data, graphType);
    }

    private _getHtml(data: any, graphType: string): string {
        const dataJson = JSON.stringify(data).replace(/</g, '\\u003c');
        return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
:root { --bg: var(--vscode-editor-background); --fg: var(--vscode-foreground); --border: var(--vscode-panel-border);
    --input-bg: var(--vscode-input-background); --input-fg: var(--vscode-input-foreground); --input-border: var(--vscode-input-border);
    --sel-bg: var(--vscode-editor-selectionBackground); --desc: var(--vscode-descriptionForeground); }
* { box-sizing: border-box; }
body { font-family: var(--vscode-font-family); color: var(--fg); background: var(--bg); margin: 0; padding: 0; overflow: hidden; }
.toolbar { display: flex; gap: 6px; padding: 6px 10px; align-items: center; flex-wrap: wrap;
    border-bottom: 1px solid var(--border); background: var(--bg); }
.toolbar select, .toolbar button, .toolbar input {
    padding: 3px 8px; border-radius: 3px; border: 1px solid var(--input-border);
    background: var(--input-bg); color: var(--input-fg); font-size: 12px; cursor: pointer; }
.toolbar button:hover { background: var(--vscode-button-hoverBackground); color: var(--vscode-button-foreground); }
.toolbar label { font-size: 12px; color: var(--desc); margin-right: 2px; }
.separator { width: 1px; height: 20px; background: var(--border); margin: 0 4px; }
#graphContainer { width: 100%; height: calc(100vh - 44px); overflow: hidden; position: relative; }
#svgCanvas { position: absolute; top: 0; left: 0; }
.tooltip-box { position: fixed; background: var(--vscode-editorHoverWidget-background);
    border: 1px solid var(--vscode-editorHoverWidget-border); padding: 8px 12px;
    border-radius: 4px; font-size: 12px; max-width: 450px; display: none; z-index: 200;
    white-space: pre-wrap; line-height: 1.5; pointer-events: none; }
/* Symbol table */
.sym-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.sym-table th { background: var(--sel-bg); padding: 6px 8px; text-align: left; position: sticky; top: 0; }
.sym-table td { padding: 4px 8px; border-bottom: 1px solid var(--border); }
.sym-table tr:hover { background: var(--sel-bg); cursor: pointer; }
.sym-category { font-size: 13px; font-weight: bold; margin: 12px 0 6px 0; padding: 4px 8px;
    background: var(--sel-bg); border-radius: 3px; }
</style>
</head>
<body>
<div class="toolbar">
    <span id="graphTitle" style="font-weight:bold; font-size: 13px;"></span>
    <div class="separator"></div>
    <label>ファイル:</label><select id="fileSelect" style="display:none; max-width:180px;"></select>
    <label>関数:</label><select id="funcSelect" style="max-width:220px;"></select>
    <label>範囲:</label><select id="scopeSelect">
        <option value="callees">呼び出し先のみ</option>
        <option value="path">経路+呼び出し先</option>
        <option value="siblings">兄弟も含む</option>
        <option value="all" selected>すべて</option>
    </select>
    <div class="separator"></div>
    <button id="fitBtn" title="フィット">⊞ フィット</button>
    <button id="zoomInBtn" title="拡大">＋</button>
    <button id="zoomOutBtn" title="縮小">－</button>
    <div class="separator"></div>
    <select id="exportCat">
        <option value="image">画像</option>
        <option value="dev">開発者</option>
        <option value="data">データ</option>
    </select>
    <select id="exportFormat">
        <option value="svg">SVG</option>
        <option value="png">PNG</option>
        <option value="json">JSON</option>
    </select>
    <button id="exportBtn">💾 保存</button>
</div>
<div id="graphContainer"></div>
<div id="tooltip" class="tooltip-box"></div>

<script>
const vscode = acquireVsCodeApi();
const graphData = ${dataJson};
const graphType = "${graphType}";

let transform = { x: 0, y: 0, scale: 1 };
let isDragging = false, dragStart = { x: 0, y: 0 };

/* ============================== INIT ============================== */
function init() {
    document.getElementById('graphTitle').textContent = ({
        calltree: 'コールツリー', flowchart: 'フローチャート',
        dfd: 'DFD', classdiagram: 'クラス図', symbols: 'シンボル一覧'
    })[graphType] || graphType;

    setupToolbar();
    setupExportCategories();
    render();
    setupPanZoom();
}

function setupToolbar() {
    const funcSel = document.getElementById('funcSelect');
    const scopeSel = document.getElementById('scopeSelect');

    // コールツリー: 全関数をリスト、範囲選択あり
    if (graphType === 'calltree') {
        const funcs = graphData.functions || [];
        funcSel.innerHTML = '<option value="__all__">すべて表示</option>';
        funcs.sort().forEach(f => {
            const o = document.createElement('option');
            o.value = f; o.textContent = f; funcSel.appendChild(o);
        });
        funcSel.addEventListener('change', () => render());
        scopeSel.addEventListener('change', () => render());
    } else if (graphType === 'flowchart' || graphType === 'dfd') {
        scopeSel.style.display = 'none';
        document.querySelector('label[for="scopeSelect"]')?.remove();
        // scopeSelectの直前のlabelを消す
        const labels = document.querySelectorAll('.toolbar label');
        labels.forEach(l => { if (l.textContent === '範囲:') l.style.display = 'none'; });

        const funcs = Object.keys(graphData.functions || graphData.flowchart || {});
        funcSel.innerHTML = '';
        funcs.forEach(f => {
            const o = document.createElement('option');
            o.value = f; o.textContent = f; funcSel.appendChild(o);
        });
        funcSel.addEventListener('change', () => render());
    } else {
        funcSel.style.display = 'none'; scopeSel.style.display = 'none';
        document.querySelectorAll('.toolbar label').forEach(l => {
            if (l.textContent === '関数:' || l.textContent === '範囲:' || l.textContent === 'ファイル:')
                l.style.display = 'none';
        });
    }

    document.getElementById('fitBtn').addEventListener('click', fitToView);
    document.getElementById('zoomInBtn').addEventListener('click', () => { transform.scale *= 1.2; applyTransform(); });
    document.getElementById('zoomOutBtn').addEventListener('click', () => { transform.scale /= 1.2; applyTransform(); });
    document.getElementById('exportBtn').addEventListener('click', handleExport);
}

function setupExportCategories() {
    const cat = document.getElementById('exportCat');
    const fmt = document.getElementById('exportFormat');
    const formats = {
        image: [['svg','SVG'],['png','PNG']],
        dev: [['mermaid','Mermaid'],['dot','DOT'],['plantuml','PlantUML']],
        data: [['json','JSON'],['html','HTML']],
    };
    cat.addEventListener('change', () => {
        fmt.innerHTML = '';
        (formats[cat.value] || []).forEach(([v,l]) => {
            const o = document.createElement('option'); o.value = v; o.textContent = l; fmt.appendChild(o);
        });
    });
    cat.dispatchEvent(new Event('change'));
}

/* ============================== PAN / ZOOM ============================== */
function setupPanZoom() {
    const c = document.getElementById('graphContainer');
    c.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (e.ctrlKey) {
            const f = e.deltaY < 0 ? 1.12 : 0.89;
            const rect = c.getBoundingClientRect();
            const mx = e.clientX - rect.left, my = e.clientY - rect.top;
            transform.x = mx - (mx - transform.x) * f;
            transform.y = my - (my - transform.y) * f;
            transform.scale *= f;
        } else {
            transform.x -= e.deltaX * 0.8;
            transform.y -= e.deltaY * 0.8;
        }
        applyTransform();
    });
    c.addEventListener('mousedown', (e) => { isDragging = true; dragStart = { x: e.clientX - transform.x, y: e.clientY - transform.y }; });
    window.addEventListener('mousemove', (e) => { if (isDragging) { transform.x = e.clientX - dragStart.x; transform.y = e.clientY - dragStart.y; applyTransform(); } });
    window.addEventListener('mouseup', () => { isDragging = false; });
}

function applyTransform() {
    const svg = document.getElementById('svgCanvas');
    if (svg) { svg.style.transform = 'translate('+transform.x+'px,'+transform.y+'px) scale('+transform.scale+')'; svg.style.transformOrigin = '0 0'; }
}

function fitToView() {
    transform = { x: 20, y: 10, scale: 1 };
    applyTransform();
}

/* ============================== RENDER ============================== */
function render() {
    const c = document.getElementById('graphContainer');
    transform = { x: 20, y: 10, scale: 1 };
    if (graphType === 'calltree') renderCallTree(c);
    else if (graphType === 'flowchart') renderFlowchart(c);
    else if (graphType === 'dfd') renderDFD(c);
    else if (graphType === 'classdiagram') renderClassDiagram(c);
    else if (graphType === 'symbols') renderSymbols(c);
    else c.innerHTML = '<p style="padding:20px;">未対応のグラフタイプです</p>';
    applyTransform();
}

/* ============================== CALL TREE (Column-based + L-connectors + 20 colors) ============================== */
function renderCallTree(container) {
    const funcs = graphData.functions || [];
    const calls = graphData.calls || [];
    const selected = document.getElementById('funcSelect').value;
    const scope = document.getElementById('scopeSelect').value;

    // Build adjacency
    const children = {}, parents = {};
    calls.forEach(([u, v]) => {
        if (!children[u]) children[u] = [];
        children[u].push(v);
        if (!parents[v]) parents[v] = [];
        parents[v].push(u);
    });

    // BFS from <module> to get depths
    const depths = {};
    const roots = funcs.filter(f => !parents[f] || parents[f].length === 0);
    roots.forEach(r => { depths[r] = 0; });
    const queue = [...roots];
    while (queue.length) {
        const n = queue.shift();
        (children[n] || []).forEach(c => {
            if (!(c in depths)) { depths[c] = (depths[n] || 0) + 1; queue.push(c); }
        });
    }
    funcs.forEach(f => { if (!(f in depths)) depths[f] = 0; });

    // Filter by selected function
    let visibleNodes;
    if (selected === '__all__') {
        visibleNodes = new Set(funcs);
    } else {
        visibleNodes = new Set([selected]);
        if (scope === 'callees' || scope === 'path' || scope === 'siblings' || scope === 'all') {
            // Add callees (descendants)
            const bfs = [selected];
            while (bfs.length) { const n = bfs.shift(); (children[n]||[]).forEach(c => { if (!visibleNodes.has(c)) { visibleNodes.add(c); bfs.push(c); }}); }
        }
        if (scope === 'path' || scope === 'siblings' || scope === 'all') {
            // Add path to root
            const pathUp = [selected];
            while (pathUp.length) { const n = pathUp.shift(); (parents[n]||[]).forEach(p => { if (!visibleNodes.has(p)) { visibleNodes.add(p); pathUp.push(p); }}); }
        }
        if (scope === 'siblings') {
            (parents[selected]||[]).forEach(p => { (children[p]||[]).forEach(c => visibleNodes.add(c)); });
        }
        if (scope === 'all') { funcs.forEach(f => visibleNodes.add(f)); }
    }

    const visible = funcs.filter(f => visibleNodes.has(f));
    // 20 depth colors
    const COLORS = ['#B3D9FF','#85C1E9','#76D7C4','#82E0AA','#ABEBC6','#F9E79F','#F5CBA7','#F0B27A',
        '#F1948A','#E8DAEF','#D7BDE2','#C39BD3','#A9CCE3','#A3E4D7','#F7DC6F','#EB984E',
        '#EC7063','#AF7AC5','#5DADE2','#48C9B0'];

    const COL_W = 200, ROW_H = 42, NODE_W = 170, NODE_H = 28, PAD_TOP = 50, PAD_LEFT = 30;

    // Lay out by depth columns, ordered within each column
    const byDepth = {};
    visible.forEach(f => { const d = depths[f] || 0; if (!byDepth[d]) byDepth[d] = []; byDepth[d].push(f); });
    const maxDepth = Math.max(...visible.map(f => depths[f] || 0), 0);

    const pos = {};
    let totalRows = 0;
    for (let d = 0; d <= maxDepth; d++) {
        (byDepth[d] || []).forEach((f, i) => {
            pos[f] = { x: PAD_LEFT + d * COL_W, y: PAD_TOP + totalRows * ROW_H };
            totalRows++;
        });
    }

    const svgW = PAD_LEFT + (maxDepth + 1) * COL_W + 60;
    const svgH = PAD_TOP + totalRows * ROW_H + 40;

    let svg = '<svg id="svgCanvas" xmlns="http://www.w3.org/2000/svg" width="'+svgW+'" height="'+svgH+'" style="font-family:Consolas,monospace;">';
    svg += '<defs><marker id="arrowCT" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#666"/></marker></defs>';

    // Column headers
    for (let d = 0; d <= maxDepth; d++) {
        const x = PAD_LEFT + d * COL_W;
        svg += '<text x="'+(x+NODE_W/2)+'" y="25" text-anchor="middle" font-size="11" fill="var(--desc)" font-weight="bold">階層 '+(d+1)+'</text>';
        svg += '<line x1="'+x+'" y1="35" x2="'+(x+NODE_W)+'" y2="35" stroke="var(--border)" stroke-width="1"/>';
    }

    // L-shaped connectors
    calls.forEach(([u, v]) => {
        const p1 = pos[u], p2 = pos[v];
        if (!p1 || !p2) return;
        const x1 = p1.x + NODE_W, y1 = p1.y + NODE_H / 2;
        const x2 = p2.x, y2 = p2.y + NODE_H / 2;
        const midX = x1 + (x2 - x1) * 0.5;
        svg += '<path d="M'+x1+' '+y1+' L'+midX+' '+y1+' L'+midX+' '+y2+' L'+x2+' '+y2+'" fill="none" stroke="#888" stroke-width="1.2" marker-end="url(#arrowCT)"/>';
    });

    // Nodes
    visible.forEach(f => {
        const p = pos[f];
        const d = depths[f] || 0;
        const c = COLORS[d % COLORS.length];
        const label = f.length > 22 ? f.substring(0, 20) + '..' : f;
        const isSelected = (f === selected && selected !== '__all__');
        const strokeW = isSelected ? 3 : 1.5;
        const strokeC = isSelected ? '#FF6B6B' : '#666';
        svg += '<g class="node-group" data-name="'+esc(f)+'" onmouseenter="showTip(this,event)" onmouseleave="hideTip()" onclick="nodeClick(\\''+esc(f)+'\\')">'+
            '<rect x="'+p.x+'" y="'+p.y+'" width="'+NODE_W+'" height="'+NODE_H+'" rx="4" fill="'+c+'" stroke="'+strokeC+'" stroke-width="'+strokeW+'"/>'+
            '<text x="'+(p.x+NODE_W/2)+'" y="'+(p.y+NODE_H/2+4)+'" text-anchor="middle" font-size="10" fill="#333">'+esc(label)+'</text></g>';
    });

    // Legend
    let ly = svgH - 10;
    svg += '<text x="'+PAD_LEFT+'" y="'+ly+'" font-size="10" fill="var(--desc)">深さ色: ';
    for (let i = 0; i <= Math.min(maxDepth, 9); i++) {
        const lx = PAD_LEFT + 50 + i * 40;
        svg += '<tspan><rect x="'+lx+'" y="'+(ly-10)+'" width="12" height="12" rx="2" fill="'+COLORS[i]+'"/></tspan>';
    }
    svg += '</text>';
    svg += '</svg>';
    container.innerHTML = svg;
}

/* ============================== FLOWCHART (JIS shapes) ============================== */
function renderFlowchart(container) {
    const funcName = document.getElementById('funcSelect').value;
    const funcs = graphData.functions || {};
    const cfg = funcs[funcName];
    if (!cfg) { container.innerHTML = '<p style="padding:20px;">関数を選択してください</p>'; return; }

    const nodes = cfg.nodes || [];
    const edges = cfg.edges || [];
    const ROW_H = 65;
    const CENTER_X = 300;
    const NO_OFFSET_X = 200;

    // Calculate node widths
    function nodeW(label) { return Math.max(160, label.length * 8 + 30); }

    // Position nodes
    const pos = {};
    let row = 0;
    const noNodes = new Set();
    nodes.forEach((n, i) => {
        pos[n.id] = { x: CENTER_X, y: row * ROW_H + 30, w: nodeW(n.label) };
        row++;
    });

    // Detect NO branches — shift right
    edges.forEach(e => {
        if (e.label === 'False' || e.label === 'No') {
            const fromPos = pos[e.from];
            const toPos = pos[e.to];
            if (fromPos && toPos && toPos.x === CENTER_X) {
                noNodes.add(e.to);
            }
        }
    });

    const svgH = row * ROW_H + 80;
    const svgW = CENTER_X + NO_OFFSET_X + 200;

    let svg = '<svg id="svgCanvas" xmlns="http://www.w3.org/2000/svg" width="'+svgW+'" height="'+svgH+'" style="font-family:Consolas,\\'MS Gothic\\',monospace;">';
    svg += '<defs><marker id="arrowFC" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#3C5A99"/></marker></defs>';

    // Colors per type
    const typeColors = {
        start: '#A9DFBF', end: '#F5B7B1', process: '#85C1E9', decision: '#F9E79F',
        loop_start: '#D7BDE2', loop_end: '#D7BDE2', io: '#F5CBA7', return: '#F5B7B1'
    };

    // Draw edges first (behind nodes)
    edges.forEach(e => {
        const pFrom = pos[e.from], pTo = pos[e.to];
        if (!pFrom || !pTo) return;
        const fromNode = nodes.find(n => n.id === e.from);
        const isNo = (e.label === 'False' || e.label === 'No');
        const wFrom = pFrom.w || 160, hNode = 30;

        let path;
        if (isNo && fromNode && fromNode.type === 'decision') {
            // NO: horizontal right then down
            const x1 = pFrom.x + wFrom/2, y1 = pFrom.y;
            const xMid = pFrom.x + wFrom/2 + NO_OFFSET_X;
            const y2 = pTo.y;
            path = 'M'+x1+' '+y1+' L'+xMid+' '+y1+' L'+xMid+' '+y2+' L'+(pTo.x + (pTo.w||160)/2)+' '+y2;
            svg += '<path d="'+path+'" fill="none" stroke="#3C5A99" stroke-width="1.5" marker-end="url(#arrowFC)"/>';
            svg += '<text x="'+(x1+8)+'" y="'+(y1-5)+'" font-size="10" fill="#C0392B" font-weight="bold">NO</text>';
        } else {
            // YES / normal: straight down
            const x1 = pFrom.x, y1 = pFrom.y + hNode/2;
            const x2 = pTo.x, y2 = pTo.y - hNode/2;
            path = 'M'+x1+' '+y1+' L'+x2+' '+y2;
            svg += '<line x1="'+x1+'" y1="'+y1+'" x2="'+x2+'" y2="'+y2+'" stroke="#3C5A99" stroke-width="1.5" marker-end="url(#arrowFC)"/>';
            if (e.label === 'True' || e.label === 'Yes') {
                svg += '<text x="'+(x1+5)+'" y="'+(y1+14)+'" font-size="10" fill="#27AE60" font-weight="bold">YES</text>';
            }
        }
    });

    // Draw nodes
    nodes.forEach(n => {
        const p = pos[n.id];
        const w = p.w || 160, h = 30;
        const c = typeColors[n.type] || '#85C1E9';
        const cx = p.x, cy = p.y;
        const label = n.label;

        svg += '<g class="node-group" data-name="'+esc(label)+'" onmouseenter="showTip(this,event)" onmouseleave="hideTip()">';

        if (n.type === 'start' || n.type === 'end' || n.type === 'return') {
            // 角丸端子 (JIS terminal)
            svg += '<rect x="'+(cx-w/2)+'" y="'+(cy-h/2)+'" width="'+w+'" height="'+h+'" rx="'+h/2+'" fill="'+c+'" stroke="#333" stroke-width="1.5"/>';
        } else if (n.type === 'decision') {
            // ひし形 (JIS decision)
            const dw = w * 0.65, dh = h * 0.85;
            svg += '<polygon points="'+cx+','+(cy-dh)+' '+(cx+dw)+','+cy+' '+cx+','+(cy+dh)+' '+(cx-dw)+','+cy+'" fill="'+c+'" stroke="#333" stroke-width="1.5"/>';
        } else if (n.type === 'loop_start') {
            // 台形 (下広) — JIS loop start
            const top = w * 0.35, bot = w * 0.5;
            svg += '<polygon points="'+(cx-top)+','+(cy-h/2)+' '+(cx+top)+','+(cy-h/2)+' '+(cx+bot)+','+(cy+h/2)+' '+(cx-bot)+','+(cy+h/2)+'" fill="'+c+'" stroke="#333" stroke-width="1.5"/>';
        } else if (n.type === 'loop_end') {
            // 台形 (上広) — JIS loop end
            const top = w * 0.5, bot = w * 0.35;
            svg += '<polygon points="'+(cx-top)+','+(cy-h/2)+' '+(cx+top)+','+(cy-h/2)+' '+(cx+bot)+','+(cy+h/2)+' '+(cx-bot)+','+(cy+h/2)+'" fill="'+c+'" stroke="#333" stroke-width="1.5"/>';
        } else if (n.type === 'io') {
            // 平行四辺形 (JIS I/O)
            const skew = 15;
            svg += '<polygon points="'+(cx-w/2+skew)+','+(cy-h/2)+' '+(cx+w/2+skew)+','+(cy-h/2)+' '+(cx+w/2-skew)+','+(cy+h/2)+' '+(cx-w/2-skew)+','+(cy+h/2)+'" fill="'+c+'" stroke="#333" stroke-width="1.5"/>';
        } else {
            // 四角形 (JIS process)
            svg += '<rect x="'+(cx-w/2)+'" y="'+(cy-h/2)+'" width="'+w+'" height="'+h+'" fill="'+c+'" stroke="#333" stroke-width="1.5"/>';
        }

        const fontSize = label.length > 35 ? 8 : (label.length > 25 ? 9 : 10);
        const displayLabel = label.length > 45 ? label.substring(0,42)+'...' : label;
        svg += '<text x="'+cx+'" y="'+(cy+4)+'" text-anchor="middle" font-size="'+fontSize+'" fill="#333">'+esc(displayLabel)+'</text>';
        svg += '</g>';
    });

    // Shape legend
    svg += '<g transform="translate(10,'+(svgH-25)+')" font-size="9" fill="var(--desc)">';
    svg += '<rect x="0" y="-8" width="16" height="10" rx="5" fill="#A9DFBF" stroke="#333" stroke-width="0.5"/><text x="20" y="0">端子</text>';
    svg += '<rect x="55" y="-8" width="16" height="10" fill="#85C1E9" stroke="#333" stroke-width="0.5"/><text x="75" y="0">処理</text>';
    svg += '<polygon points="130,-3 138,-8 146,-3 138,2" fill="#F9E79F" stroke="#333" stroke-width="0.5"/><text x="150" y="0">判断</text>';
    svg += '<polygon points="190,-8 210,-8 215,2 185,2" fill="#D7BDE2" stroke="#333" stroke-width="0.5"/><text x="220" y="0">ループ</text>';
    svg += '</g>';
    svg += '</svg>';
    container.innerHTML = svg;
}

/* ============================== DFD (SVG process-based) ============================== */
function renderDFD(container) {
    const funcName = document.getElementById('funcSelect').value;
    const funcs = graphData.functions || {};
    const finfo = funcs[funcName];
    if (!finfo) { container.innerHTML = '<p style="padding:20px;">関数を選択してください</p>'; return; }

    const vars = finfo.variables || {};
    const calls = finfo.calls || [];
    const varNames = Object.keys(vars);
    const PAD = 40, NODE_H = 35, PROC_W = 150, VAR_W = 120, SPACING_Y = 55;

    // Layout: variables on left, processes (calls) on right
    const procY = {};
    calls.forEach((c, i) => { procY[c.func + '_' + i] = PAD + i * SPACING_Y; });

    const varY = {};
    varNames.forEach((v, i) => { varY[v] = PAD + i * SPACING_Y; });

    const leftX = PAD, rightX = PAD + VAR_W + 120;
    const svgH = PAD + Math.max(varNames.length, calls.length) * SPACING_Y + 60;
    const svgW = rightX + PROC_W + PAD;

    let svg = '<svg id="svgCanvas" xmlns="http://www.w3.org/2000/svg" width="'+svgW+'" height="'+svgH+'" style="font-family:Consolas,monospace;">';
    svg += '<defs><marker id="arrowDFD" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L10 5L0 10z" fill="#3C5A99"/></marker></defs>';

    // Column headers
    svg += '<text x="'+(leftX + VAR_W/2)+'" y="20" text-anchor="middle" font-size="11" fill="var(--desc)" font-weight="bold">変数・データ</text>';
    svg += '<text x="'+(rightX + PROC_W/2)+'" y="20" text-anchor="middle" font-size="11" fill="var(--desc)" font-weight="bold">プロセス</text>';

    // Variable nodes (parallelogram = data store)
    varNames.forEach(v => {
        const y = varY[v];
        const skew = 10;
        svg += '<g class="node-group" data-name="'+esc(v)+'" onmouseenter="showTip(this,event)" onmouseleave="hideTip()">';
        svg += '<polygon points="'+(leftX+skew)+','+y+' '+(leftX+VAR_W+skew)+','+y+' '+(leftX+VAR_W-skew)+','+(y+NODE_H)+' '+(leftX-skew)+','+(y+NODE_H)+'" fill="#A9DFBF" stroke="#333" stroke-width="1.2"/>';
        const label = v.length > 14 ? v.substring(0,12)+'..' : v;
        svg += '<text x="'+(leftX+VAR_W/2)+'" y="'+(y+NODE_H/2+4)+'" text-anchor="middle" font-size="10" fill="#333">'+esc(label)+'</text>';
        svg += '</g>';
    });

    // Process nodes (rounded rect)
    calls.forEach((c, i) => {
        const key = c.func + '_' + i;
        const y = procY[key];
        svg += '<g class="node-group">';
        svg += '<rect x="'+rightX+'" y="'+y+'" width="'+PROC_W+'" height="'+NODE_H+'" rx="8" fill="#85C1E9" stroke="#333" stroke-width="1.2"/>';
        const label = (c.result_var ? c.result_var + ' = ' : '') + c.func;
        const dl = label.length > 18 ? label.substring(0,16)+'..' : label;
        svg += '<text x="'+(rightX+PROC_W/2)+'" y="'+(y+NODE_H/2+4)+'" text-anchor="middle" font-size="10" fill="#333">'+esc(dl)+'</text>';
        svg += '</g>';

        // Edges: args → process, process → result
        (c.args || []).forEach(arg => {
            if (varY[arg] !== undefined) {
                const vy = varY[arg] + NODE_H/2;
                const py = y + NODE_H/2;
                svg += '<line x1="'+(leftX+VAR_W)+'" y1="'+vy+'" x2="'+rightX+'" y2="'+py+'" stroke="#3C5A99" stroke-width="1" marker-end="url(#arrowDFD)" opacity="0.7"/>';
            }
        });
        if (c.result_var && varY[c.result_var] !== undefined) {
            const vy = varY[c.result_var] + NODE_H/2;
            const py = y + NODE_H/2;
            svg += '<line x1="'+rightX+'" y1="'+py+'" x2="'+(leftX+VAR_W)+'" y2="'+vy+'" stroke="#27AE60" stroke-width="1" stroke-dasharray="4" marker-end="url(#arrowDFD)" opacity="0.7"/>';
        }
    });

    // Variable details table below
    let ty = Math.max(varNames.length, calls.length) * SPACING_Y + PAD + 20;
    svg += '<text x="'+PAD+'" y="'+ty+'" font-size="12" fill="var(--fg)" font-weight="bold">変数詳細</text>';
    ty += 20;
    varNames.forEach(v => {
        const info = vars[v];
        const defs = (info.defined_at || []).map(d => d.expr || '').join(', ');
        const uses = (info.used_at || []).map(u => u.expr || '').join(', ');
        svg += '<text x="'+PAD+'" y="'+ty+'" font-size="10" fill="var(--fg)"><tspan font-weight="bold">'+esc(v)+'</tspan>  定義: '+esc(defs.substring(0,60))+'  使用: '+esc(uses.substring(0,60))+'</text>';
        ty += 16;
    });

    svg += '</svg>';
    container.innerHTML = svg;
}

/* ============================== CLASS DIAGRAM (UML + inheritance) ============================== */
function renderClassDiagram(container) {
    const classes = graphData.classes || {};
    const classNames = Object.keys(classes);
    if (classNames.length === 0) { container.innerHTML = '<p style="padding:20px;">クラスが見つかりません</p>'; return; }

    const BOX_W = 280, PAD = 30, LINE_H = 18, SPACING = 40;
    let totalH = PAD;
    const positions = {};

    // Calculate heights and positions
    classNames.forEach(name => {
        const info = classes[name];
        const attrs = info.attributes || [];
        const methods = info.methods || [];
        const headerH = 30;
        const attrH = Math.max(attrs.length, 1) * LINE_H + 10;
        const methodH = Math.max(methods.length, 1) * LINE_H + 10;
        const boxH = headerH + attrH + methodH;
        positions[name] = { x: PAD, y: totalH, w: BOX_W, h: boxH, headerH, attrH, methodH };
        totalH += boxH + SPACING;
    });

    // Multi-column for many classes
    const cols = Math.ceil(Math.sqrt(classNames.length));
    let col = 0, maxColH = 0, colX = PAD;
    const colHeights = new Array(cols).fill(PAD);
    classNames.forEach(name => {
        const p = positions[name];
        p.x = colX;
        p.y = colHeights[col];
        colHeights[col] += p.h + SPACING;
        col++;
        if (col >= cols) { col = 0; colX = PAD; }
        else { colX += BOX_W + SPACING * 2; }
    });

    const svgW = cols * (BOX_W + SPACING * 2) + PAD;
    const svgH = Math.max(...colHeights) + PAD;

    let svg = '<svg id="svgCanvas" xmlns="http://www.w3.org/2000/svg" width="'+svgW+'" height="'+svgH+'" style="font-family:Consolas,monospace;">';
    svg += '<defs><marker id="inherit" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0L10 5L0 10z" fill="white" stroke="#333"/></marker></defs>';

    // Draw inheritance arrows first
    classNames.forEach(name => {
        const info = classes[name];
        (info.bases || []).forEach(base => {
            if (positions[base]) {
                const child = positions[name];
                const parent = positions[base];
                svg += '<line x1="'+(child.x+child.w/2)+'" y1="'+child.y+'" x2="'+(parent.x+parent.w/2)+'" y2="'+(parent.y+parent.h)+'" stroke="#333" stroke-width="2" marker-end="url(#inherit)"/>';
            }
        });
    });

    // Draw class boxes
    classNames.forEach(name => {
        const info = classes[name];
        const p = positions[name];
        const attrs = info.attributes || [];
        const methods = info.methods || [];

        svg += '<g class="node-group" data-name="'+esc(name)+'" onmouseenter="showTip(this,event)" onmouseleave="hideTip()">';
        // Background
        svg += '<rect x="'+p.x+'" y="'+p.y+'" width="'+p.w+'" height="'+p.h+'" fill="var(--input-bg)" stroke="var(--fg)" stroke-width="2" rx="2"/>';
        // Header
        svg += '<rect x="'+p.x+'" y="'+p.y+'" width="'+p.w+'" height="'+p.headerH+'" fill="var(--sel-bg)" stroke="var(--fg)" stroke-width="2" rx="2"/>';
        svg += '<text x="'+(p.x+p.w/2)+'" y="'+(p.y+p.headerH/2+5)+'" text-anchor="middle" font-size="13" font-weight="bold" fill="var(--fg)">'+esc(name)+'</text>';

        // Divider after header
        const attrStartY = p.y + p.headerH;
        svg += '<line x1="'+p.x+'" y1="'+attrStartY+'" x2="'+(p.x+p.w)+'" y2="'+attrStartY+'" stroke="var(--fg)" stroke-width="1"/>';

        // Attributes
        attrs.forEach((a, i) => {
            const ty = attrStartY + 6 + (i + 1) * LINE_H;
            const typeStr = a.type ? ': ' + a.type : '';
            const defStr = a.default ? ' = ' + a.default : '';
            svg += '<text x="'+(p.x+10)+'" y="'+ty+'" font-size="11" fill="var(--fg)">'+esc(a.name + typeStr + defStr)+'</text>';
        });
        if (attrs.length === 0) {
            svg += '<text x="'+(p.x+10)+'" y="'+(attrStartY+LINE_H)+'" font-size="10" fill="var(--desc)">(属性なし)</text>';
        }

        // Divider after attributes
        const methodStartY = attrStartY + p.attrH;
        svg += '<line x1="'+p.x+'" y1="'+methodStartY+'" x2="'+(p.x+p.w)+'" y2="'+methodStartY+'" stroke="var(--fg)" stroke-width="1"/>';

        // Methods
        methods.forEach((m, i) => {
            const ty = methodStartY + 6 + (i + 1) * LINE_H;
            const retStr = m.returns ? ' → ' + m.returns : '';
            const prefix = m.is_static ? '«static» ' : (m.is_property ? '«property» ' : '');
            svg += '<text x="'+(p.x+10)+'" y="'+ty+'" font-size="11" fill="var(--fg)">'+esc(prefix + m.name + '(' + (m.params || '') + ')' + retStr)+'</text>';
        });
        if (methods.length === 0) {
            svg += '<text x="'+(p.x+10)+'" y="'+(methodStartY+LINE_H)+'" font-size="10" fill="var(--desc)">(メソッドなし)</text>';
        }

        svg += '</g>';
    });

    svg += '</svg>';
    container.innerHTML = svg;
}

/* ============================== SYMBOLS ============================== */
function renderSymbols(container) {
    const symbols = graphData.symbols || {};
    container.style.overflow = 'auto';

    let html = '<div style="padding:16px; overflow:auto; height:100%;">';
    const sections = [
        { key: 'classes', title: 'クラス', icon: '📦' },
        { key: 'functions', title: '関数', icon: '⚙' },
        { key: 'variables', title: '変数', icon: '📝' },
        { key: 'imports', title: 'インポート', icon: '📥' },
    ];

    sections.forEach(s => {
        const items = symbols[s.key] || [];
        if (items.length === 0) return;
        html += '<div class="sym-category">'+s.icon+' '+s.title+' ('+items.length+')</div>';
        html += '<table class="sym-table"><tr><th>名前</th><th>スコープ</th><th>行</th><th>説明</th></tr>';
        items.forEach(item => {
            html += '<tr onclick="jumpTo('+item.line+')"><td><strong>'+esc(item.name)+'</strong></td><td>'+esc(item.scope||'')+'</td><td>'+item.line+'</td><td style="color:var(--desc);">'+esc((item.docstring||'').substring(0,50))+'</td></tr>';
        });
        html += '</table>';
    });
    html += '</div>';
    container.innerHTML = html;
}

/* ============================== TOOLTIP ============================== */
function showTip(el, event) {
    const tip = document.getElementById('tooltip');
    const name = el.getAttribute('data-name') || '';
    // Try to find docstring from symbols data
    let text = name;
    const syms = graphData._symbols || {};
    const allFns = (syms.functions || []).concat(
        (syms.classes || []).flatMap(c => (c.methods || []).map(m => ({...m, name: c.name+'.'+m.name})))
    );
    const match = allFns.find(f => f.name === name);
    if (match && match.docstring) {
        text = name + '\\n\\n' + match.docstring;
    }
    tip.textContent = text;
    tip.style.display = 'block';
    tip.style.left = (event.clientX + 12) + 'px';
    tip.style.top = (event.clientY + 12) + 'px';
}
function hideTip() { document.getElementById('tooltip').style.display = 'none'; }

/* ============================== UTILS ============================== */
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function jumpTo(line) { vscode.postMessage({ command: 'jumpToLine', line }); }
function nodeClick(name) {
    // コールツリーでクリック→関数選択に反映
    if (graphType === 'calltree') {
        const sel = document.getElementById('funcSelect');
        sel.value = name;
        render();
    }
}

/* ============================== EXPORT ============================== */
function handleExport() {
    const format = document.getElementById('exportFormat').value;
    const graphDiv = document.getElementById('graphContainer');
    const funcName = document.getElementById('funcSelect').value;
    let content = '';

    if (format === 'svg') {
        const svgEl = document.getElementById('svgCanvas');
        content = svgEl ? svgEl.outerHTML : graphDiv.innerHTML;
    } else if (format === 'png') {
        // SVG to PNG via canvas
        const svgEl = document.getElementById('svgCanvas');
        if (svgEl) {
            const svgData = new XMLSerializer().serializeToString(svgEl);
            content = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)));
        }
    } else if (format === 'json') {
        content = JSON.stringify(graphData, null, 2);
    } else if (format === 'mermaid') {
        content = genMermaid();
    } else if (format === 'dot') {
        content = genDot();
    } else if (format === 'plantuml') {
        content = genPlantUML();
    } else if (format === 'html') {
        content = document.documentElement.outerHTML;
    }

    vscode.postMessage({ command: 'export', format, data: content, graphType, funcName });
}

function genMermaid() {
    if (graphType === 'calltree') {
        let md = 'graph LR\\n';
        (graphData.calls || []).forEach(([u, v]) => { md += '    ' + u.replace(/\\./g,'_') + ' --> ' + v.replace(/\\./g,'_') + '\\n'; });
        return md;
    }
    if (graphType === 'flowchart') {
        const fn = document.getElementById('funcSelect').value;
        const cfg = (graphData.functions || {})[fn];
        if (!cfg) return '';
        let md = 'flowchart TD\\n';
        (cfg.nodes || []).forEach(n => {
            const shapes = { start: '(['+n.label+'])', end: '(['+n.label+'])', decision: '{'+n.label+'}', process: '['+n.label+']' };
            md += '    ' + n.id + (shapes[n.type] || '['+n.label+']') + '\\n';
        });
        (cfg.edges || []).forEach(e => {
            const lbl = e.label ? '|'+e.label+'|' : '';
            md += '    ' + e.from + ' -->' + lbl + ' ' + e.to + '\\n';
        });
        return md;
    }
    if (graphType === 'classdiagram') {
        let md = 'classDiagram\\n';
        Object.entries(graphData.classes || {}).forEach(([name, info]) => {
            md += '    class ' + name + ' {\\n';
            (info.attributes || []).forEach(a => { md += '        ' + a.name + '\\n'; });
            (info.methods || []).forEach(m => { md += '        ' + m.name + '()\\n'; });
            md += '    }\\n';
            (info.bases || []).forEach(b => { md += '    ' + b + ' <|-- ' + name + '\\n'; });
        });
        return md;
    }
    return '';
}

function genDot() {
    if (graphType === 'calltree') {
        let dot = 'digraph calltree {\\n    rankdir=LR;\\n';
        (graphData.functions || []).forEach(f => { dot += '    "'+f+'" [shape=box];\\n'; });
        (graphData.calls || []).forEach(([u,v]) => { dot += '    "'+u+'" -> "'+v+'";\\n'; });
        return dot + '}\\n';
    }
    if (graphType === 'flowchart') {
        const fn = document.getElementById('funcSelect').value;
        const cfg = (graphData.functions || {})[fn];
        if (!cfg) return '';
        let dot = 'digraph flowchart {\\n';
        const shapes = { start:'ellipse', end:'ellipse', process:'box', decision:'diamond', loop_start:'trapezium', loop_end:'invtrapezium', io:'parallelogram', return:'ellipse' };
        (cfg.nodes || []).forEach(n => { dot += '    "'+n.id+'" [label="'+n.label.replace(/"/g,'\\\\"')+'" shape='+(shapes[n.type]||'box')+'];\\n'; });
        (cfg.edges || []).forEach(e => { const lbl = e.label ? ' [label="'+e.label+'"]' : ''; dot += '    "'+e.from+'" -> "'+e.to+'"'+lbl+';\\n'; });
        return dot + '}\\n';
    }
    return '';
}

function genPlantUML() {
    if (graphType === 'classdiagram') {
        let uml = '@startuml\\n';
        Object.entries(graphData.classes || {}).forEach(([name, info]) => {
            uml += 'class ' + name + ' {\\n';
            (info.attributes || []).forEach(a => { uml += '    ' + a.name + (a.type ? ' : '+a.type : '') + '\\n'; });
            (info.methods || []).forEach(m => { uml += '    ' + m.name + '(' + (m.params||'') + ')' + (m.returns ? ' : '+m.returns : '') + '\\n'; });
            uml += '}\\n';
            (info.bases || []).forEach(b => { uml += b + ' <|-- ' + name + '\\n'; });
        });
        return uml + '@enduml\\n';
    }
    if (graphType === 'calltree') {
        let uml = '@startuml\\n';
        (graphData.calls || []).forEach(([u,v]) => { uml += '"'+u+'" --> "'+v+'"\\n'; });
        return uml + '@enduml\\n';
    }
    return '';
}

init();
</script>
</body>
</html>`;
    }

    private async _handleExport(format: string, data: string, graphType: string, funcName: string) {
        const typeNames: { [key: string]: string } = {
            calltree: 'call_tree', flowchart: 'flowchart', dfd: 'dfd', classdiagram: 'class_diagram', symbols: 'symbols'
        };
        const baseName = typeNames[graphType] || 'graph';
        const suffix = funcName && funcName !== '__all__' ? '_' + funcName.replace(/\./g, '_') : '';
        const defaultName = baseName + suffix;

        const extMap: { [key: string]: string[] } = {
            svg: ['svg'], png: ['png'], json: ['json'],
            mermaid: ['md'], dot: ['dot'], plantuml: ['puml'], html: ['html'],
        };
        const ext = extMap[format] || ['txt'];

        const uri = await vscode.window.showSaveDialog({
            defaultUri: vscode.Uri.file(defaultName + '.' + ext[0]),
            filters: { [format.toUpperCase()]: ext },
        });
        if (uri) {
            const content = Buffer.from(data, 'utf-8');
            await vscode.workspace.fs.writeFile(uri, content);
            vscode.window.showInformationMessage(`保存しました: ${uri.fsPath}`);
        }
    }

    private async _jumpToLine(file: string, line: number) {
        const editor = vscode.window.activeTextEditor;
        if (editor && line > 0) {
            const pos = new vscode.Position(line - 1, 0);
            editor.selection = new vscode.Selection(pos, pos);
            editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
        }
    }
}
