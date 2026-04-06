import * as vscode from 'vscode';
import { execFile } from 'child_process';
import * as path from 'path';

export class PythonBridge {
    private pythonPath: string;
    private bridgePath: string;

    constructor() {
        const config = vscode.workspace.getConfiguration('orionparser');
        this.pythonPath = config.get<string>('pythonPath', 'python');
        const customPath = config.get<string>('orionParserPath', '');
        this.bridgePath = customPath || path.join(__dirname, '..', '..', '..', 'src');
    }

    async execute(command: string, target: string): Promise<any> {
        return new Promise((resolve, reject) => {
            const env = { ...process.env, PYTHONPATH: this.bridgePath, PYTHONIOENCODING: 'utf-8' };
            execFile(
                this.pythonPath,
                ['-m', 'orionparser.vscode_bridge', command, target],
                { env, maxBuffer: 50 * 1024 * 1024, timeout: 60000, encoding: 'utf-8' },
                (error, stdout, stderr) => {
                    if (error) {
                        reject(new Error(`Python bridge error: ${error.message}\n${stderr}`));
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

    async analyzeAll(filePath: string): Promise<any> {
        return this.execute('all', filePath);
    }

    async getSymbols(filePath: string): Promise<any> {
        return this.execute('symbols', filePath);
    }

    async getCallTree(filePath: string): Promise<any> {
        return this.execute('calltree', filePath);
    }

    async getFlowchart(filePath: string): Promise<any> {
        return this.execute('flowchart', filePath);
    }

    async getDFD(filePath: string): Promise<any> {
        return this.execute('dfd', filePath);
    }

    async getClassDiagram(filePath: string): Promise<any> {
        return this.execute('classdiagram', filePath);
    }

    async getTokens(filePath: string): Promise<any> {
        return this.execute('tokens', filePath);
    }
}
