import * as vscode from 'vscode';

/**
 * コード解析パネル — トークン/AST表示用Webview
 */
export class AnalysisPanel {
    public static currentPanel: AnalysisPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private _disposables: vscode.Disposable[] = [];

    public static createOrShow(extensionUri: vscode.Uri, title: string, data: any, viewType: string) {
        const column = vscode.ViewColumn.Beside;

        if (AnalysisPanel.currentPanel) {
            AnalysisPanel.currentPanel._panel.reveal(column);
            AnalysisPanel.currentPanel._update(title, data, viewType);
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            'orionparserAnalysis', title, column,
            { enableScripts: true, retainContextWhenHidden: true }
        );

        AnalysisPanel.currentPanel = new AnalysisPanel(panel, title, data, viewType);
    }

    private constructor(panel: vscode.WebviewPanel, title: string, data: any, viewType: string) {
        this._panel = panel;
        this._update(title, data, viewType);
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

        this._panel.webview.onDidReceiveMessage(async (msg) => {
            if (msg.command === 'jumpToLine') {
                const editor = vscode.window.activeTextEditor;
                if (editor && msg.line > 0) {
                    const pos = new vscode.Position(msg.line - 1, msg.col || 0);
                    editor.selection = new vscode.Selection(pos, pos);
                    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
                }
            }
        }, null, this._disposables);
    }

    public dispose() {
        AnalysisPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) { const d = this._disposables.pop(); if (d) { d.dispose(); } }
    }

    private _update(title: string, data: any, viewType: string) {
        this._panel.title = `OrionParser: ${title}`;
        this._panel.webview.html = this._getHtml(data, viewType);
    }

    private _getHtml(data: any, viewType: string): string {
        const dataJson = JSON.stringify(data).replace(/</g, '\\u003c');
        return `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground);
    background: var(--vscode-editor-background); margin: 0; padding: 0; overflow: auto; }
.toolbar { display: flex; gap: 8px; padding: 6px 10px; align-items: center;
    border-bottom: 1px solid var(--vscode-panel-border); }
.toolbar input { padding: 3px 8px; border-radius: 3px; border: 1px solid var(--vscode-input-border);
    background: var(--vscode-input-background); color: var(--vscode-input-foreground); flex: 1; max-width: 300px; }
.tab-bar { display: flex; gap: 0; border-bottom: 1px solid var(--vscode-panel-border); }
.tab { padding: 6px 16px; cursor: pointer; border-bottom: 2px solid transparent; font-size: 12px; }
.tab:hover { background: var(--vscode-editor-selectionBackground); }
.tab.active { border-bottom-color: var(--vscode-focusBorder); font-weight: bold; }
#content { padding: 10px; overflow: auto; height: calc(100vh - 80px); }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { background: var(--vscode-editor-selectionBackground); padding: 5px 8px; text-align: left;
    position: sticky; top: 0; z-index: 1; }
td { padding: 3px 8px; border-bottom: 1px solid var(--vscode-panel-border); }
tr:hover { background: var(--vscode-editor-selectionBackground); cursor: pointer; }
.token-type { font-weight: bold; }
.tree-node { padding-left: 20px; }
.tree-toggle { cursor: pointer; user-select: none; }
.ast-key { color: var(--vscode-symbolIcon-propertyForeground, #9CDCFE); }
.ast-value { color: var(--vscode-symbolIcon-stringForeground, #CE9178); }
.highlight { background: rgba(255, 213, 79, 0.3); }
</style>
</head>
<body>
<div class="tab-bar">
    <div class="tab active" data-tab="tokens" onclick="switchTab('tokens')">トークン</div>
    <div class="tab" data-tab="ast" onclick="switchTab('ast')">AST</div>
</div>
<div class="toolbar">
    <input id="search" type="text" placeholder="検索..." oninput="filterContent()">
</div>
<div id="content"></div>

<script>
const vscode = acquireVsCodeApi();
const data = ${dataJson};
let currentTab = 'tokens';

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    renderTab();
}

function renderTab() {
    const content = document.getElementById('content');
    if (currentTab === 'tokens') renderTokens(content);
    else renderAST(content);
}

function renderTokens(container) {
    const tokens = data.tokens || [];
    const search = document.getElementById('search').value.toLowerCase();
    let html = '<table><tr><th>#</th><th>タイプ</th><th>値</th><th>行</th></tr>';
    tokens.forEach((t, i) => {
        const type = t.type || t[0] || '';
        const value = t.value || t[1] || '';
        const line = t.line || t[2] || 0;
        if (search && !type.toLowerCase().includes(search) && !String(value).toLowerCase().includes(search)) return;
        const typeClass = getTokenColor(type);
        html += '<tr onclick="jumpTo('+line+')"><td>'+(i+1)+'</td><td class="token-type" style="color:'+typeClass+'">'+esc(type)+'</td><td>'+esc(String(value))+'</td><td>'+line+'</td></tr>';
    });
    html += '</table>';
    container.innerHTML = html;
}

function getTokenColor(type) {
    const colors = {
        'KEYWORD': '#569CD6', 'NAME': '#9CDCFE', 'NUMBER': '#B5CEA8', 'STRING': '#CE9178',
        'OP': '#D4D4D4', 'NEWLINE': '#808080', 'INDENT': '#808080', 'DEDENT': '#808080',
        'COMMENT': '#6A9955', 'PUNCT': '#D4D4D4'
    };
    for (const [k, c] of Object.entries(colors)) {
        if (type.toUpperCase().includes(k)) return c;
    }
    return 'var(--vscode-foreground)';
}

function renderAST(container) {
    const ast = data.ast || data;
    container.innerHTML = '<div style="font-family:Consolas,monospace; font-size:12px; white-space:pre-wrap;">' + renderASTNode(ast, 0) + '</div>';
}

function renderASTNode(node, depth) {
    if (!node || typeof node !== 'object') return esc(String(node));
    if (Array.isArray(node)) {
        if (node.length === 0) return '[]';
        return '[\\n' + node.map((item, i) => pad(depth+1) + renderASTNode(item, depth+1)).join(',\\n') + '\\n' + pad(depth) + ']';
    }
    const entries = Object.entries(node);
    if (entries.length === 0) return '{}';
    let html = '{\\n';
    entries.forEach(([k, v], i) => {
        html += pad(depth+1) + '<span class="ast-key">"'+esc(k)+'"</span>: ';
        if (typeof v === 'string') html += '<span class="ast-value">"'+esc(v)+'"</span>';
        else if (typeof v === 'number' || typeof v === 'boolean' || v === null) html += '<span class="ast-value">'+esc(String(v))+'</span>';
        else html += renderASTNode(v, depth+1);
        if (i < entries.length - 1) html += ',';
        html += '\\n';
    });
    html += pad(depth) + '}';
    return html;
}

function pad(d) { return '  '.repeat(d); }
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function jumpTo(line) { vscode.postMessage({ command: 'jumpToLine', line }); }
function filterContent() { renderTab(); }

renderTab();
</script>
</body>
</html>`;
    }
}
