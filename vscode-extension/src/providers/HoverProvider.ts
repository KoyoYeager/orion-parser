import * as vscode from 'vscode';
import { PythonBridge } from '../backend/PythonBridge';

export class OrionHoverProvider implements vscode.HoverProvider {
    private _cache: Map<string, any> = new Map();

    constructor(private bridge: PythonBridge) {}

    async provideHover(
        document: vscode.TextDocument,
        position: vscode.Position,
        _token: vscode.CancellationToken
    ): Promise<vscode.Hover | undefined> {
        if (document.languageId !== 'python') { return; }

        const wordRange = document.getWordRangeAtPosition(position);
        if (!wordRange) { return; }
        const word = document.getText(wordRange);

        try {
            const symbols = await this._getSymbols(document.uri.fsPath);
            if (!symbols) { return; }

            // 関数のdocstring
            for (const fn of symbols.functions || []) {
                if (fn.name === word && fn.docstring) {
                    return new vscode.Hover(
                        new vscode.MarkdownString(`**${fn.name}**\n\n${fn.docstring}`),
                        wordRange
                    );
                }
            }

            // クラスのdocstring
            for (const cls of symbols.classes || []) {
                if (cls.name === word && cls.docstring) {
                    return new vscode.Hover(
                        new vscode.MarkdownString(`**class ${cls.name}**\n\n${cls.docstring}`),
                        wordRange
                    );
                }
                // メソッド
                for (const m of cls.methods || []) {
                    if (m.name === word && m.docstring) {
                        return new vscode.Hover(
                            new vscode.MarkdownString(`**${cls.name}.${m.name}**\n\n${m.docstring}`),
                            wordRange
                        );
                    }
                }
            }
        } catch {
            // ignore
        }
    }

    private async _getSymbols(filePath: string): Promise<any> {
        if (this._cache.has(filePath)) {
            return this._cache.get(filePath);
        }
        const result = await this.bridge.getSymbols(filePath);
        if (result.symbols) {
            this._cache.set(filePath, result.symbols);
            // 30秒でキャッシュクリア
            setTimeout(() => this._cache.delete(filePath), 30000);
        }
        return result.symbols;
    }
}
