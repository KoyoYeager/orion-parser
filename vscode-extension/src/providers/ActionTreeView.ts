import * as vscode from 'vscode';

/**
 * Sidebar action panel — file/folder selection + analysis buttons.
 * Works like the GUI's left panel + toolbar.
 */

type ActionItem = {
    id: string;
    label: string;
    icon: string;
    description?: string;
    section: string;
};

export class ActionTreeProvider implements vscode.TreeDataProvider<ActionItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<ActionItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private _targetPath: string = '';
    private _targetType: 'file' | 'folder' | 'none' = 'none';

    get targetPath(): string { return this._targetPath; }
    get targetType(): string { return this._targetType; }

    setTarget(filePath: string, type: 'file' | 'folder') {
        this._targetPath = filePath;
        this._targetType = type;
        this._onDidChangeTreeData.fire(undefined);
    }

    clearTarget() {
        this._targetPath = '';
        this._targetType = 'none';
        this._onDidChangeTreeData.fire(undefined);
    }

    refresh() {
        this._onDidChangeTreeData.fire(undefined);
    }

    getTreeItem(element: ActionItem): vscode.TreeItem {
        const item = new vscode.TreeItem(element.label, vscode.TreeItemCollapsibleState.None);
        item.iconPath = new vscode.ThemeIcon(element.icon);
        item.description = element.description || '';
        item.command = {
            command: `orionparser.action.${element.id}`,
            title: element.label,
        };

        // Disable analysis items when no target
        if (element.section === 'analysis' && this._targetType === 'none') {
            item.description = '(select a file first)';
        }

        return item;
    }

    getChildren(element?: ActionItem): ActionItem[] {
        if (element) { return []; }

        const items: ActionItem[] = [];

        // --- Section: Target selection ---
        items.push({
            id: 'selectFile',
            label: 'Open File...',
            icon: 'file-add',
            description: '',
            section: 'select',
        });
        items.push({
            id: 'selectFolder',
            label: 'Open Folder...',
            icon: 'folder-opened',
            description: '',
            section: 'select',
        });
        items.push({
            id: 'useActiveEditor',
            label: 'Use Active Editor',
            icon: 'file-code',
            description: '',
            section: 'select',
        });

        // --- Current target ---
        if (this._targetPath) {
            const short = this._targetPath.length > 40
                ? '...' + this._targetPath.slice(-37)
                : this._targetPath;
            items.push({
                id: 'currentTarget',
                label: this._targetType === 'folder' ? `Folder: ${short}` : `File: ${short}`,
                icon: this._targetType === 'folder' ? 'folder' : 'file',
                description: '',
                section: 'target',
            });
        }

        // --- Section: Graph analysis ---
        items.push({
            id: 'runCallTree',
            label: 'Call Tree',
            icon: 'type-hierarchy',
            section: 'analysis',
        });
        items.push({
            id: 'runFlowchart',
            label: 'Flowchart',
            icon: 'workflow',
            section: 'analysis',
        });
        items.push({
            id: 'runDFD',
            label: 'DFD (Data Flow)',
            icon: 'git-merge',
            section: 'analysis',
        });
        items.push({
            id: 'runClassDiagram',
            label: 'Class Diagram',
            icon: 'symbol-class',
            section: 'analysis',
        });
        items.push({
            id: 'runSymbols',
            label: 'Symbols',
            icon: 'symbol-method',
            section: 'analysis',
        });

        // --- Section: Code analysis ---
        items.push({
            id: 'runTokens',
            label: 'Tokens',
            icon: 'list-flat',
            section: 'analysis',
        });
        items.push({
            id: 'runAST',
            label: 'AST',
            icon: 'list-tree',
            section: 'analysis',
        });

        return items;
    }
}
