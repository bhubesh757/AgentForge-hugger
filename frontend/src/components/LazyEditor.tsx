import { lazy, Suspense, type ComponentProps } from 'react';
import { Spinner } from './ui';
const CodeEditor = lazy(() => import('./CodeEditor'));
export default function LazyEditor(props: ComponentProps<typeof CodeEditor>) {
  return <Suspense fallback={<Spinner label="Loading editor…" />}><CodeEditor {...props} /></Suspense>;
}
