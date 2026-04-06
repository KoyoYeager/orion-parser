import * as vscode from 'vscode';
import { PythonBridge } from './backend/PythonBridge';
import { GraphPanel } from './panels/GraphPanel';
import { AnalysisPanel } from './panels/AnalysisPanel';
import { OrionSymbolProvider } from './providers/SymbolProvider';
import { OrionHoverProvider } from './providers/HoverProvider';
import { SymbolTreeProvider } from './providers/TreeView';

let bridge: PythonBridge;
let symbolTree: SymbolTreeProvider;

export function activate(context: vscode.ExtensionContext) {
    bridge = new PythonBridge();
    symbolTree = new SymbolTreeProvider(bridge);

    // サイドバーツリービュー
    vscode.window.registerTreeDataProvider('orionparser.symbols', symbolTree);

    // Document Symbol Provider (アウトライン / Ctrl+Shift+O)
    const symbolProvider = new OrionSymbolProvider(bridge);
    context.subscriptions.push(
        vscode.languages.registerDocumentSymbolProvider(
            { language: 'python' }, symbolProvider
        )
    );

    // Hover Provider (docstring表示)
    const hoverProvider = new OrionHoverProvider(bridge);
    context.subscriptions.push(
        vscode.languages.registerHoverProvider(
            { language: 'python' }, hoverProvider
        )
    );

    // コマンド登録
    context.subscriptions.push(
        vscode.commands.registerCommand('orionparser.analyzeFile', () => cmdAnalyzeFile(context)),
        vscode.commands.registerCommand('orionparser.showSymbols', () => cmdShowGraph(context, 'symbols')),
        vscode.commands.registerCommand('orionparser.showCallTree', () => cmdShowGraph(context, 'calltree')),
        vscode.commands.registerCommand('orionparser.showFlowchart', () => cmdShowGraph(context, 'flowchart')),
        vscode.commands.registerCommand('orionparser.showDFD', () => cmdShowGraph(context, 'dfd')),
        vscode.commands.registerCommand('orionparser.showClassDiagram', () => cmdShowGraph(context, 'classdiagram')),
        vscode.commands.registerCommand('orionparser.showTokens', () => cmdShowAnalysis(context, 'tokens')),
        vscode.commands.registerCommand('orionparser.showAST', () => cmdShowAnalysis(context, 'ast')),
        vscode.commands.registerCommand('orionparser.analyzeFolder', () => cmdAnalyzeFolder(context)),
        vscode.commands.registerCommand('orionparser.exportGraph', () => cmdExportGraph())
    );

    // アクティブエディタ変更でツリー更新
    vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (editor && editor.document.languageId === 'python') {
            symbolTree.refresh(editor.document.uri.fsPath);
        }
    }, null, context.subscriptions);

    // 初回: 現在のエディタでツリー更新
    const activeEditor = vscode.window.activeTextEditor;
    if (activeEditor && activeEditor.document.languageId === 'python') {
        symbolTree.refresh(activeEditor.document.uri.fsPath);
    }

    // ステータスバー
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(symbol-structure) OrionParser';
    statusBar.tooltip = 'OrionParser: ファイルを解析';
    statusBar.command = 'orionparser.analyzeFile';
    statusBar.show();
    context.subscriptions.push(statusBar);

    vscode.window.showInformationMessage('OrionParser が有効化されました');
}

export function deactivate() {}

// === コマンド実装 ===

async function cmdAnalyzeFile(context: vscode.ExtensionContext) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('ファイルを開いてください');
        return;
    }
    const filePath = editor.document.uri.fsPath;

    const pick = await vscode.window.showQuickPick([
        { label: 'シンボル一覧', value: 'symbols' },
        { label: 'コールツリー', value: 'calltree' },
        { label: 'フローチャート', value: 'flowchart' },
        { label: 'DFD', value: 'dfd' },
        { label: 'クラス図', value: 'classdiagram' },
        { label: 'トークン', value: 'tokens' },
        { label: 'AST', value: 'ast' },
        { label: '全解析', value: 'all' },
    ], { placeHolder: '解析タイプを選択' });

    if (!pick) { return; }

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'OrionParser 解析中...' },
        async () => {
            try {
                if (pick.value === 'tokens' || pick.value === 'ast') {
                    await cmdShowAnalysis(context, pick.value);
                } else if (pick.value === 'all') {
                    const data = await bridge.analyzeAll(filePath);
                    GraphPanel.createOrShow(context.extensionUri, 'シンボル一覧', data, 'symbols');
                } else {
                    await showGraphForType(context, filePath, pick.value);
                }
            } catch (e: any) {
                vscode.window.showErrorMessage(`解析エラー: ${e.message}`);
            }
        }
    );
}

async function cmdShowGraph(context: vscode.ExtensionContext, graphType: string) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('ファイルを開いてください');
        return;
    }
    const filePath = editor.document.uri.fsPath;

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `OrionParser: ${graphType} 解析中...` },
        async () => {
            try {
                await showGraphForType(context, filePath, graphType);
            } catch (e: any) {
                vscode.window.showErrorMessage(`解析エラー: ${e.message}`);
            }
        }
    );
}

async function showGraphForType(context: vscode.ExtensionContext, filePath: string, graphType: string) {
    const titles: { [key: string]: string } = {
        symbols: 'シンボル一覧',
        calltree: 'コールツリー',
        flowchart: 'フローチャート',
        dfd: 'DFD',
        classdiagram: 'クラス図',
    };

    let data: any;
    switch (graphType) {
        case 'symbols': data = await bridge.getSymbols(filePath); break;
        case 'calltree': {
            const [ct, sym] = await Promise.all([bridge.getCallTree(filePath), bridge.getSymbols(filePath)]);
            data = { ...ct, _symbols: sym.symbols || {} };
            break;
        }
        case 'flowchart': data = await bridge.getFlowchart(filePath); break;
        case 'dfd': data = await bridge.getDFD(filePath); break;
        case 'classdiagram': data = await bridge.getClassDiagram(filePath); break;
        default: return;
    }

    GraphPanel.createOrShow(context.extensionUri, titles[graphType] || graphType, data, graphType);
}

async function cmdShowAnalysis(context: vscode.ExtensionContext, viewType: string) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('ファイルを開いてください');
        return;
    }
    const filePath = editor.document.uri.fsPath;
    const titles: { [key: string]: string } = { tokens: 'トークン', ast: 'AST' };

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `OrionParser: ${titles[viewType]} 解析中...` },
        async () => {
            try {
                const data = viewType === 'tokens'
                    ? await bridge.getTokens(filePath)
                    : await bridge.analyzeAll(filePath);
                AnalysisPanel.createOrShow(context.extensionUri, titles[viewType] || viewType, data, viewType);
            } catch (e: any) {
                vscode.window.showErrorMessage(`解析エラー: ${e.message}`);
            }
        }
    );
}

async function cmdAnalyzeFolder(context: vscode.ExtensionContext) {
    const folderUri = await vscode.window.showOpenDialog({
        canSelectFolders: true,
        canSelectFiles: false,
        canSelectMany: false,
        openLabel: 'フォルダを選択',
    });
    if (!folderUri || folderUri.length === 0) { return; }
    const folderPath = folderUri[0].fsPath;

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'OrionParser: フォルダ解析中...' },
        async () => {
            try {
                const data = await bridge.getCallTree(folderPath);
                GraphPanel.createOrShow(context.extensionUri, 'コールツリー (フォルダ)', data, 'calltree');
            } catch (e: any) {
                vscode.window.showErrorMessage(`解析エラー: ${e.message}`);
            }
        }
    );
}

async function cmdExportGraph() {
    if (!GraphPanel.currentPanel) {
        vscode.window.showWarningMessage('グラフパネルが開かれていません');
        return;
    }
    vscode.window.showInformationMessage('グラフパネル内の保存ボタンを使用してください');
}
