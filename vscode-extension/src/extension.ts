import * as vscode from 'vscode';
import { PythonBridge } from './backend/PythonBridge';
import { GraphPanel } from './panels/GraphPanel';
import { AnalysisPanel } from './panels/AnalysisPanel';
import { OrionSymbolProvider } from './providers/SymbolProvider';
import { OrionHoverProvider } from './providers/HoverProvider';
import { SymbolTreeProvider } from './providers/TreeView';
import { ActionTreeProvider } from './providers/ActionTreeView';

let bridge: PythonBridge;
let symbolTree: SymbolTreeProvider;
let actionTree: ActionTreeProvider;

export function activate(context: vscode.ExtensionContext) {
    bridge = new PythonBridge();
    symbolTree = new SymbolTreeProvider(bridge);
    actionTree = new ActionTreeProvider();

    // Sidebar views
    vscode.window.registerTreeDataProvider('orionparser.actions', actionTree);
    vscode.window.registerTreeDataProvider('orionparser.symbols', symbolTree);

    // Document Symbol Provider (Outline / Ctrl+Shift+O)
    context.subscriptions.push(
        vscode.languages.registerDocumentSymbolProvider(
            { language: 'python' }, new OrionSymbolProvider(bridge)
        )
    );

    // Hover Provider (docstring)
    context.subscriptions.push(
        vscode.languages.registerHoverProvider(
            { language: 'python' }, new OrionHoverProvider(bridge)
        )
    );

    // ========== Sidebar action commands ==========
    context.subscriptions.push(
        vscode.commands.registerCommand('orionparser.action.selectFile', async () => {
            const uris = await vscode.window.showOpenDialog({
                canSelectFiles: true,
                canSelectFolders: false,
                canSelectMany: false,
                filters: { 'Python': ['py'] },
                openLabel: 'Select Python File',
            });
            if (uris && uris.length > 0) {
                actionTree.setTarget(uris[0].fsPath, 'file');
                // Also open the file in editor
                await vscode.window.showTextDocument(uris[0]);
                symbolTree.refresh(uris[0].fsPath);
            }
        }),
        vscode.commands.registerCommand('orionparser.action.selectFolder', async () => {
            const uris = await vscode.window.showOpenDialog({
                canSelectFiles: false,
                canSelectFolders: true,
                canSelectMany: false,
                openLabel: 'Select Folder',
            });
            if (uris && uris.length > 0) {
                actionTree.setTarget(uris[0].fsPath, 'folder');
            }
        }),
        vscode.commands.registerCommand('orionparser.action.useActiveEditor', () => {
            const editor = vscode.window.activeTextEditor;
            if (editor) {
                actionTree.setTarget(editor.document.uri.fsPath, 'file');
                symbolTree.refresh(editor.document.uri.fsPath);
            } else {
                vscode.window.showWarningMessage('No active editor');
            }
        }),
        vscode.commands.registerCommand('orionparser.action.currentTarget', () => {
            if (actionTree.targetPath) {
                vscode.window.showInformationMessage(`Target: ${actionTree.targetPath}`);
            }
        }),
        // --- Analysis action commands ---
        vscode.commands.registerCommand('orionparser.action.runCallTree', () =>
            runAnalysisFromSidebar(context, 'calltree')),
        vscode.commands.registerCommand('orionparser.action.runFlowchart', () =>
            runAnalysisFromSidebar(context, 'flowchart')),
        vscode.commands.registerCommand('orionparser.action.runDFD', () =>
            runAnalysisFromSidebar(context, 'dfd')),
        vscode.commands.registerCommand('orionparser.action.runClassDiagram', () =>
            runAnalysisFromSidebar(context, 'classdiagram')),
        vscode.commands.registerCommand('orionparser.action.runSymbols', () =>
            runAnalysisFromSidebar(context, 'symbols')),
        vscode.commands.registerCommand('orionparser.action.runTokens', () =>
            runAnalysisFromSidebar(context, 'tokens')),
        vscode.commands.registerCommand('orionparser.action.runAST', () =>
            runAnalysisFromSidebar(context, 'ast')),
    );

    // ========== Original commands (right-click, palette, shortcuts) ==========
    context.subscriptions.push(
        vscode.commands.registerCommand('orionparser.analyzeFile', () => cmdAnalyzeFile(context)),
        vscode.commands.registerCommand('orionparser.showSymbols', () => cmdShowGraph(context, 'symbols')),
        vscode.commands.registerCommand('orionparser.showCallTree', () => cmdShowGraph(context, 'calltree')),
        vscode.commands.registerCommand('orionparser.showFlowchart', () => cmdShowGraph(context, 'flowchart')),
        vscode.commands.registerCommand('orionparser.showDFD', () => cmdShowGraph(context, 'dfd')),
        vscode.commands.registerCommand('orionparser.showClassDiagram', () => cmdShowGraph(context, 'classdiagram')),
        vscode.commands.registerCommand('orionparser.showTokens', () => cmdShowCodeAnalysis(context, 'tokens')),
        vscode.commands.registerCommand('orionparser.showAST', () => cmdShowCodeAnalysis(context, 'ast')),
        vscode.commands.registerCommand('orionparser.analyzeFolder', () => cmdAnalyzeFolder(context)),
        vscode.commands.registerCommand('orionparser.exportGraph', () => cmdExportGraph()),
    );

    // Track active editor changes
    vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (editor && editor.document.languageId === 'python') {
            symbolTree.refresh(editor.document.uri.fsPath);
        }
    }, null, context.subscriptions);

    // Initial symbol tree
    const activeEditor = vscode.window.activeTextEditor;
    if (activeEditor && activeEditor.document.languageId === 'python') {
        symbolTree.refresh(activeEditor.document.uri.fsPath);
        actionTree.setTarget(activeEditor.document.uri.fsPath, 'file');
    }

    // Status bar
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(symbol-structure) OrionParser';
    statusBar.tooltip = 'OrionParser: Analyze File';
    statusBar.command = 'orionparser.analyzeFile';
    statusBar.show();
    context.subscriptions.push(statusBar);
}

export function deactivate() {}

// ============================================================
// Sidebar analysis runner
// ============================================================

async function runAnalysisFromSidebar(context: vscode.ExtensionContext, type: string) {
    const targetPath = actionTree.targetPath;

    if (!targetPath) {
        // No target set — prompt for file/folder
        const choice = await vscode.window.showQuickPick([
            { label: '$(file-add) Open File...', value: 'file' },
            { label: '$(folder-opened) Open Folder...', value: 'folder' },
            { label: '$(file-code) Use Active Editor', value: 'active' },
        ], { placeHolder: 'Select a target first' });

        if (!choice) { return; }

        if (choice.value === 'file') {
            await vscode.commands.executeCommand('orionparser.action.selectFile');
        } else if (choice.value === 'folder') {
            await vscode.commands.executeCommand('orionparser.action.selectFolder');
        } else {
            await vscode.commands.executeCommand('orionparser.action.useActiveEditor');
        }

        // Re-check after selection
        if (!actionTree.targetPath) { return; }
        return runAnalysisFromSidebar(context, type);
    }

    const isFolder = actionTree.targetType === 'folder';

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `OrionParser: ${type} ...` },
        async () => {
            try {
                if (type === 'tokens' || type === 'ast') {
                    if (isFolder) {
                        vscode.window.showWarningMessage('Tokens/AST requires a file, not a folder');
                        return;
                    }
                    const data = type === 'tokens'
                        ? await bridge.getTokens(targetPath)
                        : await bridge.analyzeAll(targetPath);
                    AnalysisPanel.createOrShow(context.extensionUri, type, data, type);
                } else {
                    await showGraphForPath(context, targetPath, type, isFolder);
                }
            } catch (e: any) {
                vscode.window.showErrorMessage(`Error: ${e.message}`);
            }
        }
    );
}

// ============================================================
// Graph rendering for any path (file or folder)
// ============================================================

async function showGraphForPath(
    context: vscode.ExtensionContext,
    filePath: string,
    graphType: string,
    isFolder: boolean
) {
    const titles: Record<string, string> = {
        symbols: 'Symbols', calltree: 'Call Tree', flowchart: 'Flowchart',
        dfd: 'DFD', classdiagram: 'Class Diagram',
    };

    if (isFolder) {
        // Folder: only calltree is supported for directory
        if (graphType !== 'calltree') {
            vscode.window.showWarningMessage(`Folder analysis: only Call Tree is supported. Running Call Tree.`);
            graphType = 'calltree';
        }
        const data = await bridge.getCallTree(filePath);
        GraphPanel.createOrShow(context.extensionUri, 'Call Tree (Folder)', data, 'calltree');
        return;
    }

    let data: any;
    switch (graphType) {
        case 'symbols': data = await bridge.getSymbols(filePath); break;
        case 'calltree': {
            const [ct, sym] = await Promise.all([
                bridge.getCallTree(filePath), bridge.getSymbols(filePath)
            ]);
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

// ============================================================
// Original command handlers (palette, right-click, shortcuts)
// ============================================================

async function cmdAnalyzeFile(context: vscode.ExtensionContext) {
    // If no active editor, offer file selection
    let filePath: string;
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        filePath = editor.document.uri.fsPath;
        actionTree.setTarget(filePath, 'file');
    } else {
        const uris = await vscode.window.showOpenDialog({
            canSelectFiles: true, canSelectFolders: false, canSelectMany: false,
            filters: { 'Python': ['py'] }, openLabel: 'Select Python File',
        });
        if (!uris || uris.length === 0) { return; }
        filePath = uris[0].fsPath;
        actionTree.setTarget(filePath, 'file');
        await vscode.window.showTextDocument(uris[0]);
    }

    const pick = await vscode.window.showQuickPick([
        { label: '$(symbol-method) Symbols', value: 'symbols' },
        { label: '$(type-hierarchy) Call Tree', value: 'calltree' },
        { label: '$(workflow) Flowchart', value: 'flowchart' },
        { label: '$(git-merge) DFD', value: 'dfd' },
        { label: '$(symbol-class) Class Diagram', value: 'classdiagram' },
        { label: '$(list-flat) Tokens', value: 'tokens' },
        { label: '$(list-tree) AST', value: 'ast' },
        { label: '$(search) All', value: 'all' },
    ], { placeHolder: 'Select analysis type' });

    if (!pick) { return; }

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `OrionParser: ${pick.value} ...` },
        async () => {
            try {
                if (pick.value === 'tokens' || pick.value === 'ast') {
                    const data = pick.value === 'tokens'
                        ? await bridge.getTokens(filePath)
                        : await bridge.analyzeAll(filePath);
                    AnalysisPanel.createOrShow(context.extensionUri, pick.value, data, pick.value);
                } else if (pick.value === 'all') {
                    const data = await bridge.analyzeAll(filePath);
                    GraphPanel.createOrShow(context.extensionUri, 'Symbols', data, 'symbols');
                } else {
                    await showGraphForPath(context, filePath, pick.value, false);
                }
            } catch (e: any) {
                vscode.window.showErrorMessage(`Error: ${e.message}`);
            }
        }
    );
}

async function cmdShowGraph(context: vscode.ExtensionContext, graphType: string) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        // Offer file selection instead of just warning
        await vscode.commands.executeCommand('orionparser.action.selectFile');
        if (!actionTree.targetPath) { return; }
        return runAnalysisFromSidebar(context, graphType);
    }

    const filePath = editor.document.uri.fsPath;
    actionTree.setTarget(filePath, 'file');

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `OrionParser: ${graphType} ...` },
        async () => {
            try {
                await showGraphForPath(context, filePath, graphType, false);
            } catch (e: any) {
                vscode.window.showErrorMessage(`Error: ${e.message}`);
            }
        }
    );
}

async function cmdShowCodeAnalysis(context: vscode.ExtensionContext, viewType: string) {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        await vscode.commands.executeCommand('orionparser.action.selectFile');
        if (!actionTree.targetPath) { return; }
        return runAnalysisFromSidebar(context, viewType);
    }

    const filePath = editor.document.uri.fsPath;
    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `OrionParser: ${viewType} ...` },
        async () => {
            try {
                const data = viewType === 'tokens'
                    ? await bridge.getTokens(filePath)
                    : await bridge.analyzeAll(filePath);
                AnalysisPanel.createOrShow(context.extensionUri, viewType, data, viewType);
            } catch (e: any) {
                vscode.window.showErrorMessage(`Error: ${e.message}`);
            }
        }
    );
}

async function cmdAnalyzeFolder(context: vscode.ExtensionContext) {
    const folderUri = await vscode.window.showOpenDialog({
        canSelectFolders: true, canSelectFiles: false, canSelectMany: false,
        openLabel: 'Select Folder',
    });
    if (!folderUri || folderUri.length === 0) { return; }
    const folderPath = folderUri[0].fsPath;
    actionTree.setTarget(folderPath, 'folder');

    await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'OrionParser: Folder analysis ...' },
        async () => {
            try {
                const data = await bridge.getCallTree(folderPath);
                GraphPanel.createOrShow(context.extensionUri, 'Call Tree (Folder)', data, 'calltree');
            } catch (e: any) {
                vscode.window.showErrorMessage(`Error: ${e.message}`);
            }
        }
    );
}

async function cmdExportGraph() {
    if (!GraphPanel.currentPanel) {
        vscode.window.showWarningMessage('No graph panel is open');
        return;
    }
    vscode.window.showInformationMessage('Use the Save button in the graph panel');
}
