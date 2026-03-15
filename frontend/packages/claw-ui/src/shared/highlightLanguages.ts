/**
 * PrismLight language registration — 17 languages, tree-shaken.
 * Import this module once (side-effect) before using <HighlightedCode />.
 */
import { PrismLight } from 'react-syntax-highlighter';

import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx';
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import xml from 'react-syntax-highlighter/dist/esm/languages/prism/xml-doc';
import diff from 'react-syntax-highlighter/dist/esm/languages/prism/diff';
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c';

PrismLight.registerLanguage('python', python);
PrismLight.registerLanguage('javascript', javascript);
PrismLight.registerLanguage('js', javascript);
PrismLight.registerLanguage('typescript', typescript);
PrismLight.registerLanguage('ts', typescript);
PrismLight.registerLanguage('tsx', tsx);
PrismLight.registerLanguage('jsx', jsx);
PrismLight.registerLanguage('css', css);
PrismLight.registerLanguage('go', go);
PrismLight.registerLanguage('java', java);
PrismLight.registerLanguage('rust', rust);
PrismLight.registerLanguage('sql', sql);
PrismLight.registerLanguage('yaml', yaml);
PrismLight.registerLanguage('yml', yaml);
PrismLight.registerLanguage('json', json);
PrismLight.registerLanguage('bash', bash);
PrismLight.registerLanguage('shell', bash);
PrismLight.registerLanguage('sh', bash);
PrismLight.registerLanguage('markdown', markdown);
PrismLight.registerLanguage('md', markdown);
PrismLight.registerLanguage('xml', xml);
PrismLight.registerLanguage('html', xml);
PrismLight.registerLanguage('diff', diff);
PrismLight.registerLanguage('c', c);
