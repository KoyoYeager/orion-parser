import * as vscode from 'vscode';
import { PythonBridge } from '../backend/PythonBridge';

type SymbolItem = {
    name: string;
    kind: string;
    line: number;
    docstring?: string;
    children?: SymbolItem[];
};

export class SymbolTreeProvider implements vscode.TreeDataProvider<SymbolItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<SymbolItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private _symbols: SymbolItem[] = [];
    private _filePath: string = '';

    constructor(private bridge: PythonBridge) {}

    async refresh(filePath: string): Promise<void> {
        this._filePath = filePath;
        try {
            const result = await this.bridge.getSymbols(filePath);
            this._symbols = this._buildItems(result.symbols || {});
        } catch {
            this._symbols = [];
        }
        this._onDidChangeTreeData.fire(undefined);
    }

    getTreeItem(element: SymbolItem): vscode.TreeItem {
        const hasChildren = (element.children && element.children.length > 0);
        const item = new vscode.TreeItem(
            element.name,
            hasChildren
                ? vscode.TreeItemCollapsibleState.Expanded
                : vscode.TreeItemCollapsibleState.None
        );

        const icons: { [key: string]: string } = {
            function: 'symbol-method',
            class: 'symbol-class',
            variable: 'symbol-variable',
            import: 'symbol-namespace',
            method: 'symbol-method',
            attribute: 'symbol-field',
        };
        item.iconPath = new vscode.ThemeIcon(icons[element.kind] || 'symbol-misc');
        item.description = element.docstring ? element.docstring.substring(0, 40) : '';
        item.tooltip = element.docstring || element.name;

        if (element.line > 0 && this._filePath) {
            item.command = {
                command: 'vscode.open',
                title: 'ジャンプ',
                arguments: [
                    vscode.Uri.file(this._filePath),
                    { selection: new vscode.Range(element.line - 1, 0, element.line - 1, 0) }
                ]
            };
        }

        return item;
    }

    getChildren(element?: SymbolItem): SymbolItem[] {
        if (!element) { return this._symbols; }
        return element.children || [];
    }

    private _buildItems(symbols: any): SymbolItem[] {
        const items: SymbolItem[] = [];

        for (const cls of symbols.classes || []) {
            const children: SymbolItem[] = [];
            for (const attr of cls.attributes || []) {
                children.push({ name: attr.name, kind: 'attribute', line: attr.line || 0 });
            }
            for (const m of cls.methods || []) {
                children.push({
                    name: m.name, kind: 'method', line: m.line || 0,
                    docstring: m.docstring
                });
            }
            items.push({
                name: cls.name, kind: 'class', line: cls.line || 0,
                docstring: cls.docstring, children
            });
        }

        for (const fn of symbols.functions || []) {
            items.push({
                name: fn.name, kind: 'function', line: fn.line || 0,
                docstring: fn.docstring
            });
        }

        for (const v of symbols.variables || []) {
            items.push({ name: v.name, kind: 'variable', line: v.line || 0 });
        }

        for (const imp of symbols.imports || []) {
            items.push({ name: imp.name, kind: 'import', line: imp.line || 0 });
        }

        return items;
    }
}
