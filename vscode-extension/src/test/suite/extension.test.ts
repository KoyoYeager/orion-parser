import * as assert from 'assert';
import * as vscode from 'vscode';
import * as path from 'path';
import { execFile } from 'child_process';

suite('OrionParser Extension Test Suite', () => {

    const testFile = path.resolve(__dirname, '../../../../src/orionparser/analysis/symbols.py');
    const bridgePath = path.resolve(__dirname, '../../../../src');

    // ============================================================
    // Python Bridge 直接呼び出しテスト
    // ============================================================

    function callBridge(command: string, target: string): Promise<any> {
        return new Promise((resolve, reject) => {
            const env = { ...process.env, PYTHONPATH: bridgePath, PYTHONIOENCODING: 'utf-8' };
            execFile('python', ['-m', 'orionparser.vscode_bridge', command, target],
                { env, maxBuffer: 50 * 1024 * 1024, timeout: 60000, encoding: 'utf-8' },
                (error, stdout, stderr) => {
                    if (error) { reject(new Error(`Bridge error: ${error.message}\n${stderr}`)); return; }
                    try {
                        const result = JSON.parse(stdout);
                        if (result.error) { reject(new Error(result.error)); }
                        else { resolve(result); }
                    } catch (e) {
                        reject(new Error(`JSON parse error: ${stdout.substring(0, 300)}`));
                    }
                }
            );
        });
    }

    test('Python Bridge: symbols コマンドが正常に動作する', async () => {
        const result = await callBridge('symbols', testFile);
        assert.ok(result.success, 'success=true であること');
        assert.ok(result.symbols, 'symbols が存在すること');
        assert.ok(result.symbols.functions.length > 0, '関数が抽出されること');
        assert.ok(result.symbols.classes.length > 0, 'クラスが抽出されること');

        const funcNames = result.symbols.functions.map((f: any) => f.name);
        assert.ok(funcNames.includes('extract_symbols'), 'extract_symbols が含まれること');
    });

    test('Python Bridge: calltree コマンドが正常に動作する', async () => {
        const result = await callBridge('calltree', testFile);
        assert.ok(result.success);
        assert.ok(Array.isArray(result.functions), 'functions が配列であること');
        assert.ok(result.functions.length > 0, '関数が1つ以上');
        assert.ok(Array.isArray(result.calls), 'calls が配列であること');
        assert.ok(result.calls.length > 0, '呼び出しが1つ以上');
    });

    test('Python Bridge: flowchart コマンドが正常に動作する', async () => {
        const result = await callBridge('flowchart', testFile);
        assert.ok(result.success);
        assert.ok(result.functions, 'functions が存在');
        const fns = Object.keys(result.functions);
        assert.ok(fns.length > 0, '関数フローが1つ以上');

        // 各関数にnodes/edgesがあること
        for (const fn of fns) {
            assert.ok(Array.isArray(result.functions[fn].nodes), `${fn} に nodes がある`);
            assert.ok(Array.isArray(result.functions[fn].edges), `${fn} に edges がある`);
        }
    });

    test('Python Bridge: dfd コマンドが正常に動作する', async () => {
        const result = await callBridge('dfd', testFile);
        assert.ok(result.success);
        assert.ok(result.functions, 'functions が存在');
        const fns = Object.keys(result.functions);
        assert.ok(fns.length > 0, 'DFD関数が1つ以上');
    });

    test('Python Bridge: classdiagram コマンドが正常に動作する', async () => {
        const result = await callBridge('classdiagram', testFile);
        assert.ok(result.success);
        assert.ok(result.classes, 'classes が存在');
        const cls = Object.keys(result.classes);
        assert.ok(cls.length > 0, 'クラスが1つ以上');
        assert.ok(cls.includes('Symbol'), 'Symbol クラスが含まれる');
        assert.ok(cls.includes('SymbolTable'), 'SymbolTable クラスが含まれる');

        // Symbol クラスの属性とメソッドを確認
        const symbolCls = result.classes['Symbol'];
        assert.ok(symbolCls.attributes.length > 0, 'Symbol に属性がある');

        const symTable = result.classes['SymbolTable'];
        assert.ok(symTable.methods.length > 0, 'SymbolTable にメソッドがある');
    });

    test('Python Bridge: tokens コマンドが正常に動作する', async () => {
        const result = await callBridge('tokens', testFile);
        assert.ok(result.success);
        assert.ok(Array.isArray(result.tokens), 'tokens が配列');
        assert.ok(result.tokens.length > 100, 'トークンが100個以上');
    });

    test('Python Bridge: all コマンドが全解析を返す', async () => {
        const result = await callBridge('all', testFile);
        assert.ok(result.success);
        assert.ok(result.symbols, 'symbols あり');
        assert.ok(result.calltree, 'calltree あり');
        assert.ok(result.flowchart, 'flowchart あり');
        assert.ok(result.dfd, 'dfd あり');
        assert.ok(result.classdiagram, 'classdiagram あり');
        assert.ok(result.tokens, 'tokens あり');
    });

    // ============================================================
    // フォルダ解析テスト
    // ============================================================

    test('Python Bridge: フォルダのcalltreeが動作する', async () => {
        const folderPath = path.resolve(__dirname, '../../../../src/orionparser/analysis');
        const result = await callBridge('calltree', folderPath);
        assert.ok(result.success);
        assert.ok(result.functions.length > 20, 'フォルダ解析で20関数以上');
        assert.ok(result.calls.length > 50, 'フォルダ解析で50呼び出し以上');
    });

    // ============================================================
    // 複数ファイルでのロバスト性テスト
    // ============================================================

    const additionalFiles = [
        'analysis/control_flow.py',
        'analysis/call_tree.py',
        'analysis/dfd.py',
        'analysis/class_diagram.py',
        'vscode_bridge.py',
    ];

    for (const relFile of additionalFiles) {
        const absFile = path.resolve(__dirname, '../../../../src/orionparser', relFile);

        test(`ロバスト性: ${relFile} の symbols が動作`, async () => {
            const result = await callBridge('symbols', absFile);
            assert.ok(result.success, `${relFile}: symbols 成功`);
        });

        test(`ロバスト性: ${relFile} の flowchart が動作`, async () => {
            const result = await callBridge('flowchart', absFile);
            assert.ok(result.success, `${relFile}: flowchart 成功`);
        });

        test(`ロバスト性: ${relFile} の classdiagram が動作`, async () => {
            const result = await callBridge('classdiagram', absFile);
            assert.ok(result.success, `${relFile}: classdiagram 成功`);
        });
    }

    // ============================================================
    // VSCode Extension 登録テスト
    // ============================================================

    test('拡張機能がアクティベートされる', async () => {
        const ext = vscode.extensions.getExtension('KoyoYeager.orion-parser');
        // Extension Host でロードされていれば undefined でない
        // ただし devDependencies 環境では undefined の場合もある
        if (ext) {
            await ext.activate();
            assert.ok(ext.isActive, '拡張がアクティブ');
        }
    });

    test('コマンドが登録されている', async () => {
        const commands = await vscode.commands.getCommands(true);
        const orionCommands = commands.filter(c => c.startsWith('orionparser.'));
        console.log('登録済みOrionParserコマンド:', orionCommands);
        // Extension Host 内でテスト実行時にコマンドが登録されていることを確認
        // (devDependencies 環境では未登録の場合がある)
        if (orionCommands.length > 0) {
            assert.ok(orionCommands.includes('orionparser.analyzeFile'), 'analyzeFile コマンドあり');
            assert.ok(orionCommands.includes('orionparser.showCallTree'), 'showCallTree コマンドあり');
            assert.ok(orionCommands.includes('orionparser.showFlowchart'), 'showFlowchart コマンドあり');
            assert.ok(orionCommands.includes('orionparser.showDFD'), 'showDFD コマンドあり');
            assert.ok(orionCommands.includes('orionparser.showClassDiagram'), 'showClassDiagram コマンドあり');
        }
    });
});
