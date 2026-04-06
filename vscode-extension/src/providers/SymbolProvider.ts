import * as vscode from 'vscode';
import { PythonBridge } from '../backend/PythonBridge';

export class OrionSymbolProvider implements vscode.DocumentSymbolProvider {
    constructor(private bridge: PythonBridge) {}

    async provideDocumentSymbols(
        document: vscode.TextDocument,
        _token: vscode.CancellationToken
    ): Promise<vscode.DocumentSymbol[]> {
        if (document.languageId !== 'python') { return []; }

        try {
            const result = await this.bridge.getSymbols(document.uri.fsPath);
            if (!result.symbols) { return []; }
            return this._buildSymbols(result.symbols, document);
        } catch {
            return [];
        }
    }

    private _buildSymbols(symbols: any, document: vscode.TextDocument): vscode.DocumentSymbol[] {
        const out: vscode.DocumentSymbol[] = [];

        for (const fn of symbols.functions || []) {
            const line = Math.max(0, (fn.line || 1) - 1);
            const range = new vscode.Range(line, 0, line, 0);
            const sym = new vscode.DocumentSymbol(
                fn.name,
                fn.docstring || '',
                vscode.SymbolKind.Function,
                range, range
            );
            out.push(sym);
        }

        for (const cls of symbols.classes || []) {
            const line = Math.max(0, (cls.line || 1) - 1);
            const range = new vscode.Range(line, 0, line, 0);
            const sym = new vscode.DocumentSymbol(
                cls.name,
                cls.docstring || '',
                vscode.SymbolKind.Class,
                range, range
            );

            // メソッドを子要素に
            for (const method of cls.methods || []) {
                const mLine = Math.max(0, (method.line || 1) - 1);
                const mRange = new vscode.Range(mLine, 0, mLine, 0);
                sym.children.push(new vscode.DocumentSymbol(
                    method.name,
                    method.docstring || '',
                    vscode.SymbolKind.Method,
                    mRange, mRange
                ));
            }
            out.push(sym);
        }

        for (const v of symbols.variables || []) {
            const line = Math.max(0, (v.line || 1) - 1);
            const range = new vscode.Range(line, 0, line, 0);
            out.push(new vscode.DocumentSymbol(
                v.name, '',
                vscode.SymbolKind.Variable,
                range, range
            ));
        }

        for (const imp of symbols.imports || []) {
            const line = Math.max(0, (imp.line || 1) - 1);
            const range = new vscode.Range(line, 0, line, 0);
            out.push(new vscode.DocumentSymbol(
                imp.name, imp.source || '',
                vscode.SymbolKind.Module,
                range, range
            ));
        }

        return out;
    }
}
