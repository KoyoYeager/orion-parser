import * as vscode from 'vscode';
import { execFile } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

export class PythonBridge {
    private pythonPath: string;

    constructor() {
        const config = vscode.workspace.getConfiguration('orionparser');
        this.pythonPath = config.get<string>('pythonPath', 'python');
    }

    /**
     * Resolve the orionparser src directory.
     * Priority:
     *   1. User setting orionparser.orionParserPath
     *   2. Workspace folder containing src/orionparser/
     *   3. Relative path from extension (dev mode)
     *   4. Parent of the target file being analyzed
     */
    private resolveBridgePath(targetFile?: string): string {
        // 1. User config
        const config = vscode.workspace.getConfiguration('orionparser');
        const customPath = config.get<string>('orionParserPath', '');
        if (customPath && fs.existsSync(path.join(customPath, 'orionparser', 'vscode_bridge.py'))) {
            return customPath;
        }

        // 2. Search workspace folders
        const workspaceFolders = vscode.workspace.workspaceFolders || [];
        for (const folder of workspaceFolders) {
            const candidate = path.join(folder.uri.fsPath, 'src');
            if (fs.existsSync(path.join(candidate, 'orionparser', 'vscode_bridge.py'))) {
                return candidate;
            }
        }

        // 3. Relative from extension (dev mode: __dirname = vscode-extension/out/backend)
        const devPath = path.join(__dirname, '..', '..', '..', 'src');
        if (fs.existsSync(path.join(devPath, 'orionparser', 'vscode_bridge.py'))) {
            return devPath;
        }

        // 4. Walk up from target file
        if (targetFile) {
            let dir = path.dirname(targetFile);
            for (let i = 0; i < 10; i++) {
                const candidate = path.join(dir, 'src');
                if (fs.existsSync(path.join(candidate, 'orionparser', 'vscode_bridge.py'))) {
                    return candidate;
                }
                const parent = path.dirname(dir);
                if (parent === dir) { break; }
                dir = parent;
            }
        }

        // Fallback: hope it's pip-installed
        return '';
    }

    async execute(command: string, target: string): Promise<any> {
        return new Promise((resolve, reject) => {
            const bridgePath = this.resolveBridgePath(target);
            const env: NodeJS.ProcessEnv = { ...process.env, PYTHONIOENCODING: 'utf-8' };
            if (bridgePath) {
                env.PYTHONPATH = bridgePath;
            }

            execFile(
                this.pythonPath,
                ['-m', 'orionparser.vscode_bridge', command, target],
                { env, maxBuffer: 50 * 1024 * 1024, timeout: 60000, encoding: 'utf-8' },
                (error, stdout, stderr) => {
                    if (error) {
                        const hint = bridgePath
                            ? `\nPYTHONPATH=${bridgePath}`
                            : '\nHint: Set orionparser.orionParserPath in settings';
                        reject(new Error(`Python bridge error: ${error.message}\n${stderr}${hint}`));
                        return;
                    }
                    try {
                        const result = JSON.parse(stdout);
                        if (result.error) {
                            reject(new Error(result.error));
                        } else {
                            resolve(result);
                        }
                    } catch (e) {
                        reject(new Error(`JSON parse error: ${stdout.substring(0, 500)}`));
                    }
                }
            );
        });
    }

    async analyzeAll(filePath: string): Promise<any> { return this.execute('all', filePath); }
    async getSymbols(filePath: string): Promise<any> { return this.execute('symbols', filePath); }
    async getCallTree(filePath: string): Promise<any> { return this.execute('calltree', filePath); }
    async getFlowchart(filePath: string): Promise<any> { return this.execute('flowchart', filePath); }
    async getDFD(filePath: string): Promise<any> { return this.execute('dfd', filePath); }
    async getClassDiagram(filePath: string): Promise<any> { return this.execute('classdiagram', filePath); }
    async getTokens(filePath: string): Promise<any> { return this.execute('tokens', filePath); }
}
