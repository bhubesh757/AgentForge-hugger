import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';

// Use the locally bundled monaco-editor (no CDN) — works offline and on GitHub Pages.
self.MonacoEnvironment = { getWorker: (_id: string, label: string) => (label === 'json' ? new JsonWorker() : new EditorWorker()) };
loader.config({ monaco });

export default function CodeEditor({ value, onChange, language = 'json', height = 280, readOnly }: { value: string; onChange?: (v: string) => void; language?: string; height?: number | string; readOnly?: boolean }) {
  const dark = document.documentElement.classList.contains('dark');
  return (
    <div className="overflow-hidden rounded-md border border-slate-300 dark:border-slate-700">
      <Editor height={height} language={language} value={value} theme={dark ? 'vs-dark' : 'light'} onChange={(v) => onChange?.(v ?? '')}
        options={{ minimap: { enabled: false }, fontSize: 13, readOnly, scrollBeyondLastLine: false, automaticLayout: true, tabSize: language === 'python' ? 4 : 2 }} />
    </div>
  );
}
